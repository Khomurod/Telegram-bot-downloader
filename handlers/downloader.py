import asyncio
import re

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from services.db import ensure_user_and_get_language
from services.i18n import t
from services.ytdlp_service import build_download_options, cache_format_options, extract_info
from utils.logger import logger

URL_REGEX = r"(https?://[^\s]+)"
COMPACT_VIDEO_TIERS = 3


def format_duration(duration_seconds, unknown_label: str):
    if not duration_seconds:
        return unknown_label

    mins, secs = divmod(int(duration_seconds), 60)
    if mins >= 60:
        hours, mins = divmod(mins, 60)
        return f"{hours}:{mins:02d}:{secs:02d}"

    return f"{mins}:{secs:02d}"


def _pick_compact_video_options(video_options: list[dict]) -> list[dict]:
    if len(video_options) <= COMPACT_VIDEO_TIERS:
        return video_options

    candidate_indexes = [0, len(video_options) // 2, len(video_options) - 1]
    selected: list[dict] = []
    seen_tokens: set[str] = set()

    for index in candidate_indexes:
        option = video_options[index]
        token = option["token"]
        if token in seen_tokens:
            continue
        selected.append(option)
        seen_tokens.add(token)

    if len(selected) >= COMPACT_VIDEO_TIERS:
        return selected[:COMPACT_VIDEO_TIERS]

    for option in video_options:
        token = option["token"]
        if token in seen_tokens:
            continue
        selected.append(option)
        seen_tokens.add(token)
        if len(selected) == COMPACT_VIDEO_TIERS:
            break

    return selected


def build_options_keyboard(options: list[dict], language_code: str, expanded: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    video_options = [opt for opt in options if opt["kind"] == "video"]
    audio_options = [opt for opt in options if opt["kind"] == "audio"]

    compact_video_options = _pick_compact_video_options(video_options)
    displayed_video_options = video_options if expanded else compact_video_options

    if expanded:
        video_buttons = [
            InlineKeyboardButton(option["label"], callback_data=f"dl|{option['token']}")
            for option in displayed_video_options
        ]
    else:
        tier_keys = ["quality_excellent", "quality_good", "quality_bad"]
        video_buttons = []
        for index, option in enumerate(displayed_video_options):
            tier_key = tier_keys[min(index, len(tier_keys) - 1)]
            video_buttons.append(
                InlineKeyboardButton(
                    t(language_code, tier_key),
                    callback_data=f"dl|{option['token']}",
                )
            )

    audio_buttons = [
        InlineKeyboardButton(option["label"], callback_data=f"dl|{option['token']}")
        for option in audio_options
    ]

    if expanded:
        for index in range(0, len(video_buttons), 2):
            rows.append(video_buttons[index : index + 2])
    else:
        for button in video_buttons:
            rows.append([button])

    for button in audio_buttons:
        rows.append([button])

    if not expanded and len(video_options) > len(displayed_video_options):
        rows.append([
            InlineKeyboardButton(
                t(language_code, "more_options"),
                callback_data="opt|more",
            )
        ])

    return InlineKeyboardMarkup(rows)


@Client.on_message(filters.regex(URL_REGEX) & filters.private)
async def handle_link(client: Client, message: Message):
    user_id = message.from_user.id
    language_code = await ensure_user_and_get_language(user_id)
    text = (message.text or message.caption or "").strip()

    match = re.search(URL_REGEX, text or "")
    if not match:
        await message.reply_text(
            f"{t(language_code, 'no_url_found')}\n\n"
            f"{t(language_code, 'send_link_example', example='https://youtu.be/dQw4w9WgXcQ')}",
            quote=True,
        )
        return

    url = match.group(0)

    processing_msg = await message.reply_text(
        t(language_code, "analyzing_link"),
        quote=True,
    )

    analysis_done = {"value": False}

    async def _slow_hint():
        await asyncio.sleep(7)
        if analysis_done["value"]:
            return
        try:
            await processing_msg.edit_text(t(language_code, "analyzing_link_slow"))
        except Exception:
            # Message was likely already updated; ignore.
            pass

    asyncio.create_task(_slow_hint())

    info = await extract_info(url)
    if not info or "error" in info:
        logger.warning(
            "Media extraction failed for user %s and URL %s: %s",
            user_id,
            url,
            info.get("error", "No info returned") if info else "No info returned",
        )
        analysis_done["value"] = True
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
    cached_options = cache_format_options(
        processing_msg.chat.id,
        processing_msg.id,
        options,
    )
    keyboard = build_options_keyboard(cached_options, language_code, expanded=False)

    video_count = sum(1 for option in cached_options if option["kind"] == "video")
    if video_count:
        prompt = t(language_code, "choose_format")
    else:
        prompt = t(language_code, "audio_only")

    text_lines = [
        t(language_code, "media_found"),
        "",
    ]
    text_lines.append(f"{t(language_code, 'title_label')}: {title}")
    text_lines.append(f"{t(language_code, 'duration_label')}: {duration}")

    if video_count:
        text_lines.append("")
        text_lines.append(t(language_code, "formats_video_header"))
        text_lines.append(prompt)

    if any(opt["kind"] == "audio" for opt in cached_options):
        text_lines.append("")
        text_lines.append(t(language_code, "formats_audio_header"))

    text = "\n".join(text_lines)

    try:
        analysis_done["value"] = True
        await processing_msg.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error sending info: {e}")
