from pyrogram import Client, filters
from pyrogram.types import Message

from services.db import get_user_language, register_user
from services.i18n import build_language_keyboard, build_welcome_message, t

@Client.on_message(filters.command(["start"]) & filters.private)
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    await register_user(user_id)
    language_code = await get_user_language(user_id)

    await message.reply_text(
        build_welcome_message(language_code),
        reply_markup=build_language_keyboard(language_code),
    )


@Client.on_message(filters.command(["help"]) & filters.private)
async def help_command(client: Client, message: Message):
    user_id = message.from_user.id
    await register_user(user_id)
    language_code = await get_user_language(user_id)

    await message.reply_text(
        t(language_code, "help_text")
    )


@Client.on_message(filters.command("language") & filters.private)
async def language_command(client: Client, message: Message):
    user_id = message.from_user.id
    await register_user(user_id)
    language_code = await get_user_language(user_id)

    await message.reply_text(
        t(language_code, "language_prompt"),
        reply_markup=build_language_keyboard(language_code),
    )
