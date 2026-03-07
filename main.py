import asyncio
import sys

try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
from pyrogram import Client
from config import BOT_TOKEN, API_ID, API_HASH
from services.db import init_db
from utils.logger import logger

# Automatically load handlers from the "handlers" package
plugins = dict(root="handlers")

app = Client(
    "downloader_bot",
    bot_token=BOT_TOKEN,
    api_id=API_ID if API_ID else None,
    api_hash=API_HASH if API_HASH else None,
    plugins=plugins
)

if __name__ == "__main__":
    logger.info("Initializing database...")
    
    # Try getting the event loop carefully to initialize the db
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    loop.run_until_complete(init_db())
    
    logger.info("Starting bot using native app.run()...")
    if not API_ID or not API_HASH:
        logger.warning("API_ID or API_HASH is missing! Pyrogram might fail to start if the local session needs them.")
    
    app.run()
