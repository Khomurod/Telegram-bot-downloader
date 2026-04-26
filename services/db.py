from services.gsheets import (
    DEFAULT_LANGUAGE,
    ensure_user_and_get_language_sheet,
    get_all_user_ids_from_sheet,
    get_stats_from_sheet,
    log_download_to_sheet,
    register_user_to_sheet,
    set_user_language_in_sheet,
)
from utils.logger import logger


async def init_db():
    # Google Sheets webhook is now the primary persistence layer.
    logger.info("Google Sheets primary database mode is enabled.")


async def get_db():
    raise RuntimeError("get_db is not available in Google Sheets primary database mode.")


async def register_user(user_id: int, language_code: str = DEFAULT_LANGUAGE):
    await register_user_to_sheet(user_id, "", language_code or DEFAULT_LANGUAGE)


async def get_user_language(user_id: int) -> str:
    return await ensure_user_and_get_language(user_id)


async def set_user_language(user_id: int, language_code: str):
    await set_user_language_in_sheet(user_id, language_code or DEFAULT_LANGUAGE)


async def log_download(user_id: int, link: str, format_choice: str, status: str):
    await log_download_to_sheet(user_id, link, format_choice, status)


async def get_stats():
    return await get_stats_from_sheet()


async def get_all_user_ids() -> list[int]:
    return await get_all_user_ids_from_sheet()


async def ensure_user_and_get_language(user_id: int, first_name: str = "") -> str:
    return await ensure_user_and_get_language_sheet(
        user_id=user_id,
        first_name=first_name or "",
        default_language=DEFAULT_LANGUAGE,
    )
