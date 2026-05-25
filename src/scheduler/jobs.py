from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.fetchers.news import fetch_news
from src.fetchers.sentiment import fetch_sentiment
from src.fetchers.trending import fetch_trending
from src.generators.types import NewsItem
from src.generators.picker import pick_template
from src.generators.caption import write_caption
from src.generators.meme import render_meme
from src.publishers.telegram import drop_to_telegram
from src.publishers.twitter import post_to_x, TwitterRateLimitError
from src.storage import repository
from src.utils.dedup import hash_topic
from src.utils.logger import logger
from config.settings import settings


async def job_fetch_news() -> None:
    """Fetch latest crypto news headlines into storage."""
    try:
        items = await fetch_news(limit=20)
        count = len(items) if items is not None else 0
        logger.info("job_fetch_news: fetched %d news items", count)
    except Exception:
        logger.exception("job_fetch_news failed")


async def job_generate_batch() -> None:
    """Generate a batch of meme candidates from recent news."""
    try:
        news_list = repository.get_recent_news(limit=settings.CANDIDATES_PER_BATCH)
        sentiment = await fetch_sentiment()
        trending = await fetch_trending()

        for ns in news_list:
            try:
                news_item = NewsItem(
                    id=ns.id,
                    title=ns.title,
                    url=ns.url,
                    source=ns.source or "",
                    published_at=ns.fetched_at,
                )
                topic_hash = hash_topic(news_item.title)

                template = await pick_template(news_item, sentiment)
                if template is None:
                    continue

                if repository.recently_used(template.template_id, topic_hash):
                    continue

                image_url = await render_meme(template)
                if image_url is None:
                    continue

                caption = await write_caption(news_item, template, sentiment, trending)

                candidate = repository.save_candidate(
                    news_id=ns.id,
                    news_title=ns.title,
                    news_url=ns.url,
                    template_id=template.template_id,
                    template_name=template.template_name,
                    text_boxes=template.boxes,
                    caption=caption,
                    image_url=image_url,
                    sentiment_score=sentiment.score,
                    sentiment_label=sentiment.label,
                )

                await drop_to_telegram(candidate)
            except Exception:
                logger.exception(
                    "job_generate_batch: skipping news_id=%s due to error",
                    getattr(ns, "id", "<unknown>"),
                )
    except Exception:
        logger.exception("job_generate_batch failed")


async def job_post_queue() -> None:
    """Post approved-and-due candidates to X (Twitter)."""
    try:
        if settings.WARMUP_MODE:
            logger.info("job_post_queue: WARMUP_MODE active, skipping post step")
            return

        candidates = repository.get_approved_candidates_due_now()
        for c in candidates:
            try:
                tweet_id = await post_to_x(c)
                if tweet_id:
                    repository.mark_posted(c.id, tweet_id)
            except TwitterRateLimitError as e:
                repository.reschedule(c.id, delay_seconds=e.retry_after_seconds)
                logger.warning(
                    "job_post_queue: rate-limited on candidate %s, rescheduled +%ss",
                    c.id,
                    e.retry_after_seconds,
                )
            except Exception:
                logger.exception("post failed for candidate %s", c.id)
                repository.mark_failed(c.id)
    except Exception:
        logger.exception("job_post_queue failed")


def build_scheduler() -> AsyncIOScheduler:
    """Build the AsyncIOScheduler and register the three interval jobs.

    Caller is responsible for starting (`scheduler.start()`) and shutting it down.
    """
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        job_fetch_news,
        trigger="interval",
        hours=2,
        id="job_fetch_news",
        name="job_fetch_news",
        replace_existing=True,
    )
    scheduler.add_job(
        job_generate_batch,
        trigger="interval",
        hours=4,
        id="job_generate_batch",
        name="job_generate_batch",
        replace_existing=True,
    )
    scheduler.add_job(
        job_post_queue,
        trigger="interval",
        minutes=15,
        id="job_post_queue",
        name="job_post_queue",
        replace_existing=True,
    )
    return scheduler
