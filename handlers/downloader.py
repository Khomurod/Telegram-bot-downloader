import re

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from services.db import get_user_language, register_user
from services.i18n import t
from services.ytdlp_service import (
    build_download_options,
    cache_format_options,
    extract_info,
)
from utils.logger import logger

URL_REGEX = r"(https?://[^\s]+)"


def format_duration(duration_seconds, unknown_label: str):
    if not duration_seconds:
        return unknown_label

    mins, secs = divmod(int(duration_seconds), 60)
    if mins >= 60:
        hours, mins = divmod(mins, 60)
        return f"{hours}:{mins:02d}:{secs:02d}"

    return f"{mins}:{secs:02d}"


def build_options_keyboard(options: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    video_buttons = [
        InlineKeyboardButton(option["label"], callback_data=f"dl|{option['token']}")
        for option in options
        if option["kind"] == "video"
    ]
    audio_buttons = [
        InlineKeyboardButton(option["label"], callback_data=f"dl|{option['token']}")
        for option in options
        if option["kind"] == "audio"
    ]

    for index in range(0, len(video_buttons), 2):
        rows.append(video_buttons[index:index + 2])

    for button in audio_buttons:
        rows.append([button])

    return InlineKeyboardMarkup(rows)


@Client.on_message(filters.regex(URL_REGEX) & filters.private)
async def handle_link(client: Client, message: Message):
    user_id = message.from_user.id
    await register_user(user_id)
    language_code = await get_user_language(user_id)
    url = re.search(URL_REGEX, message.text).group(0)

    processing_msg = await message.reply_text(t(language_code, "analyzing_link"), quote=True)

    info = await extract_info(url)
    if not info or "error" in info:
        logger.warning(
            "Media extraction failed for user %s and URL %s: %s",
            user_id,
            url,
            info.get("error", "No info returned") if info else "No info returned",
        )
        await processing_msg.edit_text(
            t(language_code, "extract_failed")
        )
        return

    title = info.get("title") or t(language_code, "unknown")
    duration = format_duration(info.get("duration", 0), t(language_code, "unknown"))
    options = build_download_options(
        info,
        unknown_label=t(language_code, "unknown"),
        audio_label=t(language_code, "audio_mp3"),
    )
    cached_options = cache_format_options(processing_msg.chat.id, processing_msg.id, options)
    keyboard = build_options_keyboard(cached_options)

    video_count = sum(1 for option in cached_options if option["kind"] == "video")
    if video_count:
        prompt = t(language_code, "choose_format")
    else:
        prompt = t(language_code, "audio_only")

    text = (
        f"{t(language_code, 'media_found')}\n\n"
        f"{t(language_code, 'title_label')}: {title}\n"
        f"{t(language_code, 'duration_label')}: {duration}\n\n"
        f"{prompt}"
    )

    try:
        await processing_msg.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error sending info: {e}")
