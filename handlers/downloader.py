import re
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from services.ytdlp_service import extract_info
from services.db import register_user
from utils.logger import logger

URL_REGEX = r'(https?://[^\s]+)'

def format_duration(duration_seconds):
    if not duration_seconds:
        return "Unknown"
    mins, secs = divmod(int(duration_seconds), 60)
    if mins > 60:
        hours, mins = divmod(mins, 60)
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"

@Client.on_message(filters.regex(URL_REGEX) & filters.private)
async def handle_link(client: Client, message: Message):
    await register_user(message.from_user.id)
    url = re.search(URL_REGEX, message.text).group(0)
    
    processing_msg = await message.reply_text("🔍 Analyzing link...", quote=True)
    
    info = await extract_info(url)
    if not info or "error" in info:
        err_msg = info.get("error", "Unknown Error") if info else "No info returned"
        await processing_msg.edit_text(f"❌ Sorry, I couldn't extract info from this link.\n\n**Error details:**\n`{err_msg[:800]}`")
        return
        
    title = info.get("title", 'Unknown Title')
    duration = format_duration(info.get("duration", 0))
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📹 1080p", callback_data="dl|1080p"),
            InlineKeyboardButton("📹 720p", callback_data="dl|720p")
        ],
        [
            InlineKeyboardButton("📹 480p", callback_data="dl|480p"),
            InlineKeyboardButton("🎵 Audio (MP3)", callback_data="dl|audio")
        ]
    ])
    
    text = f"**Video found!**\n\n**Title:** `{title}`\n**Duration:** `{duration}`\n\nChoose download format:"
    
    try:
        await processing_msg.edit_text(text, reply_markup=keyboard)
    except Exception as e:
        logger.error(f"Error sending info: {e}")
