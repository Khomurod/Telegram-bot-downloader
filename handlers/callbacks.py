import os
import re
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery
from services.ytdlp_service import download_media
from services.queue_manager import check_rate_limit, record_download, acquire_lock, release_lock
from services.db import log_download
from utils.logger import logger

@Client.on_callback_query(filters.regex(r"^dl\|"))
async def handle_download_callback(client: Client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    _, format_spec = callback_query.data.split("|")
    
    original_message = callback_query.message.reply_to_message
    if not original_message or not original_message.text:
        await callback_query.answer("Original link not found.", show_alert=True)
        return
        
    url_match = re.search(r'(https?://[^\s]+)', original_message.text)
    if not url_match:
        await callback_query.answer("No URL found.", show_alert=True)
        return
    url = url_match.group(0)
    
    if check_rate_limit(user_id):
        await callback_query.answer("Rate limit exceeded. Max 5 downloads per minute.", show_alert=True)
        return
        
    await callback_query.answer()
    
    async def notify_queue(position):
        await callback_query.message.edit_text(f"⏳ Your download is queued.\nPosition: {position}")
    
    position = await acquire_lock(send_wait_message=notify_queue)
    filepath = None
    
    try:
        await callback_query.message.edit_text("⬇️ Downloading media...")
        
        filepath = await download_media(url, format_spec)
        
        if not filepath or not os.path.exists(filepath):
            await callback_query.message.edit_text("❌ Download failed. Please try again.")
            await log_download(user_id, url, format_spec, "FAILED")
            return
            
        await callback_query.message.edit_text("⬆️ Uploading to Telegram...")
        
        if format_spec == "audio" or filepath.endswith('.mp3'):
            await client.send_audio(
                chat_id=callback_query.message.chat.id,
                audio=filepath,
                reply_to_message_id=original_message.id
            )
        else:
            try:
                await client.send_video(
                    chat_id=callback_query.message.chat.id,
                    video=filepath,
                    supports_streaming=True,
                    reply_to_message_id=original_message.id
                )
            except Exception as e:
                logger.warning(f"Failed to send as video: {e}, falling back to document.")
                await client.send_document(
                    chat_id=callback_query.message.chat.id,
                    document=filepath,
                    reply_to_message_id=original_message.id
                )
        
        await callback_query.message.delete()
        record_download(user_id)
        await log_download(user_id, url, format_spec, "SUCCESS")
        
    except Exception as e:
        logger.error(f"Error processing download for {user_id}: {e}")
        try:
            await callback_query.message.edit_text("❌ An error occurred during upload.")
        except:
            pass
        await log_download(user_id, url, format_spec, "ERROR")
    finally:
        release_lock()
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            logger.error(f"Error removing temp file {filepath}: {e}")
