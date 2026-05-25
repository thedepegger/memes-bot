"""Imgflip meme renderer.

Posts a `TemplateChoice` to the Imgflip caption_image endpoint and returns
the rendered image URL. `success: false` is a normal response, not an
exception — we log + return None and the scheduler skips the candidate.
On success we HEAD the URL to confirm the image actually loads before
queuing it in Telegram.
"""

from __future__ import annotations

import httpx

from config.settings import settings
from src.generators.types import TemplateChoice
from src.utils.logger import logger


_IMGFLIP_ENDPOINT = "https://api.imgflip.com/caption_image"
_TIMEOUT = httpx.Timeout(15.0)


def _build_form(template: TemplateChoice) -> dict[str, str]:
    """Imgflip form fields: template_id, creds, then boxes[i][text] per box."""
    form: dict[str, str] = {
        "template_id": template.template_id,
        "username": settings.IMGFLIP_USERNAME,
        "password": settings.IMGFLIP_PASSWORD,
    }
    for i, box in enumerate(template.boxes):
        form[f"boxes[{i}][text]"] = box
    return form


async def render_meme(template: TemplateChoice) -> str | None:
    """Render via Imgflip; return the image URL or None on any render failure.

    Failure modes (all return None, no exception):
    - HTTP error during POST (network, 5xx, etc.)
    - `success: false` in Imgflip response
    - Missing or unexpected response shape
    - HEAD request on returned URL fails or non-2xx
    """
    form = _build_form(template)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(_IMGFLIP_ENDPOINT, data=form)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as e:
        logger.error(
            f"meme: imgflip POST failed for template={template.template_id}: {e}"
        )
        return None
    except ValueError as e:
        logger.error(
            f"meme: imgflip response not JSON for template={template.template_id}: {e}"
        )
        return None

    if not isinstance(payload, dict) or not payload.get("success"):
        error_msg = payload.get("error_message") if isinstance(payload, dict) else "unknown"
        logger.error(
            f"meme: imgflip returned success=false for template={template.template_id}: "
            f"{error_msg}"
        )
        return None

    data = payload.get("data") or {}
    url = data.get("url") if isinstance(data, dict) else None
    if not isinstance(url, str) or not url:
        logger.error(
            f"meme: imgflip success but missing url for template={template.template_id}"
        )
        return None

    # Confirm the image actually loads before we hand it off.
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            head = await client.head(url)
        if head.status_code < 200 or head.status_code >= 300:
            logger.error(
                f"meme: HEAD check failed for url={url} status={head.status_code}"
            )
            return None
    except httpx.HTTPError as e:
        logger.error(f"meme: HEAD request errored for url={url}: {e}")
        return None

    logger.info(f"meme: rendered template={template.template_id} -> {url}")
    return url


__all__ = ["render_meme"]
