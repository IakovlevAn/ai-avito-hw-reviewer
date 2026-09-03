from __future__ import annotations

import httpx

from app.config import Settings


async def send_telegram(settings: Settings, message: str) -> bool:
    if not settings.telegram_bot_token or not settings.telegram_default_chat_id:
        return False
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {
        "chat_id": settings.telegram_default_chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=payload)
        return response.status_code == 200
    except httpx.HTTPError:
        # Notification failure must not expose the token or break a completed review.
        return False
