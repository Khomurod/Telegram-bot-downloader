from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
import asyncio
from config import ADMIN_IDS
from services.db import get_stats, get_user_language, register_user
from services.i18n import normalize_language_code, t
from utils.logger import logger

def is_admin(user_id):
    return user_id in ADMIN_IDS

@Client.on_message(filters.command("stats") & filters.private)
async def stats_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    await register_user(user_id)
    language_code = normalize_language_code(await get_user_language(user_id))
    total_users, total_downloads, today_downloads = await get_stats()

    text = (
        f"{t(language_code, 'stats_title')}\n\n"
        f"{t(language_code, 'total_users', count=total_users)}\n"
        f"{t(language_code, 'total_downloads', count=total_downloads)}\n"
        f"{t(language_code, 'downloads_today', count=today_downloads)}"
    )
    await message.reply_text(text)

@Client.on_message(filters.command("broadcast") & filters.private)
async def broadcast_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    await register_user(user_id)
    language_code = normalize_language_code(await get_user_language(user_id))

    if not message.reply_to_message:
        await message.reply_text(t(language_code, "broadcast_reply_required"))
        return

    from services.db import DB_PATH
    import aiosqlite

    status_msg = await message.reply_text(t(language_code, "broadcast_started"))

    success = 0
    failed = 0

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cursor:
            async for row in cursor:
                target_user_id = row[0]
                try:
                    await message.reply_to_message.copy(target_user_id)
                    success += 1
                    await asyncio.sleep(0.05)  # Prevent flood wait
                except FloodWait as e:
                    await asyncio.sleep(e.value)
                    try:
                        await message.reply_to_message.copy(target_user_id)
                        success += 1
                    except Exception as retry_error:
                        logger.warning(f"Broadcast retry failed for {target_user_id}: {retry_error}")
                        failed += 1
                except Exception as send_error:
                    logger.warning(f"Broadcast send failed for {target_user_id}: {send_error}")
                    failed += 1

    await status_msg.edit_text(
        t(language_code, "broadcast_finished", success=success, failed=failed)
    )
