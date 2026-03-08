import os
import re

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

from services.db import log_download
from services.queue_manager import (
    acquire_lock,
    check_rate_limit,
    record_download,
    release_lock,
)
from services.ytdlp_service import (
    clear_cached_format_options,
    download_media,
    get_cached_format_option,
)
from utils.logger import logger

LEGACY_FORMAT_SPECS = {"audio", "1080p", "720p", "480p"}


@Client.on_callback_query(filters.regex(r"^dl\|"))
async def handle_download_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, selection_token = callback_query.data.split("|", 1)

    selected_option = get_cached_format_option(
        callback_query.message.chat.id,
        callback_query.message.id,
        selection_token,
    )
    if selected_option:
        format_spec = selected_option["selector"]
        log_format = selected_option["log_format"]
    elif selection_token in LEGACY_FORMAT_SPECS:
        format_spec = selection_token
        log_format = selection_token
    else:
        await callback_query.answer("This selection has expired. Send the link again.", show_alert=True)
        return

    original_message = callback_query.message.reply_to_message
    if not original_message or not original_message.text:
        await callback_query.answer("Original link not found.", show_alert=True)
        return

    url_match = re.search(r"(https?://[^\s]+)", original_message.text)
    if not url_match:
        await callback_query.answer("No URL found.", show_alert=True)
        return
    url = url_match.group(0)

    if check_rate_limit(user_id):
        await callback_query.answer("Rate limit exceeded. Max 5 downloads per minute.", show_alert=True)
        return

    await callback_query.answer()

    async def notify_queue(position):
        await callback_query.message.edit_text(f"Your download is queued.\nPosition: {position}")

    await acquire_lock(send_wait_message=notify_queue)
    filepath = None
    download_error = None

    try:
        await callback_query.message.edit_text("Downloading media...")

        result = await download_media(url, format_spec)
        if isinstance(result, dict):
            filepath = result.get("filepath")
            download_error = result.get("error")
        else:
            filepath = result

        if not filepath or not os.path.exists(filepath):
            if download_error:
                logger.error(f"Download failed for {url} ({log_format}): {download_error}")
                safe_reason = download_error.replace("\n", " ").strip()[:240]
                await callback_query.message.edit_text(f"Download failed.\nReason: {safe_reason}")
            else:
                await callback_query.message.edit_text("Download failed. Please try again.")
            await log_download(user_id, url, log_format, "FAILED")
            return

        await callback_query.message.edit_text("Uploading to Telegram...")

        if format_spec == "audio" or filepath.endswith(".mp3"):
            await client.send_audio(
                chat_id=callback_query.message.chat.id,
                audio=filepath,
                reply_to_message_id=original_message.id,
            )
        else:
            try:
                await client.send_video(
                    chat_id=callback_query.message.chat.id,
                    video=filepath,
                    supports_streaming=True,
                    reply_to_message_id=original_message.id,
                )
            except Exception as e:
                logger.warning(f"Failed to send as video: {e}, falling back to document.")
                await client.send_document(
                    chat_id=callback_query.message.chat.id,
                    document=filepath,
                    reply_to_message_id=original_message.id,
                )

        clear_cached_format_options(callback_query.message.chat.id, callback_query.message.id)
        await callback_query.message.delete()
        record_download(user_id)
        await log_download(user_id, url, log_format, "SUCCESS")

    except Exception as e:
        logger.error(f"Error processing download for {user_id}: {e}")
        try:
            await callback_query.message.edit_text("An error occurred during upload.")
        except Exception:
            pass
        await log_download(user_id, url, log_format, "ERROR")
    finally:
        release_lock()
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            logger.error(f"Error removing temp file {filepath}: {e}")
