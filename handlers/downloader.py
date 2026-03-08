import re

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from services.db import register_user
from services.ytdlp_service import (
    build_download_options,
    cache_format_options,
    extract_info,
)
from utils.logger import logger

URL_REGEX = r"(https?://[^\s]+)"


def format_duration(duration_seconds):
    if not duration_seconds:
        return "Unknown"

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
    await register_user(message.from_user.id)
    url = re.search(URL_REGEX, message.text).group(0)

    processing_msg = await message.reply_text("Analyzing link...", quote=True)

    info = await extract_info(url)
    if not info or "error" in info:
        err_msg = info.get("error", "Unknown error") if info else "No info returned"
        await processing_msg.edit_text(
            "Sorry, I couldn't extract info from this link.\n\n"
            f"Error details:\n{err_msg[:800]}"
        )
        return

    title = info.get("title", "Unknown Title")
    duration = format_duration(info.get("duration", 0))
    options = build_download_options(info)
    cached_options = cache_format_options(processing_msg.chat.id, processing_msg.id, options)
    keyboard = build_options_keyboard(cached_options)

    video_count = sum(1 for option in cached_options if option["kind"] == "video")
    if video_count:
        prompt = "Choose one of the available formats below:"
    else:
        prompt = "Only audio is available for this link."

    text = (
        "Media found!\n\n"
        f"Title: {title}\n"
        f"Duration: {duration}\n\n"
        f"{prompt}"
    )

    try:
        await processing_msg.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error sending info: {e}")
