"""Telegram approval flow — aiogram v3 polling bot.

Drops candidates with `[Approve][Regen][Skip][Edit]` inline buttons into the
private channel and routes operator callbacks back into the storage + generator
pipeline. Single admin (`settings.TELEGRAM_ADMIN_USER_ID`); everyone else is
silently rejected — no response, no PII logged.

State machine handoff:
- approve -> repository.mark_approved + record_template_usage + edit TG msg
- regen   -> repository.mark_rejected("regen") + fresh pick/render/caption +
             drop_to_telegram(new_candidate)
- skip    -> repository.mark_rejected("skip") + edit TG msg
- edit    -> prompt for new caption text within 5 minutes, then update_caption
             and redrop with the same image.

TG UI emojis (✓ 🔄 ⏭ ✏ ✅) are Telegram inline-keyboard glyphs only and never
appear in actual tweet captions — caption emoji enforcement lives in
`src/generators/caption.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from config.settings import settings
from src.fetchers.sentiment import fetch_sentiment
from src.fetchers.trending import fetch_trending
from src.generators.caption import write_caption
from src.generators.meme import render_meme
from src.generators.picker import pick_template
from src.generators.types import NewsItem
from src.storage import repository
from src.utils.dedup import hash_topic
from src.utils.logger import logger


# Edit-flow state. Maps admin user id to (candidate_id, expiry_utc).
# Single-process bot, single admin, so a plain dict is fine for v1.
_pending_edits: dict[int, tuple[int, datetime]] = {}

# How long the operator has to send their new caption after tapping Edit.
_EDIT_TIMEOUT = timedelta(minutes=5)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _is_admin(user_id: Optional[int]) -> bool:
    """Hard-check helper. Centralized so we never compare against the wrong int."""
    return user_id is not None and user_id == settings.TELEGRAM_ADMIN_USER_ID


def _build_keyboard(candidate_id: int) -> InlineKeyboardMarkup:
    """2x2 inline keyboard for a pending candidate."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✓ Approve",
                    callback_data=f"approve:{candidate_id}",
                ),
                InlineKeyboardButton(
                    text="\U0001F504 Regen",
                    callback_data=f"regen:{candidate_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏭ Skip",
                    callback_data=f"skip:{candidate_id}",
                ),
                InlineKeyboardButton(
                    text="✏ Edit",
                    callback_data=f"edit:{candidate_id}",
                ),
            ],
        ]
    )


def _build_preview_text(candidate) -> str:
    """Caption shown on the drop, per task §Drop format."""
    title_snippet = (candidate.news_title or "")[:100]
    template_name = candidate.template_name or candidate.template_id
    label = candidate.sentiment_label or "unknown"
    score = candidate.sentiment_score
    score_str = (
        str(int(score)) if isinstance(score, (int, float)) else "?"
    )
    return (
        f"\U0001F4F0 {title_snippet}\n\n"
        f"\U0001F4AC caption:\n"
        f"{candidate.caption}\n\n"
        f"\U0001F3AD template: {template_name} | "
        f"sentiment: {label} ({score_str})"
    )


def build_bot() -> Bot:
    """Construct an aiogram Bot with HTML parse-mode defaults.

    Token comes from `settings.TELEGRAM_BOT_TOKEN`. We do not validate it
    here — aiogram raises on the first API call if it's malformed.
    """
    return Bot(
        token=settings.TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=None),
    )


def build_dispatcher() -> Dispatcher:
    """Construct a Dispatcher with all approval-flow handlers pre-registered."""
    dp = Dispatcher()

    dp.callback_query.register(
        _on_approve, F.data.startswith("approve:")
    )
    dp.callback_query.register(
        _on_regen, F.data.startswith("regen:")
    )
    dp.callback_query.register(
        _on_skip, F.data.startswith("skip:")
    )
    dp.callback_query.register(
        _on_edit, F.data.startswith("edit:")
    )
    # Catches the admin's reply with a new caption after tapping Edit.
    dp.message.register(_on_text)

    return dp


# ---------------------------------------------------------------------------
# Drop
# ---------------------------------------------------------------------------


async def drop_to_telegram(candidate) -> None:
    """Send a candidate to the private channel with inline approval buttons.

    Persists the returned `message.message_id` on the candidate row so later
    handlers can edit the same message in place. Swallows aiogram errors and
    logs them — callers (scheduler) should not crash if Telegram is flaky.
    """
    bot = build_bot()
    try:
        preview = _build_preview_text(candidate)
        kb = _build_keyboard(candidate.id)
        try:
            msg = await bot.send_photo(
                chat_id=settings.TELEGRAM_CHANNEL_ID,
                photo=candidate.image_url,
                caption=preview,
                reply_markup=kb,
            )
        except Exception as exc:
            logger.error(
                f"drop_to_telegram: send_photo failed for candidate "
                f"{candidate.id}: {exc!r}"
            )
            return

        try:
            repository.set_tg_message_id(candidate.id, msg.message_id)
        except Exception as exc:
            logger.error(
                f"drop_to_telegram: set_tg_message_id failed for candidate "
                f"{candidate.id}: {exc!r}"
            )
    finally:
        await bot.session.close()


# ---------------------------------------------------------------------------
# Callback handlers
# ---------------------------------------------------------------------------


def _parse_callback(data: Optional[str]) -> Optional[int]:
    """Parse `action:{id}` callback data into the candidate id (or None)."""
    if not data or ":" not in data:
        return None
    _, _, raw_id = data.partition(":")
    try:
        return int(raw_id)
    except ValueError:
        return None


def _sweep_pending_edits(now: datetime) -> None:
    """Drop any pending-edit entries whose 5-minute timer has expired."""
    expired = [uid for uid, (_, exp) in _pending_edits.items() if exp < now]
    for uid in expired:
        _pending_edits.pop(uid, None)


async def _on_approve(event: CallbackQuery) -> None:
    if not _is_admin(event.from_user.id if event.from_user else None):
        return  # silent reject
    _sweep_pending_edits(datetime.utcnow())

    candidate_id = _parse_callback(event.data)
    if candidate_id is None:
        return

    try:
        candidate = repository.get_candidate(candidate_id)
        if candidate is None:
            logger.warning(f"approve: candidate {candidate_id} not found")
            try:
                await event.answer("not found")
            except Exception:
                pass
            return

        now = datetime.utcnow()
        from src.utils.time_windows import compute_post_schedule

        scheduled_for = compute_post_schedule(
            now,
            repository.posts_today_count(),
            repository.get_last_scheduled(),
        )
        repository.mark_approved(candidate_id, scheduled_for)

        topic_hash = hash_topic(candidate.news_title or "")
        try:
            repository.record_template_usage(
                candidate.template_id, topic_hash
            )
        except Exception as exc:
            logger.error(
                f"approve: record_template_usage failed for candidate "
                f"{candidate_id}: {exc!r}"
            )

        delta_minutes = max(
            0, int((scheduled_for - now).total_seconds() // 60)
        )
        new_text = (
            f"✅ approved, scheduled for "
            f"{scheduled_for.strftime('%H:%M')} UTC "
            f"({delta_minutes}min)"
        )
        try:
            await event.message.edit_caption(caption=new_text)
        except Exception as exc:
            logger.warning(
                f"approve: edit_caption failed for candidate "
                f"{candidate_id}: {exc!r}"
            )

        try:
            await event.answer()
        except Exception:
            pass
    except Exception as exc:
        logger.error(
            f"approve handler error for candidate {candidate_id}: {exc!r}"
        )
        try:
            await event.answer()
        except Exception:
            pass


async def _on_regen(event: CallbackQuery) -> None:
    if not _is_admin(event.from_user.id if event.from_user else None):
        return
    _sweep_pending_edits(datetime.utcnow())

    candidate_id = _parse_callback(event.data)
    if candidate_id is None:
        return

    try:
        candidate = repository.get_candidate(candidate_id)
        if candidate is None:
            logger.warning(f"regen: candidate {candidate_id} not found")
            try:
                await event.answer("not found")
            except Exception:
                pass
            return

        repository.mark_rejected(candidate_id, reason="regen")
        try:
            await event.message.edit_caption(caption="\U0001F504 regenerating...")
        except Exception:
            pass

        # Reconstruct a NewsItem from the candidate's denormalised fields.
        news = NewsItem(
            id=candidate.news_id or "",
            title=candidate.news_title or "",
            url=candidate.news_url or "",
            source="",
            published_at=datetime.utcnow(),
        )

        sentiment = await fetch_sentiment()
        trending = await fetch_trending()

        new_template = await pick_template(
            news,
            sentiment,
            exclude_template_ids=[candidate.template_id],
        )
        if new_template is None:
            logger.warning(
                f"regen: pick_template returned None for candidate "
                f"{candidate_id}"
            )
            try:
                await event.answer("regen failed")
            except Exception:
                pass
            return

        image_url = await render_meme(new_template)
        if not image_url:
            logger.warning(
                f"regen: render_meme failed for candidate {candidate_id}"
            )
            try:
                await event.answer("regen failed")
            except Exception:
                pass
            return

        caption = await write_caption(news, new_template, sentiment, trending)

        new_candidate = repository.save_candidate(
            news_id=candidate.news_id,
            news_title=candidate.news_title,
            news_url=candidate.news_url,
            template_id=new_template.template_id,
            template_name=new_template.template_name,
            text_boxes=new_template.boxes,
            caption=caption,
            image_url=image_url,
            sentiment_score=sentiment.score,
            sentiment_label=sentiment.label,
        )

        await drop_to_telegram(new_candidate)
        try:
            await event.answer("regenerated")
        except Exception:
            pass
    except Exception as exc:
        logger.error(
            f"regen handler error for candidate {candidate_id}: {exc!r}"
        )
        try:
            await event.answer()
        except Exception:
            pass


async def _on_skip(event: CallbackQuery) -> None:
    if not _is_admin(event.from_user.id if event.from_user else None):
        return
    _sweep_pending_edits(datetime.utcnow())

    candidate_id = _parse_callback(event.data)
    if candidate_id is None:
        return

    try:
        repository.mark_rejected(candidate_id, reason="skip")
        try:
            await event.message.edit_caption(caption="⏭ skipped")
        except Exception as exc:
            logger.warning(
                f"skip: edit_caption failed for candidate "
                f"{candidate_id}: {exc!r}"
            )
        try:
            await event.answer()
        except Exception:
            pass
    except Exception as exc:
        logger.error(
            f"skip handler error for candidate {candidate_id}: {exc!r}"
        )
        try:
            await event.answer()
        except Exception:
            pass


async def _on_edit(event: CallbackQuery) -> None:
    if not _is_admin(event.from_user.id if event.from_user else None):
        return
    now = datetime.utcnow()
    _sweep_pending_edits(now)

    candidate_id = _parse_callback(event.data)
    if candidate_id is None:
        return

    try:
        admin_id = event.from_user.id  # already admin-verified above
        _pending_edits[admin_id] = (
            candidate_id,
            now + _EDIT_TIMEOUT,
        )
        try:
            await event.message.reply(
                "send new caption text (5min timeout)"
            )
        except Exception as exc:
            logger.warning(
                f"edit: reply failed for candidate {candidate_id}: {exc!r}"
            )
        try:
            await event.answer()
        except Exception:
            pass
    except Exception as exc:
        logger.error(
            f"edit handler error for candidate {candidate_id}: {exc!r}"
        )
        try:
            await event.answer()
        except Exception:
            pass


async def _on_text(event: Message) -> None:
    """Catch the admin's reply with a new caption after they tapped Edit.

    Non-admin messages are silently dropped. Non-pending admin messages are
    ignored (no echo, no error reply) so the bot doesn't spam the channel.
    """
    if not _is_admin(event.from_user.id if event.from_user else None):
        return
    now = datetime.utcnow()
    _sweep_pending_edits(now)

    admin_id = event.from_user.id
    pending = _pending_edits.get(admin_id)
    if pending is None:
        return

    candidate_id, _ = pending
    new_caption = (event.text or "").strip()
    if not new_caption:
        return

    # Consume the pending entry up-front so a flaky drop doesn't leave us
    # in a state where every admin text keeps redropping.
    _pending_edits.pop(admin_id, None)

    try:
        candidate = repository.get_candidate(candidate_id)
        if candidate is None:
            logger.warning(
                f"edit-text: candidate {candidate_id} not found"
            )
            return

        repository.update_caption(candidate_id, new_caption)
        fresh = repository.get_candidate(candidate_id)
        if fresh is None:
            return
        await drop_to_telegram(fresh)
    except Exception as exc:
        logger.error(
            f"edit-text handler error for candidate {candidate_id}: {exc!r}"
        )


# ---------------------------------------------------------------------------
# Polling entrypoint
# ---------------------------------------------------------------------------


async def run_polling(dispatcher: Dispatcher, bot: Bot) -> None:
    """Boot the polling loop. Sweeps stale pending candidates on startup.

    Long-lived async task — call from `src/main.py` via `asyncio.create_task`.
    """
    try:
        expired = repository.expire_stale_pending(hours=24)
        if expired:
            logger.info(
                f"run_polling: expired {expired} stale pending candidates "
                f"on startup"
            )
    except Exception as exc:
        logger.error(f"run_polling: expire_stale_pending failed: {exc!r}")

    await dispatcher.start_polling(bot)


__all__ = [
    "build_bot",
    "build_dispatcher",
    "drop_to_telegram",
    "run_polling",
]
