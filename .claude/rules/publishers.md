---
description: Rules for Telegram approval flow and X (Twitter) posting.
globs:
  - src/publishers/**
alwaysApply: false
---

# Publishers Rules

## `telegram.py` — approval flow

- `aiogram` v3, **polling mode** (no webhooks in v1).
- **Hard admin check** at the top of every handler: `if message.from_user.id != settings.TELEGRAM_ADMIN_USER_ID: return`. Do not respond, do not log PII beyond user_id.
- Drop format: `bot.send_photo(chat_id=TELEGRAM_CHANNEL_ID, photo=image_url, caption=preview_text, reply_markup=kb)`.
- Inline keyboard (2x2): `[✓ Approve] [🔄 Regen] / [⏭ Skip] [✏ Edit]`. Emojis here are **Telegram UI glyphs only** — they never leak into the tweet caption.
- Callback data format: `f"{action}:{candidate_id}"` where action ∈ `approve | regen | skip | edit`.
- On approve: set status `approved`, compute `scheduled_for` via `utils/time_windows.compute_post_schedule`, edit TG message to `✅ approved, scheduled for {time}`.
- On regen: set status `rejected` (keep row for analytics), trigger picker for the **same news item but excluding the used template_id**.
- On skip: set status `rejected`. Do nothing else.
- On edit: bot replies `send new caption text (5min timeout)`. Track pending edit in an in-memory dict `{admin_user_id: candidate_id}`. Next text message from admin replaces the caption; re-render preview with buttons. Clear the entry after edit received OR after 5min timeout.
- Auto-expire pending candidates after 24hr — mark `rejected` with reason `expired`.

## `twitter.py` — X posting

- **Media upload uses v1.1; tweet creation uses v2.** Both are required for the free tier.
  - `api_v1 = tweepy.API(OAuth1UserHandler(...))`
  - `client_v2 = tweepy.Client(consumer_key=..., consumer_secret=..., access_token=..., access_token_secret=...)`
- Flow per candidate:
  1. Download image from `candidate.image_url` to a temp file.
  2. `media = api_v1.media_upload(filename=tmp_path)` → grab `media.media_id`.
  3. `tweet = client_v2.create_tweet(text=candidate.caption, media_ids=[media.media_id])`.
  4. Return `tweet.data["id"]`. Delete the temp file in a `finally`.
- **No URL in caption.** The meme is the tweet — caption text only.
- On `tweepy.TooManyRequests`: do not crash. Push candidate back with `scheduled_for += 30min`, leave status `approved`.
- On other `tweepy` errors: log + mark candidate `failed`, store error in a debug log line. Do not retry automatically.
- Respect the **15-minute minimum gap** between posts — enforced by scheduler, but `twitter.py` should refuse and reschedule if `now - last_posted_at < 15min`.
- Free tier hard limits: **500 tweets/month**, target 8-10/day. Do not bypass these in code or env.
