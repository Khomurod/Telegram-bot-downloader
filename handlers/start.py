import asyncio

from pyrogram import Client, filters
from pyrogram.types import Message

from services.db import ensure_user_and_get_language
from services.gsheets import register_user_to_sheet
from services.i18n import build_language_keyboard, build_welcome_message, t

@Client.on_message(filters.command(["start"]) & filters.private)
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    first_name = message.from_user.first_name if message.from_user else ""
    language_code = await ensure_user_and_get_language(user_id, first_name=first_name)
    asyncio.create_task(register_user_to_sheet(user_id, first_name, language_code))

    await message.reply_text(
        build_welcome_message(language_code),
        reply_markup=build_language_keyboard(language_code),
    )


@Client.on_message(filters.command(["help"]) & filters.private)
async def help_command(client: Client, message: Message):
    user_id = message.from_user.id
    language_code = await ensure_user_and_get_language(user_id)

    await message.reply_text(
        t(language_code, "help_text")
    )


@Client.on_message(filters.command("language") & filters.private)
async def language_command(client: Client, message: Message):
    user_id = message.from_user.id
    language_code = await ensure_user_and_get_language(user_id)

    await message.reply_text(
        t(language_code, "language_prompt"),
        reply_markup=build_language_keyboard(language_code),
    )
