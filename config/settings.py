from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        env_ignore_empty=True,
        extra="ignore",
    )

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_ADMIN_USER_ID: int = 0
    TELEGRAM_CHANNEL_ID: int = 0

    # News
    CRYPTOPANIC_API_KEY: str = ""

    # LLM (OpenRouter, OpenAI-compatible)
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    LLM_MODEL: str = "anthropic/claude-haiku-4.5"
    OPENROUTER_APP_NAME: str = "crypto-meme-bot"
    OPENROUTER_APP_URL: str = "https://github.com/depegger/crypto-meme-bot"

    # Imgflip
    IMGFLIP_USERNAME: str = ""
    IMGFLIP_PASSWORD: str = ""

    # X (Twitter)
    X_API_KEY: str = ""
    X_API_SECRET: str = ""
    X_ACCESS_TOKEN: str = ""
    X_ACCESS_TOKEN_SECRET: str = ""
    X_BEARER_TOKEN: str = ""

    # Runtime
    DATABASE_PATH: str = "./data/memebot.db"
    LOG_LEVEL: str = "INFO"
    TIMEZONE: str = "UTC"

    # Tunables
    POSTS_PER_DAY: int = 9
    CANDIDATES_PER_BATCH: int = 5
    DEDUP_HOURS: int = 48
    WARMUP_MODE: bool = True


settings = Settings()
