from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from config.settings import settings
from src.storage.db import init_db


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Swap settings.DATABASE_PATH to a temp file and re-init the engine.

    The engine/SessionLocal in src.storage.db were bound at import time using
    the on-disk DATABASE_PATH. We monkeypatch both, then patch any module that
    imported SessionLocal by reference (notably src.storage.repository).
    """
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_path))

    import src.storage.db as db_mod

    new_engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    new_session = sessionmaker(
        bind=new_engine, expire_on_commit=False, future=True
    )
    monkeypatch.setattr(db_mod, "engine", new_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", new_session)

    # If repository imported SessionLocal directly (e.g. `from src.storage.db
    # import SessionLocal`), the reference inside repository.py is the old one.
    # Rebind it.
    import src.storage.repository as repo_mod

    if hasattr(repo_mod, "SessionLocal"):
        monkeypatch.setattr(repo_mod, "SessionLocal", new_session)

    init_db()
    yield db_path


@pytest.fixture
def sample_news():
    fixture_path = Path(__file__).parent / "fixtures" / "sample_news.json"
    return json.loads(fixture_path.read_text())
