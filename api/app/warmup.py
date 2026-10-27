"""Load the extract and chat models into the runtime at startup."""

from __future__ import annotations

import logging

import httpx

from .config import Settings

log = logging.getLogger(__name__)


async def warm_up(settings: Settings) -> None:
    url = f"{settings.model_base_url}/chat/completions"
    for model in dict.fromkeys((settings.extract_model, settings.chat_model)):
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                (await client.post(url, json=payload)).raise_for_status()
        except Exception as exc:  # noqa: BLE001 - warm-up must never take the API down
            log.warning("model warm-up failed for %s: %s", model, exc)
