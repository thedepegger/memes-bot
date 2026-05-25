---
description: Rules for LLM-driven picker, caption writer, and Imgflip renderer.
globs:
  - src/generators/**
  - src/utils/llm.py
  - config/templates.json
  - config/voice.json
alwaysApply: false
---

# Generators Rules

## Shared LLM client (`src/utils/llm.py`)

Both picker and caption use the same `AsyncOpenAI` client pointed at OpenRouter. Do not instantiate a second client. Required headers for ranking attribution:

```python
default_headers={
    "HTTP-Referer": settings.OPENROUTER_APP_URL,
    "X-Title": settings.OPENROUTER_APP_NAME,
}
```

`call_llm(system, user, max_tokens, temperature)` is the only entrypoint. Picker uses `max_tokens=500, temperature=0.8`; caption uses `max_tokens=100`.

## `picker.py` — template selection

- System prompt embeds the full `config/templates.json` pool.
- Output is **strict JSON, no markdown fences**: `{template_id, template_name, boxes[], reasoning}`.
- Parse with `json.loads` inside a `try/except`. On parse failure, retry **once** with a stricter "JSON ONLY, NO PROSE" prompt. Then skip the news item.
- Each text box: **max 60 chars, lowercase, no emojis, no hashtags.** Post-check after parse; on violation, also retry once then skip.
- Template-to-vibe mapping is in the system prompt — keep it in sync with `templates.json` `best_for` tags.

## `caption.py` — chaos goblin voice

- Voice rules live in `config/voice.json` and the system prompt. Both must stay in sync.
- **Tone is pre-picked in Python** via weighted random from `voice.json.tone_weights` (bull 25 / bear 25 / cope 20 / euphoria 15 / doom 15). Pass the chosen tone into the user message; do not let the LLM pick.
- Hard rules (enforce in prompt AND post-check): all lowercase, 4-15 words, no hashtags, no emojis, ≤1 cashtag.
- Output is **caption text only** — no quotes, no preamble. Strip surrounding whitespace before save.
- Contradictions across posts are a **feature** (chaos goblin). Do not try to maintain a consistent stance.

## `meme.py` — Imgflip render

- Endpoint: `POST https://api.imgflip.com/caption_image` (form-encoded).
- Build form data: `template_id`, `username`, `password`, `boxes[0][text]`, `boxes[1][text]`, ... (one per box defined in template).
- **Check `response.json()["success"]`** — `false` is not an exception. Log error, skip candidate, return `None`. Do not retry same template.
- After success, do a `HEAD` request against returned `url` to confirm the image loads before queuing in TG. If HEAD fails, treat as render failure.
- Store the Imgflip `url` directly on the candidate row; don't proxy or re-host.
