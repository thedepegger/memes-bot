from __future__ import annotations

import argparse
import asyncio
import json

from src.fetchers.news import fetch_news
from src.fetchers.sentiment import fetch_sentiment
from src.fetchers.trending import fetch_trending
from src.generators.types import NewsItem
from src.generators.picker import pick_template
from src.generators.caption import write_caption
from src.generators.meme import render_meme
from src.publishers.telegram import build_bot, build_dispatcher, run_polling
from src.scheduler.jobs import build_scheduler
from src.storage import repository
from src.storage.db import init_db
from src.utils.logger import logger


async def run_dry_run() -> None:
    """One-shot pipeline preview without scheduler or Telegram polling.

    Hits live APIs; each per-news iteration is wrapped in try/except so missing
    API keys or transient failures don't propagate.
    """
    init_db()

    try:
        await fetch_news(limit=5)
    except Exception:
        logger.exception("dry-run: fetch_news failed; continuing")

    try:
        sentiment = await fetch_sentiment()
    except Exception:
        logger.exception("dry-run: fetch_sentiment failed; aborting dry-run")
        return

    try:
        trending = await fetch_trending()
    except Exception:
        logger.exception("dry-run: fetch_trending failed; aborting dry-run")
        return

    try:
        news_list = repository.get_recent_news(limit=5)
    except Exception:
        logger.exception("dry-run: get_recent_news failed; aborting dry-run")
        return

    for ns in news_list:
        try:
            news_item = NewsItem(
                id=ns.id,
                title=ns.title,
                url=ns.url,
                source=ns.source or "",
                published_at=ns.fetched_at,
            )
            template = await pick_template(news_item, sentiment)
            if template is None:
                continue
            image_url = await render_meme(template)
            if image_url is None:
                continue
            caption = await write_caption(news_item, template, sentiment, trending)
            print(
                json.dumps(
                    {
                        "template_id": template.template_id,
                        "template_name": template.template_name,
                        "boxes": template.boxes,
                        "caption": caption,
                        "image_url": image_url,
                    }
                )
            )
        except Exception:
            logger.exception("dry-run iteration failed; continuing")


async def run_normal() -> None:
    """Production path: init DB, start scheduler, run aiogram polling forever."""
    init_db()
    bot = build_bot()
    dp = build_dispatcher()
    scheduler = build_scheduler()
    scheduler.start()
    logger.info("scheduler started with %d jobs", len(scheduler.get_jobs()))
    try:
        await run_polling(dp, bot)
    finally:
        scheduler.shutdown(wait=False)
        try:
            await bot.session.close()
        except Exception:
            logger.exception("error closing bot session")


async def main(args: argparse.Namespace) -> None:
    if args.dry_run:
        await run_dry_run()
    else:
        await run_normal()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crypto meme bot")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run a single pipeline preview without scheduler or Telegram polling",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(args))
