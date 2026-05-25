---
id: 01-foundation
title: Foundation — env files, settings, logger, LLM client, config data, package skeletons
phase: 0
depends_on: []
parallel_with: []
blocks: [02, 03, 04, 05, 06, 07, 08, 09, 10]
files:
  create:
    - pyproject.toml
    - requirements.txt
    - .env.example
    - .gitignore
    - config/settings.py
    - config/templates.json
    - config/voice.json
    - src/__init__.py
    - src/utils/__init__.py
    - src/utils/logger.py
    - src/utils/llm.py
    - src/storage/__init__.py
    - src/fetchers/__init__.py
    - src/generators/__init__.py
    - src/publishers/__init__.py
    - src/scheduler/__init__.py
    - tests/__init__.py
references:
  must_read:
    - CLAUDE.md (entire file — every later task assumes you've internalised the conventions)
    - .claude/rules/generators.md (the OpenRouter header section drives utils/llm.py)
    - docs/plan.md §3 (Tech Stack), §6 (env vars), §8.4 (LLM client snippet), §9 (templates), §10 (voice config)
exposes:
  - config.settings.settings — singleton pydantic-settings object; all env reads go through this
  - src.utils.logger.logger — pre-configured loguru logger
  - src.utils.llm.call_llm(system, user, max_tokens=500, temperature=0.8) -> str (async)
  - config/templates.json and config/voice.json on disk (load via json.load in consumers)
---

# Task 01 — Foundation

## Goal
Stand up the project shell so every downstream task can `from config.settings import settings`, `from src.utils.logger import logger`, and `from src.utils.llm import call_llm` without anything missing. **Owns every empty `__init__.py`** so later parallel tasks never race on package creation.

## Files to create

### Bootstrap
- `pyproject.toml` — package metadata, Python `>=3.11`. Keep config minimal (ruff/black optional).
- `requirements.txt` — pin: `aiogram>=3,<4`, `tweepy>=4,<5`, `openai>=1.10`, `httpx`, `feedparser`, `apscheduler>=3,<4`, `sqlalchemy>=2`, `pydantic-settings`, `loguru`, `pytest`, `pytest-asyncio`.
- `.env.example` — **copy verbatim from `docs/plan.md` §6**.
- `.gitignore` — Python defaults plus `.env`, `data/`, `logs/`, `*.db`, `.venv/`, `__pycache__/`.

### Settings + static config
- `config/settings.py` — `Settings(BaseSettings)` with all env vars from `.env.example`. Use `model_config = SettingsConfigDict(env_file=".env")`. Export module-level `settings = Settings()`. Defaults: `OPENROUTER_APP_NAME="crypto-meme-bot"`, `OPENROUTER_APP_URL="https://github.com/depegger/crypto-meme-bot"`.
- `config/templates.json` — **copy verbatim from `docs/plan.md` §9**.
- `config/voice.json` — **copy verbatim from `docs/plan.md` §10**.

### Shared infra
- `src/utils/logger.py` — configure loguru once. Sink to `logs/bot.log` with 10MB rotation, 14d retention. Level from `settings.LOG_LEVEL`. Export the `logger` object.
- `src/utils/llm.py` — implement exactly the snippet in `docs/plan.md` §8.4 (and `.claude/rules/generators.md`). `AsyncOpenAI` pointed at `settings.OPENROUTER_BASE_URL`, headers `HTTP-Referer` + `X-Title`, single `call_llm(system, user, max_tokens, temperature)` async function.

### Package skeletons (empty files)
`src/__init__.py`, `src/utils/__init__.py`, `src/storage/__init__.py`, `src/fetchers/__init__.py`, `src/generators/__init__.py`, `src/publishers/__init__.py`, `src/scheduler/__init__.py`, `tests/__init__.py`. **Owning these here is what lets Phase 1+ tasks run in parallel without colliding.**

## Implementation notes
- Do NOT create `README.md` — not requested.
- Do NOT ship a real `.env`. Only `.env.example`.
- Settings field names must match `.env.example` keys exactly (uppercase).
- `WARMUP_MODE` is a `bool`; pydantic parses `"true"`/`"false"` from env.

## Hand-off contract (downstream tasks rely on these stable imports)
```python
from config.settings import settings
from src.utils.logger import logger
from src.utils.llm import call_llm
```

## Acceptance criteria
- `python -c "from config.settings import settings; print(settings.LLM_MODEL)"` prints the default.
- `python -c "from src.utils.logger import logger; logger.info('ok')"` writes to console and `logs/bot.log`.
- `python -c "from src.utils.llm import call_llm; print(call_llm)"` imports without error (do NOT actually call OpenRouter).
- `pip install -r requirements.txt` resolves with no conflicts.
