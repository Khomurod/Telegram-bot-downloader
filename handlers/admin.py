from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait
import asyncio
from config import ADMIN_IDS
from services.db import ensure_user_and_get_language, get_all_user_ids, get_stats
from services.i18n import normalize_language_code, t
from utils.logger import logger

def is_admin(user_id):
    return user_id in ADMIN_IDS


@Client.on_message(filters.command("users") & filters.private)
async def users_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    language_code = normalize_language_code(await ensure_user_and_get_language(user_id))

    parts = (message.text or "").split(maxsplit=1)
    limit = 50
    if len(parts) > 1 and parts[1].isdigit():
        limit = max(1, min(int(parts[1]), 200))

    db = await get_db()
    async with db.execute(
        """
        SELECT user_id, first_seen, language_code
        FROM users
        ORDER BY datetime(first_seen) DESC, user_id DESC
        LIMIT ?
        """,
        (limit,),
    ) as cursor:
        rows = await cursor.fetchall()

    if not rows:
        await message.reply_text("No users found in the database.")
        return

    lines = [f"Users list (latest {len(rows)}):", ""]
    for index, row in enumerate(rows, start=1):
        target_user_id, first_seen, target_language = row
        lines.append(
            f"{index}. `{target_user_id}` | {first_seen} | {target_language or language_code}"
        )

    lines.append("")
    lines.append(f"Tip: use `/users 100` to show more.")
    await message.reply_text("\n".join(lines))


@Client.on_message(filters.command("stats") & filters.private)
async def stats_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        return

    user_id = message.from_user.id
    language_code = normalize_language_code(await ensure_user_and_get_language(user_id))
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
    language_code = normalize_language_code(await ensure_user_and_get_language(user_id))

    if not message.reply_to_message:
        await message.reply_text(t(language_code, "broadcast_reply_required"))
        return

    status_msg = await message.reply_text(t(language_code, "broadcast_started"))

    success = 0
    failed = 0

    user_ids = await get_all_user_ids()
    for target_user_id in user_ids:
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
