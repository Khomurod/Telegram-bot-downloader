from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
import asyncio
from config import ADMIN_IDS
from services.db import get_stats
from utils.logger import logger

def is_admin(user_id):
    return user_id in ADMIN_IDS

@Client.on_message(filters.command("stats") & filters.private)
async def stats_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
        
    total_users, total_downloads, today_downloads = await get_stats()
    
    text = (
        "📊 **Bot Statistics**\n\n"
        f"👥 Total Users: `{total_users}`\n"
        f"⬇️ Total Downloads: `{total_downloads}`\n"
        f"📅 Downloads Today: `{today_downloads}`"
    )
    await message.reply_text(text)

@Client.on_message(filters.command("broadcast") & filters.private)
async def broadcast_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return
        
    if not message.reply_to_message:
        await message.reply_text("Please reply to a message you want to broadcast.")
        return
        
    from services.db import DB_PATH
    import aiosqlite
    
    status_msg = await message.reply_text("Broadcast started...")
    
    success = 0
    failed = 0
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            async for row in cursor:
                user_id = row[0]
                try:
                    await message.reply_to_message.copy(user_id)
                    success += 1
                    await asyncio.sleep(0.05)  # Prevent flood wait
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    await message.reply_to_message.copy(user_id)
                    success += 1
                except Exception:
                    failed += 1
                    
    await status_msg.edit_text(f"✅ Broadcast finished!\n\nSuccessful: `{success}`\nFailed: `{failed}`")
