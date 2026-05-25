from __future__ import annotations

from datetime import datetime, timedelta

from src.utils.dedup import hash_topic


def test_hash_topic_deterministic():
    a = hash_topic("Bitcoin ETF sees record inflows today")
    b = hash_topic("Bitcoin ETF sees record inflows today")
    assert a == b
    assert isinstance(a, str)
    assert len(a) == 16
    # Hex characters only.
    int(a, 16)


def test_hash_topic_case_insensitive():
    upper = hash_topic("Bitcoin ETF sees record inflows today")
    lower = hash_topic("bitcoin etf sees record inflows today")
    assert upper == lower


def test_recently_used_after_record(tmp_db):
    from src.storage import repository

    repository.record_template_usage("t1", "h1")
    assert repository.recently_used("t1", "h1") is True


def test_recently_used_stale_row_past_window(tmp_db):
    """A row older than the window must not count as 'recently used'."""
    from src.storage import db as db_mod
    from src.storage import models, repository

    stale_when = datetime.utcnow() - timedelta(hours=49)

    with db_mod.SessionLocal() as session:
        row = models.TemplateUsage(
            template_id="t2",
            topic_hash="h2",
            used_at=stale_when,
        )
        session.add(row)
        session.commit()

    assert repository.recently_used("t2", "h2", hours=48) is False


def test_recently_used_different_template_same_hash(tmp_db):
    from src.storage import repository

    repository.record_template_usage("t1", "shared_hash")
    # Different template_id with the same topic hash must not register as used.
    assert repository.recently_used("t_other", "shared_hash") is False
