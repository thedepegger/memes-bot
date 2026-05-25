import sys
from pathlib import Path

from loguru import logger

from config.settings import settings


_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return

    logger.remove()

    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )

    log_path = Path("logs/bot.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        str(log_path),
        level=settings.LOG_LEVEL,
        rotation="10 MB",
        retention="14 days",
        enqueue=True,
    )

    _configured = True


_configure()

__all__ = ["logger"]
