import asyncio

import aiohttp

from utils.logger import logger

GOOGLE_SHEETS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxxqjurAjuHfCG3IXZJJLJs7oo9wp5OoQvF12r0nDePbUKihx21PzfYt48310qaHeZc/exec"


async def register_user_to_sheet(user_id, first_name, language_code):
    payload = {
        "user_id": user_id,
        "first_name": first_name or "",
        "language_code": language_code or "",
    }

    timeout = aiohttp.ClientTimeout(total=10)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(GOOGLE_SHEETS_WEBHOOK_URL, json=payload) as response:
                if response.status >= 400:
                    response_text = await response.text()
                    logger.warning(
                        "Google Sheets user registration failed for user %s with status %s: %s",
                        user_id,
                        response.status,
                        response_text[:500],
                    )
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.warning(
            "Google Sheets user registration request failed for user %s: %s",
            user_id,
            exc,
        )
    except Exception as exc:
        logger.exception(
            "Unexpected error during Google Sheets user registration for user %s: %s",
            user_id,
            exc,
        )
