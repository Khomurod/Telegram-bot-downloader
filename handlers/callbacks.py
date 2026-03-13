import os
import re

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery

from services.db import get_user_language, log_download, register_user, set_user_language
from services.i18n import (
    build_language_keyboard,
    build_welcome_message,
    get_language_label,
    normalize_language_code,
    t,
)
from services.queue_manager import acquire_lock, record_download, release_lock, get_rate_limit_retry_after_seconds
from services.ytdlp_service import (
    clear_cached_format_options,
    download_media,
    get_video_metadata,
    get_cached_format_option,
    get_all_cached_format_options,
)
from utils.logger import logger
from handlers.downloader import build_options_keyboard

LEGACY_FORMAT_SPECS = {"audio", "1080p", "720p", "480p"}


@Client.on_callback_query(filters.regex(r"^opt\|more$"))
async def handle_more_options_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await register_user(user_id)
    language_code = normalize_language_code(await get_user_language(user_id))

    options = get_all_cached_format_options(
        callback_query.message.chat.id,
        callback_query.message.id,
    )
    if not options:
        await callback_query.answer(t(language_code, "expired_selection"), show_alert=True)
        return

    try:
        await callback_query.message.edit_reply_markup(
            build_options_keyboard(options, language_code, expanded=True)
        )
        await callback_query.answer()
    except Exception as e:
        logger.error(f"Failed to expand options for user {user_id}: {e}")
        await callback_query.answer(t(language_code, "upload_error"), show_alert=True)


@Client.on_callback_query(filters.regex(r"^lang\|"))
async def handle_language_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await register_user(user_id)

    _, requested_language = callback_query.data.split("|", 1)
    language_code = normalize_language_code(requested_language)
    current_language = normalize_language_code(await get_user_language(user_id))

    if current_language != language_code:
        await set_user_language(user_id, language_code)

    await callback_query.answer(
        t(
            language_code,
            "language_updated",
            language_name=get_language_label(language_code),
        )
    )

    if current_language == language_code:
        return

    try:
        await callback_query.message.edit_text(
            build_welcome_message(language_code),
            reply_markup=build_language_keyboard(language_code),
        )
    except Exception as e:
        logger.error(f"Failed to update language message for {user_id}: {e}")


@Client.on_callback_query(filters.regex(r"^dl\|"))
async def handle_download_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    await register_user(user_id)
    language_code = normalize_language_code(await get_user_language(user_id))
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
        await callback_query.answer(t(language_code, "expired_selection"), show_alert=True)
        return

    original_message = callback_query.message.reply_to_message
    if not original_message or not original_message.text:
        await callback_query.answer(t(language_code, "original_link_not_found"), show_alert=True)
        return

    url_match = re.search(r"(https?://[^\s]+)", original_message.text)
    if not url_match:
        await callback_query.answer(t(language_code, "no_url_found"), show_alert=True)
        return
    url = url_match.group(0)

    retry_after = get_rate_limit_retry_after_seconds(user_id)
    if retry_after > 0:
        await callback_query.answer(
            t(language_code, "rate_limit_exceeded_wait", seconds=retry_after),
            show_alert=True,
        )
        return

    await callback_query.answer()

    async def notify_queue(position):
        await callback_query.message.edit_text(
            f"{t(language_code, 'queued', position=position)}\n\n"
            f"{t(language_code, 'queued_hint')}"
        )

    await acquire_lock(send_wait_message=notify_queue)
    filepath = None
    download_error = None

    try:
        await callback_query.message.edit_text(t(language_code, "downloading_media"))

        result = await download_media(url, format_spec)
        thumb_path = None
        if isinstance(result, dict):
            filepath = result.get("filepath")
            download_error = result.get("error")
            thumb_path = result.get("thumb")
        else:
            filepath = result

        if not filepath or not os.path.exists(filepath):
            if download_error:
                logger.error(f"Download failed for {url} ({log_format}): {download_error}")
                error_lower = str(download_error).lower()
                if "filesize" in error_lower or "too large" in error_lower:
                    await callback_query.message.edit_text(t(language_code, "file_too_large"))
                else:
                    await callback_query.message.edit_text(t(language_code, "download_failed"))
            else:
                await callback_query.message.edit_text(t(language_code, "download_failed"))
            await log_download(user_id, url, log_format, "FAILED")
            return

        await callback_query.message.edit_text(t(language_code, "uploading_to_telegram"))

        import time
        from pyrogram.errors import MessageNotModified

        last_update_time = [0]

        async def progress_callback(current, total):
            now = time.time()
            # Update message at most once every 3 seconds to avoid flooding
            if now - last_update_time[0] > 3:
                last_update_time[0] = now
                if total:
                    percent = current * 100 / total
                    try:
                        await callback_query.message.edit_text(
                            f"{t(language_code, 'uploading_to_telegram')}\n"
                            f"{percent:.1f}% ({current // 1048576}MB / {total // 1048576}MB)"
                        )
                    except MessageNotModified:
                        pass

        if format_spec == "audio" or filepath.endswith(".mp3"):
            await client.send_audio(
                chat_id=callback_query.message.chat.id,
                audio=filepath,
                thumb=thumb_path,
                reply_to_message_id=original_message.id,
                progress=progress_callback,
            )
        else:
            try:
                video_metadata = get_video_metadata(filepath)
                await client.send_video(
                    chat_id=callback_query.message.chat.id,
                    video=filepath,
                    thumb=thumb_path,
                    duration=video_metadata.get("duration", 0),
                    width=video_metadata.get("width", 0),
                    height=video_metadata.get("height", 0),
                    supports_streaming=True,
                    reply_to_message_id=original_message.id,
                    progress=progress_callback,
                )
            except Exception as e:
                logger.warning(f"Failed to send as video: {e}, falling back to document.")
                await client.send_document(
                    chat_id=callback_query.message.chat.id,
                    document=filepath,
                    thumb=thumb_path,
                    reply_to_message_id=original_message.id,
                    progress=progress_callback,
                )

        clear_cached_format_options(callback_query.message.chat.id, callback_query.message.id)
        await callback_query.message.delete()
        try:
            await client.send_message(
                chat_id=callback_query.message.chat.id,
                text=t(language_code, "done_ready"),
                reply_to_message_id=original_message.id,
            )
        except Exception:
            pass
        record_download(user_id)
        await log_download(user_id, url, log_format, "SUCCESS")

    except Exception as e:
        logger.error(f"Error processing download for {user_id}: {e}")
        try:
            await callback_query.message.edit_text(t(language_code, "upload_error"))
        except Exception:
            pass
        await log_download(user_id, url, log_format, "ERROR")
    finally:
        release_lock()
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
            if thumb_path and os.path.exists(thumb_path):
                os.remove(thumb_path)
        except Exception as e:
            logger.error(f"Error removing temp files: {e}")
