# Setup — First-time walkthrough

This walks you through everything from zero. If you've already done a step, skip it.

---

## 0. Prerequisites

### Python 3.11 or newer

Check what you have:
```bash
python3 --version
```

If it says **3.9 or older**, install 3.11:
- **macOS**: `brew install python@3.11`
- **Ubuntu/Debian**: `sudo apt install python3.11 python3.11-venv`
- **Other**: download from [python.org/downloads](https://www.python.org/downloads/)

### git + sqlite3

```bash
git --version
sqlite3 --version
```

Both ship with macOS. On Linux: `apt install git sqlite3`.

### Pick a project location

**On macOS, do NOT put the project under `~/Desktop/`, `~/Documents/`, or `~/Downloads/`.** macOS sandboxes terminal apps from those folders by default and you'll hit "Operation not permitted" errors when running Python. Use `~/Code/`, `~/dev/`, or `~/projects/`.

```bash
mkdir -p ~/Code
cd ~/Code
```

---

## 1. Get the code

```bash
git clone <your-repo-url> crypto-meme-bot
cd crypto-meme-bot
```

(If you don't have a git remote, just unzip wherever you have the files.)

---

## 2. Bootstrap

Run the setup script:
```bash
./scripts/setup.sh
```

It will:
1. Find a Python 3.11+ interpreter
2. Create a `.venv/` virtualenv (isolated Python install just for this project)
3. Install all dependencies from `requirements.txt`
4. Copy `.env.example` to `.env` if it doesn't exist

If the script is missing the execute bit:
```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

Manual equivalent (if you'd rather):
```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

---

## 3. Get your API keys

You need keys from 5 services. Total time: ~10 minutes.

### 3a. Telegram (3 values, all free)

1. **`TELEGRAM_BOT_TOKEN`**
   - Open Telegram, search for `@BotFather`.
   - Send `/newbot`. Pick a display name + username for your bot.
   - BotFather replies with a token like `123456789:ABCdefGHIjklMNOpqr...`. Copy the whole thing.

2. **`TELEGRAM_ADMIN_USER_ID`**
   - In Telegram, search for `@userinfobot`. Send any message.
   - It replies with your numeric user ID (e.g. `987654321`). Copy it.

3. **`TELEGRAM_CHANNEL_ID`**
   - Create a new **private channel** in Telegram (Menu → New Channel → make it Private).
   - Open the channel's settings → Administrators → Add Admin → search for your bot → enable **Post Messages** permission → save.
   - Post any text in the channel. Forward that message to `@username_to_id_bot`. It replies with the channel ID — a negative number like `-1001234567890`. Copy it (including the minus sign).

### 3b. Cryptopanic (free, 200 req/day)

4. **`CRYPTOPANIC_API_KEY`**
   - Sign up at [cryptopanic.com/developers/api](https://cryptopanic.com/developers/api).
   - Generate a developer token from your account page. Copy it.

### 3c. OpenRouter (pay-as-you-go, ~$2-4/mo)

5. **`OPENROUTER_API_KEY`**
   - Sign up at [openrouter.ai](https://openrouter.ai).
   - Add ~$5 starter credit (top right → Credits).
   - Generate an API key from the dashboard. Copy it.
   - Default model is `anthropic/claude-haiku-4.5` — cheap and fast. You can swap any OpenRouter model in `.env` later.

### 3d. Imgflip Premium (mandatory, $9.99/mo)

6. **`IMGFLIP_USERNAME`** and **`IMGFLIP_PASSWORD`**
   - Sign up at [imgflip.com](https://imgflip.com).
   - Upgrade to **Premium** ($9.99/mo) — this is required. The free tier puts a watermark on every meme.
   - Put your imgflip username + password in `.env`.

### 3e. X (Twitter, free for 500 tweets/mo)

7. **`X_API_KEY`** / **`X_API_SECRET`** / **`X_ACCESS_TOKEN`** / **`X_ACCESS_TOKEN_SECRET`** / **`X_BEARER_TOKEN`**
   - Go to [developer.x.com](https://developer.x.com).
   - Apply for a developer account (Free tier is fine).
   - Create a new **Project** → **App**.
   - In app settings → **User authentication settings** → enable **OAuth 1.0a** + **Read and Write** permissions. (This step matters — without write perms, posting will fail with a cryptic 403.)
   - From **Keys and Tokens** tab, generate:
     - API Key + Secret
     - Access Token + Secret
     - Bearer Token
   - Copy all 5 into `.env`.

---

## 4. Fill `.env`

Open `.env` in your editor and paste the keys you just collected:

```bash
# macOS
open -e .env

# Linux
nano .env
# or
vim .env
```

For lines that already have a default (`OPENROUTER_BASE_URL`, `LLM_MODEL`, `WARMUP_MODE`, `POSTS_PER_DAY`, etc.) — leave them as-is for now.

**Critical setting**: keep `WARMUP_MODE=true` for the first 2 weeks. See [§7](#7-warmup-mode) below.

---

## 5. Verify everything works

### Smoke test (no Telegram, no X)
```bash
make dry-run
```

This runs the pipeline once and prints up to 5 candidate memes as JSON. If you see `template_id`, `caption`, and `image_url` for each, the LLM + Imgflip flow is healthy.

If it prints zero blobs, that's OK too — it means there's no fresh news. The point of dry-run is "no crash". Any traceback → check [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

### Run the test suite
```bash
make test
```

Should be 18 green tests. If any fail → [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

---

## 6. Start the bot

```bash
make run
```

Within ~4 hours (the default generate interval), candidates will start dropping in your private Telegram channel with `[✓ Approve] [🔄 Regen] [⏭ Skip] [✏ Edit]` buttons. Tap to manage them from your phone.

To stop the bot, press `Ctrl+C` in the terminal.

---

## 7. Warmup mode

Brand-new X accounts that post programmatically from day one get flagged for automation. To avoid that:

- For the **first 2 weeks**, keep `WARMUP_MODE=true` in `.env`. The bot generates candidates and drops them in Telegram, but does NOT auto-post to X. You **manually copy** approved memes to X (long-press image in Telegram → Save → upload to X with the caption).
- Post 2–3 memes/day max during warmup.
- Manually reply to 5–10 crypto-Twitter accounts daily to look organic.

After ~14 days:
1. Open `.env`, change `WARMUP_MODE=true` → `WARMUP_MODE=false`.
2. Restart with `make run`. The bot will now auto-post approved candidates on schedule.

---

## 8. Run it 24/7 (optional)

To keep the bot running when your laptop is off, host it on a cheap VPS:

1. Get a $5/mo VPS (DigitalOcean droplet, Hetzner CX11, Contabo VPS-S).
2. SSH in, install Python 3.11+, git, sqlite3.
3. Clone the repo, run `./scripts/setup.sh`.
4. Set up persistent execution — easiest options:
   - **Quick (tmux)**: `tmux new -s bot`, then `make run`. Detach with `Ctrl+B D`. Reattach: `tmux a -t bot`.
   - **Proper (systemd)**: copy the unit file in `docs/plan.md` §18 to `/etc/systemd/system/memebot.service`, then `systemctl enable --now memebot`.

That's it. Welcome to the chaos goblin life.

---

## What if I want to customize?

- **Add more meme templates** → edit `config/templates.json`. Find template IDs at imgflip.com/memetemplates.
- **Tweak the voice** → edit `config/voice.json` (tone weights, lexicon, calibration examples).
- **Change posting volume** → edit `.env`: `POSTS_PER_DAY=15`, `CANDIDATES_PER_BATCH=8`, etc.
- **Swap LLM** → edit `.env`: `LLM_MODEL=openai/gpt-4o-mini` (or any OpenRouter model).
- **Deeper architecture changes** → read `docs/plan.md` (the original build spec), then look at `.claude/rules/` for per-module conventions.
