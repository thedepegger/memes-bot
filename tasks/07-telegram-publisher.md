---
id: 07-telegram-publisher
title: aiogram approval flow (approve/regen/skip/edit)
phase: 2
depends_on: [01, 02, 04]
parallel_with: [06, 08]
blocks: [09]
files:
  create:
    - src/publishers/telegram.py
references:
  must_read:
    - CLAUDE.md (Critical Gotchas — admin hard-check, TG emoji ≠ tweet emoji; Conventions)
    - .claude/rules/publishers.md (canonical rules — telegram section, read fully)
    - docs/plan.md §8.7 (telegram module), §11 (approval flow UX)
  also_useful:
    - tasks/02-storage.md (mark_approved, mark_rejected, save_candidate, posts_today_count, record_template_usage)
    - tasks/04-time-windows.md (compute_post_schedule)
    - tasks/05-generators.md (pick_template / write_caption / render_meme — used by regen flow)
exposes:
  - src.publishers.telegram.build_bot() -> aiogram.Bot
  - src.publishers.telegram.build_dispatcher() -> aiogram.Dispatcher (handlers pre-registered)
  - src.publishers.telegram.drop_to_telegram(candidate) -> None (async; sends to TELEGRAM_CHANNEL_ID, saves tg_message_id)
  - src.publishers.telegram.run_polling(dispatcher, bot) -> None (async; entry hook for main)
---

# Task 07 — Telegram approval flow

## Goal
aiogram v3 bot in polling mode. Drops candidates with `[Approve][Regen][Skip][Edit]` inline buttons. Handles callbacks. **Single admin** (`settings.TELEGRAM_ADMIN_USER_ID`) — silently rejects everyone else.

## Files to create
- `src/publishers/telegram.py`.

## Implementation notes

### Drop format (send via `bot.send_photo`)
```
[photo: candidate.image_url]

📰 {candidate.news_title[:100]}

💬 caption:
{candidate.caption}

🎭 template: {template_name} | sentiment: {label} ({score})
```
Save the returned `message.message_id` into `candidate.tg_message_id` (call a repository helper or extend save_candidate to support updating after send).

### Inline keyboard (2×2)
- `[✓ Approve]` → callback_data `approve:{id}`
- `[🔄 Regen]` → callback_data `regen:{id}`
- `[⏭ Skip]` → callback_data `skip:{id}`
- `[✏ Edit]` → callback_data `edit:{id}`

These emojis are Telegram UI glyphs only. **They MUST NOT leak into tweet captions** — captions enforce no-emoji independently (Task 05).

### Admin hard-check (first line of EVERY handler)
```python
if event.from_user.id != settings.TELEGRAM_ADMIN_USER_ID:
    return  # silent reject — no response, no log of identifiers
```

### Callback handlers
- **`approve:{id}`** → `scheduled_for = compute_post_schedule(utcnow(), posts_today_count(), get_last_scheduled())` → `repository.mark_approved(id, scheduled_for)` → `repository.record_template_usage(template_id, topic_hash)` → edit TG message text to `✅ approved, scheduled for {hh:mm} UTC ({delta_minutes}min)`.
- **`regen:{id}`** → `repository.mark_rejected(id, reason="regen")` → load the news for that candidate → `pick_template(news, sentiment, exclude_template_ids=[old_template_id])` → `render_meme` → `write_caption` → `save_candidate(...)` → `drop_to_telegram(new_candidate)`.
- **`skip:{id}`** → `repository.mark_rejected(id, reason="skip")` → edit TG message text to `⏭ skipped`.
- **`edit:{id}`** → bot replies `send new caption text (5min timeout)`. Store `_pending_edits[admin_user_id] = (candidate_id, expiry)`. On next text message from admin: replace `candidate.caption` (add a repository helper for this), re-render preview (same image, new caption text), show buttons again. Clear dict entry after edit or after 5min timeout.

### Pending-edit dict (module-level)
```python
_pending_edits: dict[int, tuple[int, datetime]] = {}
```
Sweep stale entries (`expiry < utcnow()`) on every callback fire.

### Stale candidate expiry
A small periodic check (run from a startup task or alongside callbacks): any `Candidate` with `status='pending'` AND `generated_at < utcnow() - 24h` → `mark_rejected(reason="expired")`.

## Hand-off contract
- `build_bot()` + `build_dispatcher()` are called by Task 09's `main.py`.
- `drop_to_telegram(candidate)` is called by Task 09's `job_generate_batch`.

## Acceptance criteria
- Non-admin sender's callback is silently rejected (no `answer_callback_query`, no response).
- Approve flow: status becomes `approved`, `scheduled_for` set, TG message edited.
- Regen flow: new candidate created with **different `template_id`** from the previous one; previous stays `rejected`.
- Edit flow: times out after 5 min if no text arrives.
- All callbacks complete without raising, even when storage helpers fail (catch + log).
