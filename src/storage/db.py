"""SQLAlchemy engine + session factory + init_db.

The single entry point for sessions is `SessionLocal`. Repository helpers
own all `with SessionLocal() as session:` usage — no module elsewhere
should instantiate a Session directly (per .claude/rules/storage.md).
"""

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import settings
from src.storage.models import Base


# Ensure the data/ directory exists at import time. settings.DATABASE_PATH
# is a relative path like "./data/memebot.db" by default.
_db_path = Path(settings.DATABASE_PATH)
_db_path.parent.mkdir(parents=True, exist_ok=True)


# SQLite needs check_same_thread=False if sessions are touched from threads
# spun up by APScheduler. SQLAlchemy still owns connection pooling.
engine = create_engine(
    f"sqlite:///{_db_path}",
    connect_args={"check_same_thread": False},
    future=True,
)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


def init_db() -> None:
    """Create all tables + indexes. Idempotent — safe to call on every boot."""
    Base.metadata.create_all(bind=engine)
