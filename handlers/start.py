from pyrogram import Client, filters
from pyrogram.types import Message
from services.db import register_user

@Client.on_message(filters.command(["start", "help"]) & filters.private)
async def start_command(client: Client, message: Message):
    await register_user(message.from_user.id)
    text = (
        "👋 Welcome to the Downloader Bot!\n\n"
        "Send me a link from YouTube, TikTok, Instagram, etc., and I'll download the video/audio for you.\n"
        "Just paste the link to get started!"
    )
    await message.reply_text(text)
