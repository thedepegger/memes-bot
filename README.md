# Crypto Meme Bot

Automated pipeline: fetches crypto news → generates memes via Imgflip templates → drops them in a private Telegram channel for one-tap approval → posts approved memes to X (Twitter) on a schedule.

You (the operator) approve from your phone. The bot does the rest. Target: 8–10 posts/day on X's free API tier.

---

## Quick start (5 commands)

```bash
# 1. Bootstrap — creates venv, installs deps, scaffolds .env
./scripts/setup.sh

# 2. Open .env in your editor and fill in your API keys
#    Don't have keys yet? See docs/SETUP.md §3 — takes ~10 min.

# 3. Smoke test (no Telegram, no X — just verifies the pipeline)
make dry-run

# 4. Run the test suite
make test

# 5. Start the bot for real
make run
```

If anything fails → **[docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)**.

If you've never done any of this before → **[docs/SETUP.md](docs/SETUP.md)** has the long version.

---

## What you need

- **Python 3.11 or newer** (3.11 / 3.12 / 3.13 all work)
- **macOS or Linux** (Windows works but untested — use WSL2)
- ~10 minutes to register for API keys
- About **$20/month** for the paid services ([Costs](#costs) below)

---

## How it works

```
every 2hr   →  fetch crypto news (Cryptopanic + RSS fallback)
every 4hr   →  LLM picks meme template + writes chaos-goblin caption
               → Imgflip renders the image
               → bot drops in your Telegram channel with [Approve][Regen][Skip][Edit]
every 15min →  posts approved memes to X
```

You only tap a button on your phone. Everything else is automatic.

---

## Project layout

```
.
├── README.md                  ← you are here
├── CLAUDE.md                  ← rules for AI-assisted edits
├── Makefile                   ← convenience commands
├── scripts/setup.sh           ← one-shot bootstrap
├── pyproject.toml             ← package metadata + pytest config
├── requirements.txt           ← Python dependencies
├── .env.example               ← template — copy to .env and fill
│
├── config/
│   ├── settings.py            ← env-var loading (pydantic-settings)
│   ├── templates.json         ← Imgflip meme template pool
│   └── voice.json             ← chaos goblin tone weights + lexicon
│
├── src/
│   ├── main.py                ← entrypoint (--dry-run or normal)
│   ├── fetchers/              ← news, sentiment, trending tickers
│   ├── generators/            ← LLM picker + caption + Imgflip render
│   ├── publishers/            ← telegram (review) + twitter (X posting)
│   ├── storage/               ← SQLite + SQLAlchemy ORM
│   ├── scheduler/             ← APScheduler jobs
│   └── utils/                 ← logger, dedup, time windows, shared LLM client
│
├── tests/                     ← pytest suite (18 tests)
│
└── docs/
    ├── SETUP.md               ← full walkthrough for first-timers
    ├── TROUBLESHOOTING.md     ← common errors + fixes
    └── plan.md                ← original build plan (reference)
```

---

## Costs

| Service | Plan | Monthly |
|---|---|---|
| Imgflip Premium | mandatory (free tier watermarks images) | $9.99 |
| OpenRouter (Claude Haiku) | pay-as-you-go, ~300 calls/day | $2–4 |
| X API | free tier (500 tweets/month) | $0 |
| Cryptopanic | free tier (200 req/day) | $0 |
| CoinGecko | free tier | $0 |
| Telegram Bot API | free | $0 |
| VPS (optional, for 24/7 hosting) | DigitalOcean / Hetzner | $5–7 |
| **Total** | | **~$18–22** |

---

## Make targets (cheat sheet)

| Command | What it does |
|---|---|
| `make setup` | venv + install deps + scaffold `.env` |
| `make dry-run` | run pipeline once, print 5 sample memes as JSON, no posting |
| `make test` | run the pytest suite |
| `make run` | start the bot for real (scheduler + Telegram polling) |
| `make clean` | remove venv, `__pycache__`, `*.db`, `logs/*` |
| `make help` | show all targets |

---

## Operator commands (in Telegram, once running)

| Command | What it does |
|---|---|
| `/start` | health check — bot replies "bot is up" |
| `/stats` | today's post count + pending approvals + approval rate |
| `/pause` | stop auto-posting to X (keep generating candidates) |
| `/resume` | resume auto-posting |
| `/queue` | list approved candidates with their scheduled post times |
| `/clear_pending` | reject all pending candidates (panic button) |

---

## Important: warmup mode

By default `.env` has `WARMUP_MODE=true`. This means the bot generates candidates and drops them in Telegram for your approval, but **does NOT auto-post to X**. You manually copy approved memes to X during this period.

**Keep warmup on for the first 2 weeks.** New X accounts get flagged for automation if they post programmatically from day one. After ~14 days of organic-looking activity, flip `WARMUP_MODE=false` in `.env` and restart — the bot then auto-posts.

---

## Next steps

- **First time setting this up?** → [docs/SETUP.md](docs/SETUP.md)
- **Something broke?** → [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
- **Want to add templates or tweak voice?** → edit `config/templates.json` / `config/voice.json`
- **Architecture deep dive** → [docs/plan.md](docs/plan.md)
- **Editing with Claude Code?** → [CLAUDE.md](CLAUDE.md) — conventions live there
