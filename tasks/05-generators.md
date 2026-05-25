---
id: 05-generators
title: Picker + caption + meme renderer (LLM pipeline)
phase: 1
depends_on: [01]
parallel_with: [02, 03, 04]
blocks: [07, 09, 10]
files:
  create:
    - src/generators/types.py
    - src/generators/picker.py
    - src/generators/caption.py
    - src/generators/meme.py
references:
  must_read:
    - CLAUDE.md (Key Decisions, Critical Gotchas, Conventions)
    - .claude/rules/generators.md (canonical rules — read fully, every section applies)
    - docs/plan.md §8.4 (picker prompt), §8.5 (caption prompt), §8.6 (meme render)
  also_useful:
    - tasks/01-foundation.md (call_llm, settings.IMGFLIP_*)
    - tasks/03-fetchers-easy.md (SentimentReading shape — caption consumes it)
    - config/templates.json + config/voice.json (loaded at import time)
exposes:
  - src.generators.types.TemplateChoice — (template_id: str, template_name: str, boxes: list[str], reasoning: str)
  - src.generators.types.NewsItem — (id: str, title: str, url: str, source: str, published_at: datetime)
  - src.generators.picker.pick_template(news, sentiment, exclude_template_ids: list[str] = []) -> TemplateChoice | None (async)
  - src.generators.caption.write_caption(news, template, sentiment, trending) -> str (async)
  - src.generators.meme.render_meme(template) -> str | None (async; returns Imgflip URL)
---

# Task 05 — Generators (LLM pipeline)

## Goal
The three pure transformations that turn a news item into a renderable meme + caption. **None of these write to the DB.** The scheduler (Task 09) persists candidates.

**Co-relation rationale:** picker + caption both consume `utils/llm.call_llm`. picker + meme share the `TemplateChoice` contract (picker emits, meme consumes). caption needs `TemplateChoice` for context. Splitting risks type drift. One agent owns the pipeline.

## Files to create

### `src/generators/types.py`
- `TemplateChoice` and `NewsItem` dataclasses. Define **once** here; fetchers and publishers import from here. Avoids duplicate definitions.

### `src/generators/picker.py`
- Load `config/templates.json` at module import time.
- System prompt per `docs/plan.md` §8.4 — embed the full template pool as JSON.
- Call `call_llm(system, user, max_tokens=500, temperature=0.8)`.
- Parse output strictly with `json.loads`. On `JSONDecodeError`: retry **once** with a stricter "JSON ONLY, NO PROSE, NO MARKDOWN FENCES" prompt; on second failure, log + return `None`.
- Post-check each box: `≤60 chars`, lowercase, no emoji, no `#`. On violation: retry once then return `None`.
- Honor `exclude_template_ids` by filtering the pool before embedding in the prompt (Task 07's regen flow passes the previous template's id).

### `src/generators/caption.py`
- Load `config/voice.json` at module import time.
- **Pick tone in Python** via `random.choices` weighted by `voice.json.tone_weights`. Pass the chosen tone into the user message. The LLM does NOT pick tone.
- System prompt per `docs/plan.md` §8.5.
- Call `call_llm(system, user, max_tokens=100, temperature=0.8)`.
- Strip surrounding whitespace + quotes from the result.
- Post-check: lowercase, 4–15 words, no emoji, no hashtag, ≤1 cashtag. On violation, retry once; if still bad, log and return a tone-appropriate fallback (e.g. `"down bad"` for bear, `"we're so back"` for bull) so the pipeline never blocks on a bad caption.

### `src/generators/meme.py`
- `POST https://api.imgflip.com/caption_image` form-encoded via `httpx`.
- Body fields: `template_id`, `username`, `password`, then `boxes[0][text]`, `boxes[1][text]`, ... up to len(boxes).
- **Check `response.json()["success"]`** — `false` is not an exception. On failure: log error_message, return `None`. **Do not retry the same template.**
- On success: HEAD-request the returned URL. If HEAD fails or non-2xx, treat as render failure (return `None`).

## Implementation notes
- All three functions are `async`.
- No file in `src/generators/` may import from `src/storage/` or `src/publishers/`.
- No file in `src/generators/` writes to the DB or to disk (other than logs).

## Hand-off contract
- Task 07's regen handler calls `pick_template(news, sentiment, exclude_template_ids=[old_template_id])`.
- Task 09's `job_generate_batch` chains: `pick_template → render_meme → write_caption → repository.save_candidate(...)`.
- `TemplateChoice.boxes` is a `list[str]` in **template-defined order** (drake: `[no_this, yes_this]`).

## Acceptance criteria
- With mocked `call_llm` returning valid JSON: `pick_template` returns a `TemplateChoice` matching the JSON.
- With mocked `call_llm` returning malformed JSON twice: returns `None`, failure logged.
- `write_caption` output is always lowercase, 4–15 words, no emoji, ≤1 cashtag.
- `write_caption` with violating LLM output returns a safe fallback rather than raising.
- `render_meme` returns a URL string on `success:true`, `None` on `success:false`.
- No call to picker/caption/meme touches the DB (verify with `tmp_db` fixture asserting zero rows after).
