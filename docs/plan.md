# Crypto Meme Bot — Build Plan

## 1. Goal

Build an automated pipeline that fetches crypto news + market sentiment, generates meme candidates using Imgflip templates with chaos-goblin captions, queues them in a private Telegram channel for one-tap approval, and posts approved memes to X (Twitter) on a schedule.

Operator (Depegger) approves/rejects from phone. Bot does the rest.

Target: 8-10 posts/day, free X API tier (write-only, 500 posts/month).

---

## 2. Locked Decisions

| Decision | Choice |
|---|---|
| Posting flow | Telegram review queue (operator approves before post) |
| Niche | General crypto |
| Account angle | New anon shitposter (cold-start from 0) |
| Volume | 8-10 posts/day |
| Meme generation | Imgflip templates only (paid tier, $9.99/mo, no watermark) |
| Persona | Chaos goblin (random emotional tone per post) |
| X API tier | Free (write-only, 500 posts/month) |
| LLM | Claude Haiku for picker + caption generation |
| Database | SQLite |
| Language | Python 3.11+ |

---

## 3. Tech Stack

| Layer | Library / Service | Notes |
|---|---|---|
| Telegram bot | `aiogram` v3 | async, supports inline keyboards cleanly |
| X API | `tweepy` v4 | v2 endpoints, OAuth 1.0a for posting |
| LLM | OpenRouter via `openai` SDK (OpenAI-compatible) | model configurable, default `anthropic/claude-haiku-4.5` |
| News API | Cryptopanic | `https://cryptopanic.com/api/developer/v2/posts/` |
| News fallback | `feedparser` for RSS | Cointelegraph + Coindesk feeds |
| Sentiment | `requests` to `api.alternative.me/fng/` | Fear & Greed Index |
| Trending tickers | CoinGecko free API | `/api/v3/search/trending` |
| Meme generation | Imgflip API | `https://api.imgflip.com/caption_image` |
| Scheduler | `APScheduler` v3 | cron-like jobs |
| Database | `sqlite3` stdlib + `SQLAlchemy` ORM | |
| HTTP | `httpx` | async-friendly |
| Logging | `loguru` | structured logs |
| Config | `pydantic-settings` | env-driven |

---

## 4. High-Level Architecture

```
                  ┌─────────────────┐
                  │  Scheduler      │
                  │  (APScheduler)  │
                  └────────┬────────┘
                           │
            ┌──────────────┼──────────────┐
            │              │              │
            ▼              ▼              ▼
    every 2hr        every 4hr       every 15min
    [fetch news]   [generate batch]  [post from queue]
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
    [news + sentiment] -> [LLM: pick template + caption] -> [Imgflip render]
                                                                  │
                                                                  ▼
                                                       [Telegram bot drops in channel]
                                                                  │
                                                                  ▼
                                          [Operator taps Approve / Regen / Skip / Edit]
                                                                  │
                                                                  ▼
                                                      [Queue with scheduled_for time]
                                                                  │
                                                                  ▼
                                                       [X API posts on schedule]
```

---

## 5. Project Structure

```
crypto-meme-bot/
├── .env                       # secrets (gitignored)
├── .env.example               # template
├── .gitignore
├── requirements.txt
├── README.md
├── plan.md                    # this file
├── pyproject.toml
│
├── config/
│   ├── templates.json         # imgflip template pool
│   ├── voice.json             # chaos goblin voice rules
│   └── settings.py            # pydantic settings
│
├── src/
│   ├── __init__.py
│   ├── main.py                # entrypoint, starts scheduler + tg bot
│   │
│   ├── fetchers/
│   │   ├── __init__.py
│   │   ├── news.py            # cryptopanic + rss fallback
│   │   ├── sentiment.py       # fear/greed index
│   │   └── trending.py        # coingecko trending tickers
│   │
│   ├── generators/
│   │   ├── __init__.py
│   │   ├── picker.py          # LLM picks template + fills text boxes
│   │   ├── caption.py         # LLM writes tweet caption
│   │   └── meme.py            # imgflip API render
│   │
│   ├── publishers/
│   │   ├── __init__.py
│   │   ├── telegram.py        # bot setup, approval handlers
│   │   └── twitter.py         # x api posting
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── db.py              # sqlalchemy engine + session
│   │   ├── models.py          # ORM models
│   │   └── repository.py      # query helpers
│   │
│   ├── scheduler/
│   │   ├── __init__.py
│   │   └── jobs.py            # apscheduler job definitions
│   │
│   └── utils/
│       ├── __init__.py
│       ├── logger.py
│       ├── dedup.py           # template + topic deduplication
│       └── time_windows.py    # prime ct posting hours logic
│
├── data/
│   └── memebot.db             # sqlite, gitignored
│
├── logs/
│   └── bot.log                # gitignored
│
└── tests/
    ├── test_picker.py
    ├── test_caption.py
    ├── test_dedup.py
    └── fixtures/
        └── sample_news.json
```

---

## 6. Environment Variables

`.env.example`:

```bash
# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_ADMIN_USER_ID=          # only this user can approve
TELEGRAM_CHANNEL_ID=              # private channel for approval drops

# News
CRYPTOPANIC_API_KEY=

# LLM (OpenRouter, OpenAI-compatible)
OPENROUTER_API_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=anthropic/claude-haiku-4.5
# Optional: identifies your app on openrouter.ai/rankings
OPENROUTER_APP_NAME=crypto-meme-bot
OPENROUTER_APP_URL=https://github.com/depegger/crypto-meme-bot

# Imgflip
IMGFLIP_USERNAME=
IMGFLIP_PASSWORD=

# X (Twitter)
X_API_KEY=
X_API_SECRET=
X_ACCESS_TOKEN=
X_ACCESS_TOKEN_SECRET=
X_BEARER_TOKEN=

# Runtime
DATABASE_PATH=./data/memebot.db
LOG_LEVEL=INFO
TIMEZONE=UTC

# Tunables
POSTS_PER_DAY=9                   # target volume
CANDIDATES_PER_BATCH=5            # generate 5, approve ~2 = 9/day
DEDUP_HOURS=48                    # same template + topic block window
WARMUP_MODE=true                  # set false after 2-week manual warmup
```

---

## 7. Database Schema

```sql
-- News items deduplication
CREATE TABLE news_seen (
    id TEXT PRIMARY KEY,           -- hash of url
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT,
    fetched_at TIMESTAMP NOT NULL
);

-- Generated meme candidates
CREATE TABLE candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id TEXT,                  -- FK to news_seen.id
    news_title TEXT,
    news_url TEXT,
    template_id TEXT NOT NULL,     -- imgflip template id
    template_name TEXT,
    text_boxes TEXT NOT NULL,      -- JSON array of strings
    caption TEXT NOT NULL,
    image_url TEXT,                -- imgflip rendered url
    sentiment_score REAL,          -- fear/greed value 0-100
    sentiment_label TEXT,          -- extreme_fear, fear, neutral, greed, extreme_greed
    generated_at TIMESTAMP NOT NULL,
    tg_message_id INTEGER,         -- telegram message id for editing
    status TEXT NOT NULL,          -- pending, approved, rejected, posted, failed
    scheduled_for TIMESTAMP,
    posted_at TIMESTAMP,
    tweet_id TEXT
);

-- Dedup tracking for templates
CREATE TABLE template_usage (
    template_id TEXT,
    topic_hash TEXT,               -- hash of normalized news topic
    used_at TIMESTAMP,
    PRIMARY KEY (template_id, topic_hash, used_at)
);

CREATE INDEX idx_candidates_status ON candidates(status);
CREATE INDEX idx_candidates_scheduled ON candidates(scheduled_for);
CREATE INDEX idx_template_usage_time ON template_usage(used_at);
```

---

## 8. Module Specs

### 8.1 `fetchers/news.py`

**Responsibility**: pull crypto news from Cryptopanic + RSS fallbacks, dedupe against `news_seen`.

**Interface**:
```python
async def fetch_news(limit: int = 20) -> list[NewsItem]: ...
```

**Logic**:
1. Call Cryptopanic `GET /api/developer/v2/posts/?auth_token=X&kind=news&filter=hot`.
2. If rate-limited or fails, fall back to RSS: Cointelegraph + Coindesk.
3. Hash each item URL with SHA-256, check against `news_seen`. Skip if seen.
4. Return list of new `NewsItem(id, title, url, source, published_at)`.
5. Insert new items into `news_seen`.

**Rate limit**: Cryptopanic free = 200 req/day. We call every 2hr = 12/day. Safe.

---

### 8.2 `fetchers/sentiment.py`

**Responsibility**: fetch current Fear & Greed Index.

**Interface**:
```python
async def fetch_sentiment() -> SentimentReading: ...
```

**Endpoint**: `GET https://api.alternative.me/fng/?limit=1`

**Returns**:
```python
SentimentReading(score=42, label="fear", timestamp=...)
```

Cache for 1hr (updates daily anyway).

---

### 8.3 `fetchers/trending.py`

**Responsibility**: pull current trending tickers from CoinGecko.

**Endpoint**: `GET https://api.coingecko.com/api/v3/search/trending`

**Returns**: list of top 7 trending symbols (e.g. `["btc", "sol", "pepe", "bonk", ...]`).

Used by caption generator to enrich with relevant cashtags when news doesn't mention specific tokens.

---

### 8.4 `generators/picker.py`

**Responsibility**: given a news item + sentiment, ask LLM to pick best template from pool and fill text boxes.

**Interface**:
```python
async def pick_template(news: NewsItem, sentiment: SentimentReading) -> TemplateChoice: ...
```

**LLM system prompt** (load templates from `config/templates.json`):

```
You are a meme template selector for crypto Twitter.

Given a news headline and current market sentiment, you must:
1. Pick the BEST template from the pool below.
2. Generate text for each box, matching the template's structure exactly.

Template pool:
{TEMPLATE_LIST_JSON}

Rules:
- Each text box: max 60 characters.
- All lowercase.
- No emojis, no hashtags.
- Be specific to the news (mention the token/event when relevant).
- Pick template whose structure matches the news angle:
  - Comparison/rotation news -> drake or distracted_boyfriend
  - Dilemma news -> two_buttons
  - Hot take needed -> change_my_mind or expanding_brain
  - Disaster/hack/rug -> this_is_fine or disaster_girl
  - Sentiment swing -> wojak variants

Output JSON only, no markdown fences:
{
  "template_id": "...",
  "template_name": "...",
  "boxes": ["text for box 0", "text for box 1", ...],
  "reasoning": "one sentence why this template"
}
```

**User message**:
```
News: {headline}
URL: {url}
Source: {source}
Current sentiment: {label} ({score}/100)
```

**OpenRouter client setup** (shared by `picker.py` and `caption.py`, put in `utils/llm.py`):

```python
from openai import AsyncOpenAI
from config.settings import settings

llm_client = AsyncOpenAI(
    api_key=settings.OPENROUTER_API_KEY,
    base_url=settings.OPENROUTER_BASE_URL,  # https://openrouter.ai/api/v1
    default_headers={
        "HTTP-Referer": settings.OPENROUTER_APP_URL,
        "X-Title": settings.OPENROUTER_APP_NAME,
    },
)

async def call_llm(system: str, user: str, max_tokens: int = 500, temperature: float = 0.8) -> str:
    response = await llm_client.chat.completions.create(
        model=settings.LLM_MODEL,  # e.g. anthropic/claude-haiku-4.5
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content
```

Use `call_llm()` from picker and caption. Max tokens 500 for picker (needs JSON), 100 for caption. Parse JSON strictly in picker. Retry once on parse failure with stricter prompt.

**Model swap is one env var change.** Cheap alternatives to consider via OpenRouter:
- `openai/gpt-4o-mini` (very cheap, fast)
- `meta-llama/llama-3.3-70b-instruct` (cheap, open-source)
- `google/gemini-flash-1.5` (cheap, fast)
- `anthropic/claude-haiku-4.5` (default, best voice match for chaos goblin)

---

### 8.5 `generators/caption.py`

**Responsibility**: given the meme + news + sentiment, write the tweet caption in chaos-goblin voice.

**Interface**:
```python
async def write_caption(news: NewsItem, template: TemplateChoice, sentiment: SentimentReading, trending: list[str]) -> str: ...
```

**LLM system prompt**:

```
You are a chaos goblin crypto Twitter shitposter. You write meme captions.

Voice rules (NEVER break):
- All lowercase.
- 4 to 15 words total.
- No hashtags.
- No emojis.
- Never explain the joke.
- Maximum 1 cashtag (like $btc or $sol). Often zero.
- Match the meme's vibe but DO NOT describe the meme.

Tone roulette: pick ONE per caption, randomly:
- Bull: euphoric, "im in", "buying", "wagmi", "few"
- Bear: doomer, "down bad", "cooked", "ngmi", "cope"
- Cope: defeated bull rationalizing, "still bullish actually"
- Euphoria: peak greed, "this changes everything", "we're so back"
- Doom: pure nihilism, "nothing matters", "good night sweet prince"

Approved lexicon (use sparingly, not every post):
gm, gn, ser, anon, wagmi, ngmi, few, ratio, cope, down bad, im in, buying, wen, jpow, normie, ape, rotate, rugged, based, mid, cooked, we're so back, it's so over

Contradictions across posts are FEATURE not bug. You are a chaos goblin.

Output the caption text ONLY. No quotes, no preamble, no explanation.
```

**User message**:
```
News: {headline}
Meme template: {template_name}
Meme text boxes: {boxes}
Sentiment: {label} ({score}/100)
Trending tickers today: {trending}
Tone for this post: {randomly_picked_tone}
```

Tone is pre-picked in Python via weighted random per `voice.json`:
- bull 25%, bear 25%, cope 20%, euphoria 15%, doom 15%

---

### 8.6 `generators/meme.py`

**Responsibility**: call Imgflip API to render the final image.

**Endpoint**: `POST https://api.imgflip.com/caption_image`

**Form data**:
```
template_id={template_id}
username={IMGFLIP_USERNAME}
password={IMGFLIP_PASSWORD}
boxes[0][text]={boxes[0]}
boxes[1][text]={boxes[1]}
...
```

**Response**:
```json
{
  "success": true,
  "data": {
    "url": "https://i.imgflip.com/xxxx.jpg",
    "page_url": "..."
  }
}
```

Store the `url`. Validate via HEAD request that image loads before queuing.

**Error handling**: on `success: false`, log error and skip this candidate (do not retry same template).

---

### 8.7 `publishers/telegram.py`

**Responsibility**: post candidates to private channel with approval buttons. Handle callbacks.

**Setup**:
- aiogram bot, polling mode.
- Restrict all handlers to `TELEGRAM_ADMIN_USER_ID` (hard check, reject others).

**Candidate drop format**:

Send photo via `bot.send_photo(chat_id=TELEGRAM_CHANNEL_ID, photo=image_url, caption=preview_text, reply_markup=keyboard)`.

`preview_text`:
```
[news snippet, 100 chars]

caption:
{caption}

template: {template_name} | sentiment: {label} ({score})
```

**Inline keyboard**:
```
[ ✓ Approve ]  [ 🔄 Regen ]
[ ⏭ Skip   ]  [ ✏ Edit  ]
```

(NOTE for operator: emojis used in TG UI buttons only because Telegram inline keyboards render them as glyphs. These do NOT appear in the actual posted tweet.)

**Callback actions**:
- `approve:{candidate_id}` -> set status `approved`, compute `scheduled_for`, edit message text to "✅ approved, scheduled for {time}".
- `regen:{candidate_id}` -> set status `rejected`, trigger regen of new candidate from same news item (different template).
- `skip:{candidate_id}` -> set status `rejected`, do nothing else.
- `edit:{candidate_id}` -> bot replies "send new caption". Wait for next text message from admin. Replace caption. Re-show with same buttons.

**Edit flow state**: store pending edit in dict `{user_id: candidate_id}`, clear after edit received or 5min timeout.

---

### 8.8 `publishers/twitter.py`

**Responsibility**: post approved candidates to X on schedule.

**Setup**: tweepy `Client` with OAuth 1.0a user context (required for posting).

**Interface**:
```python
async def post_to_x(candidate: Candidate) -> str:  # returns tweet_id
    # 1. Download image from candidate.image_url to temp file
    # 2. Upload via v1.1 media endpoint (tweepy.API)
    # 3. Create tweet via v2 with media_id + caption text
    # 4. Return tweet id
```

**Critical**:
- Media upload uses v1.1 (`API.media_upload`).
- Tweet creation uses v2 (`Client.create_tweet`).
- Caption: candidate.caption only. NO link to image. The meme IS the tweet.
- On rate limit, push back into queue with new `scheduled_for` +30min.

**Free tier limits to respect**:
- 500 tweets/month.
- Effectively ~16/day max but we target 8-10.
- Posts spaced minimum 15 minutes apart.

---

### 8.9 `scheduler/jobs.py`

Define APScheduler jobs:

```python
# Job 1: news fetch, every 2 hours
@scheduler.scheduled_job('interval', hours=2)
async def job_fetch_news():
    items = await fetch_news()
    # store in news_seen, push to candidate generation queue

# Job 2: generate candidates, every 4 hours
@scheduler.scheduled_job('interval', hours=4)
async def job_generate_batch():
    unprocessed_news = get_recent_news(limit=settings.CANDIDATES_PER_BATCH)
    sentiment = await fetch_sentiment()
    trending = await fetch_trending()
    for news in unprocessed_news:
        if is_duplicate_topic(news):
            continue
        template = await pick_template(news, sentiment)
        if recently_used(template.id, news.topic_hash):
            continue
        image_url = await render_meme(template)
        caption = await write_caption(news, template, sentiment, trending)
        candidate = save_candidate(...)
        await drop_to_telegram(candidate)

# Job 3: post from queue, every 15 minutes
@scheduler.scheduled_job('interval', minutes=15)
async def job_post_queue():
    if WARMUP_MODE: return  # skip auto-post during warmup
    due = get_approved_candidates_due_now()
    for candidate in due:
        try:
            tweet_id = await post_to_x(candidate)
            mark_posted(candidate.id, tweet_id)
        except RateLimitError:
            reschedule(candidate.id, delay_minutes=30)
        except Exception as e:
            log.error(f"post failed: {e}")
            mark_failed(candidate.id)
```

---

### 8.10 `utils/dedup.py`

**Functions**:

```python
def hash_topic(news_title: str) -> str:
    """Lowercase, strip stopwords, hash first 5 content words."""

def recently_used(template_id: str, topic_hash: str, hours: int = 48) -> bool:
    """Return True if same template+topic used in last N hours."""

def record_usage(template_id: str, topic_hash: str): ...
```

---

### 8.11 `utils/time_windows.py`

**Function**:

```python
def compute_post_schedule(approval_time: datetime, posts_today: int) -> datetime:
    """
    Prime CT hours: 10:00 UTC to 02:00 UTC next day (16hr window).
    Spread N posts evenly across window with random jitter ±10min.
    If approval comes during dead hours (02:00-10:00 UTC), schedule for 10:00 UTC.
    Minimum 15min gap between posts.
    """
```

---

## 9. Imgflip Template Pool

Save as `config/templates.json`. Start with these. Add more after observing what lands.

```json
[
  {
    "id": "181913649",
    "name": "drake",
    "boxes": 2,
    "structure": "no_this | yes_this",
    "best_for": ["comparison", "rotation", "preference"]
  },
  {
    "id": "87743020",
    "name": "two_buttons",
    "boxes": 2,
    "structure": "button_left | button_right",
    "best_for": ["dilemma", "trader_choice"]
  },
  {
    "id": "112126789",
    "name": "distracted_boyfriend",
    "boxes": 3,
    "structure": "girlfriend (old thing) | boyfriend label | other girl (new thing)",
    "best_for": ["rotation", "abandoning_one_token_for_another"]
  },
  {
    "id": "93895088",
    "name": "expanding_brain",
    "boxes": 4,
    "structure": "tier1 | tier2 | tier3 | tier4 (galaxy)",
    "best_for": ["escalating_takes", "galaxy_brain"]
  },
  {
    "id": "129242436",
    "name": "change_my_mind",
    "boxes": 1,
    "structure": "sign_text",
    "best_for": ["hot_take", "opinion"]
  },
  {
    "id": "55311130",
    "name": "this_is_fine",
    "boxes": 2,
    "structure": "top_text | bottom_text",
    "best_for": ["disaster", "hack", "rug", "crash"]
  },
  {
    "id": "97984",
    "name": "disaster_girl",
    "boxes": 2,
    "structure": "top | bottom",
    "best_for": ["chaos_event", "exchange_collapse"]
  },
  {
    "id": "61579",
    "name": "one_does_not_simply",
    "boxes": 2,
    "structure": "top | bottom",
    "best_for": ["sage_advice", "warnings"]
  },
  {
    "id": "61539",
    "name": "first_world_problems",
    "boxes": 2,
    "structure": "top | bottom",
    "best_for": ["minor_inconvenience", "gas_fees"]
  },
  {
    "id": "131087935",
    "name": "running_away_balloon",
    "boxes": 5,
    "structure": "balloon1 | person1 | balloon2 | person2 | person3",
    "best_for": ["chase", "fomo"]
  },
  {
    "id": "61580",
    "name": "too_damn_high",
    "boxes": 2,
    "structure": "top | bottom",
    "best_for": ["gas_fees", "prices", "leverage"]
  },
  {
    "id": "91545132",
    "name": "trojan_horse",
    "boxes": 2,
    "structure": "top | bottom",
    "best_for": ["hidden_threat", "scam_warning"]
  }
]
```

Operator can add Wojak / Pepe / Chad community templates later by searching imgflip and grabbing IDs.

---

## 10. Chaos Goblin Voice Config

Save as `config/voice.json`:

```json
{
  "tone_weights": {
    "bull": 0.25,
    "bear": 0.25,
    "cope": 0.20,
    "euphoria": 0.15,
    "doom": 0.15
  },
  "lexicon_core": [
    "gm", "gn", "ser", "anon", "wagmi", "ngmi", "few",
    "ratio", "cope", "down bad", "im in", "buying", "wen",
    "jpow", "normie", "ape", "rotate", "rugged", "based",
    "mid", "cooked", "we're so back", "it's so over"
  ],
  "rules": {
    "case": "lowercase",
    "max_words": 15,
    "min_words": 4,
    "hashtags": false,
    "emojis": false,
    "max_cashtags": 1,
    "explain_joke": false
  },
  "calibration_examples": {
    "btc_dump": "down bad ser. buying anyway",
    "gas_spike": "gas higher than my hopes for q4",
    "memecoin_pump": "few will understand",
    "exchange_hack": "not ur keys not ur problem. sponsored by hackers",
    "etf_inflow": "suits finally got the memo",
    "rugpull": "another one bites the rug",
    "fed_news": "jpow watching us bleed live on cnbc",
    "alt_season_cope": "wen alt season ser. wen.",
    "all_time_high": "we're so back",
    "all_time_low": "it's so over"
  }
}
```

---

## 11. Telegram Approval Flow UX

**Channel setup (manual, one-time)**:
1. Create private Telegram channel.
2. Add the bot as admin with post permission.
3. Note the channel ID (forward a message to `@username_to_id_bot` to get it).
4. Set in `.env` as `TELEGRAM_CHANNEL_ID`.

**Drop format example** (what operator sees):

```
[photo: rendered meme]

📰 Solana ETF sees record $200M inflows in first week

💬 caption:
suits finally got the memo

🎭 template: drake | 😨 sentiment: greed (72)

[ ✓ Approve ]  [ 🔄 Regen ]
[ ⏭ Skip   ]  [ ✏ Edit  ]
```

**Approval -> shows updated message**:
```
✅ approved, scheduled for 14:35 UTC (in 22min)
```

**Edit flow**:
- Tap Edit
- Bot replies "send new caption text (5min timeout)"
- Operator sends text
- Bot updates caption, re-renders preview, shows buttons again

**Regen flow**:
- Tap Regen
- Bot triggers picker with same news but excludes used template
- Bot generates new caption
- Drops new candidate (the old one stays as rejected in DB for analytics)

---

## 12. Posting Schedule Logic

**Prime hours**: 10:00 UTC -> 02:00 UTC next day (16-hour window). Skip 02:00-10:00 UTC (dead hours: most of CT is asleep, US closed, EU asleep).

**Distribution**: 9 posts (target) across 16hr = post every ~107min. Apply ±15min random jitter so it doesn't look bot-pattern.

**Algorithm**:
```python
def next_slot(posts_already_today: int, base_hour: int = 10) -> datetime:
    target_count = settings.POSTS_PER_DAY
    window_minutes = 16 * 60
    base_interval = window_minutes // target_count
    slot_offset = posts_already_today * base_interval
    jitter = random.randint(-15, 15)
    return today_at(base_hour) + timedelta(minutes=slot_offset + jitter)
```

**Edge cases**:
- If operator approves during dead hours, queue for next 10:00 UTC.
- If queue already has post within 15min of computed slot, push out by 15min.
- If approved but `posts_already_today >= POSTS_PER_DAY`, queue for tomorrow.

---

## 13. Dedup Logic

**Goal**: no two memes within 48hr using same template + same news topic.

**Topic hash**:
```python
import re
STOPWORDS = {"the", "a", "an", "is", "to", "of", "in", "and", "as", "for", "on", "at", "by", "with"}

def topic_hash(title: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", "", title.lower()).split()
    content = [w for w in words if w not in STOPWORDS][:5]
    return hashlib.sha1(" ".join(content).encode()).hexdigest()[:16]
```

**Check**:
```python
def is_duplicate(template_id: str, topic_hash: str, window_hours: int = 48) -> bool:
    cutoff = datetime.utcnow() - timedelta(hours=window_hours)
    return db.query(TemplateUsage).filter(
        TemplateUsage.template_id == template_id,
        TemplateUsage.topic_hash == topic_hash,
        TemplateUsage.used_at >= cutoff,
    ).first() is not None
```

Record usage when a candidate is approved (not when generated, since regens shouldn't burn the slot).

---

## 14. Build Phases

### Phase 0: Skeleton + manual mode (Day 1-2)
- Set up project structure, `.env`, dependencies.
- Implement `fetchers/news.py` and `fetchers/sentiment.py`. Print to console.
- Implement `generators/picker.py` and `generators/caption.py`. Test against sample news.
- Implement `generators/meme.py`. Verify Imgflip rendering works.
- No Telegram, no X yet. CLI script that generates 5 sample memes and saves URLs to file.

**Exit criteria**: run `python -m src.main --dry-run` and get 5 valid meme URLs with captions in chaos-goblin voice.

### Phase 1: Telegram approval flow (Day 3-4)
- Implement `publishers/telegram.py` with full button flow (approve/regen/skip/edit).
- Implement `storage/` (SQLite + ORM).
- Wire scheduler job_generate_batch to drop into TG.
- Approvals just mark DB. No X posting yet. Manually copy approved memes to X for first 2 weeks (warmup).

**Exit criteria**: bot generates 4-5 candidates every 4hr, operator approves on phone, DB tracks status correctly.

### Phase 2: Auto-post to X (Day 5-6, after warmup)
- Implement `publishers/twitter.py` with media upload + tweet.
- Wire job_post_queue with scheduling logic.
- Set `WARMUP_MODE=false`.
- Monitor first week closely for shadowban signals.

**Exit criteria**: approved candidates auto-post to X within scheduled window, dedup works, no API errors.

### Phase 3: Polish (Week 2+)
- Add `/stats` command in TG: posts today, approval rate, dead templates.
- Add `/pause` and `/resume` commands.
- Add error notifications to admin DM on failures.
- Expand template pool based on what lands.

### Future (out of scope for v1)
- Reply guy bot: monitor anchor accts, draft replies, approve in TG.
- Multi-account support.
- Engagement analytics feedback loop.
- AI-generated images via Flux Schnell for unique meme variants.

---

## 15. Operator Playbook (Cold-Start Anon Account)

This is execution context for the human operator. Not for the bot to handle.

### Week 0-2: Warmup (Manual mode)
- Create new X account. Cursed pfp (broken pepe, glitched wojak). Handle: dumb word + numbers, e.g. `gobliny_404`, `cope_dealer`, `ratio_machine`.
- Bio: 3-5 words max, cryptic, lowercase.
- Set `WARMUP_MODE=true` in `.env`.
- Bot generates and operator approves in Telegram, but operator manually copies image + caption to X (no auto-post yet).
- Post 2-3/day max during warmup.
- Manually follow 50 CT accounts (mix of big: vitalik, cz, ansem, hsaka, cobie, murad. Mid: meme accts. Small: niche projects).
- Reply manually to 5-10 tweets/day. Engagement > posts at this stage.

### Week 2+: Auto-post
- Set `WARMUP_MODE=false`. Bot auto-posts approved candidates.
- Keep manually replying to anchor accts daily (no bot replies in v1).
- Quote-tweet breaking news within 15min using bot's "manual trigger" path (TODO: add `/generate <url>` command).

### What to watch for
- Sudden engagement drop = possible shadowban. Pause auto-post for 48hr.
- Same template winning 5+ times = expand pool or re-weight picker.
- Caption getting flat = manually edit chaos-goblin lexicon, add fresh CT phrases weekly.

---

## 16. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| New X account flagged for automation | 2-week manual warmup before turning on auto-post |
| Imgflip free tier watermarks images | Use $9.99/mo paid plan. Mandatory. |
| X free tier hidden rate limits | Min 15min gap between posts. Catch rate-limit errors and reschedule. |
| LLM produces off-voice captions | Calibration examples in prompt. Manual edit button in TG. |
| Duplicate news across sources | URL-hash dedup in `news_seen`. Topic hash for similar-topic dedup. |
| Template + topic over-used | 48hr dedup window in `template_usage` table. |
| Imgflip API down | Skip batch, retry next cycle. Don't post broken images. |
| LLM API down | Skip batch. Log alert. OpenRouter auto-routes around model outages but swap `LLM_MODEL` env var to fallback if a whole provider is down. |
| Telegram bot unauthorized message | Hard-check `user_id == TELEGRAM_ADMIN_USER_ID` on every handler. |
| Operator forgets to approve = backlog | TG drops show count of pending. Auto-expire candidates after 24hr. |

---

## 17. Testing Approach

**Unit tests** (`pytest`):
- `test_picker.py`: mock LLM, assert correct template selection for known inputs.
- `test_caption.py`: mock LLM, assert caption meets voice rules (lowercase, no emoji, word count).
- `test_dedup.py`: insert usage, assert `is_duplicate` returns True within window, False after.
- `test_time_windows.py`: assert scheduler skips dead hours correctly.

**Integration tests** (manual checklist):
- Run dry-run script, verify Imgflip rendering with real API.
- Approve a test candidate in TG, verify DB status changes.
- Trigger post job manually, verify tweet appears.

**Fixtures**: `tests/fixtures/sample_news.json` with 20 hand-curated headlines covering each template's `best_for` categories.

---

## 18. Deployment

**Recommended**: single VPS (DigitalOcean / Hetzner / Contabo $5/mo droplet) running:
- `tmux` or `systemd` unit for the bot.
- `cron` backup of `data/memebot.db` to remote storage daily.
- `logrotate` on `logs/bot.log`.

**Systemd unit** (`/etc/systemd/system/memebot.service`):
```ini
[Unit]
Description=Crypto Meme Bot
After=network.target

[Service]
Type=simple
User=memebot
WorkingDirectory=/home/memebot/crypto-meme-bot
EnvironmentFile=/home/memebot/crypto-meme-bot/.env
ExecStart=/home/memebot/crypto-meme-bot/.venv/bin/python -m src.main
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Logs**: `loguru` writes to `logs/bot.log` with rotation at 10MB, retention 14 days.

**Backups**: `sqlite3 data/memebot.db ".backup data/backup_$(date +%Y%m%d).db"` daily via cron.

---

## 19. Cost Breakdown

| Item | Cost |
|---|---|
| Imgflip Premium | $9.99/mo |
| OpenRouter API (Haiku tier, ~300 LLM calls/day) | ~$2-4/mo |
| X API free tier | $0 |
| Cryptopanic free tier | $0 |
| CoinGecko free tier | $0 |
| Telegram Bot API | $0 |
| VPS | $5-7/mo |
| **Total** | **~$18-22/mo** |

---

## 20. Acceptance Criteria for v1

Ship considered done when all of these are true for 7 consecutive days:

- Bot generates 4-5 candidates every 4hr without manual intervention.
- Operator can approve, regen, skip, edit any candidate from Telegram with one tap.
- Approved candidates auto-post to X within scheduled window.
- No duplicate memes (same template + same news topic) within 48hr.
- No failed posts due to rate limits.
- 8-10 posts/day actually appear on X.
- Captions consistently match chaos-goblin voice (subjective check: operator approves >40% of generated captions without edit).

---

## 21. Commands Reference (Operator)

In Telegram chat with the bot:

| Command | Action |
|---|---|
| `/start` | Health check, returns "bot is up" |
| `/stats` | Today's post count, pending approvals, approval rate |
| `/pause` | Stop auto-posting (keep generating) |
| `/resume` | Resume auto-posting |
| `/generate <url>` | Manually trigger generation for a specific news URL |
| `/queue` | List approved candidates with scheduled times |
| `/clear_pending` | Reject all pending candidates (panic button) |

---

## 22. File-by-File Build Order

For Claude Code, build in this order:

1. `pyproject.toml` + `requirements.txt` + `.env.example` + `.gitignore`
2. `config/settings.py` (pydantic-settings)
3. `config/templates.json` + `config/voice.json`
4. `src/utils/logger.py`
5. `src/storage/models.py` + `src/storage/db.py`
6. `src/storage/repository.py`
7. `src/fetchers/sentiment.py` (simplest, no auth)
8. `src/fetchers/trending.py`
9. `src/fetchers/news.py`
10. `src/utils/dedup.py`
11. `src/utils/time_windows.py`
12. `src/generators/picker.py`
13. `src/generators/caption.py`
14. `src/generators/meme.py`
15. `src/publishers/telegram.py`
16. `src/publishers/twitter.py`
17. `src/scheduler/jobs.py`
18. `src/main.py`
19. `tests/*`

After each module, write a quick smoke test before moving on.

---

## End of Plan
