import asyncio
import os
import signal
import sys
import threading

from flask import Flask

from config import API_HASH, API_ID, BOT_TOKEN
from services.db import init_db
from utils.logger import logger

# Deferred imports and pyrogram initialization
app = None

def get_app():
    global app
    if app is None:
        from pyrogram import Client
        plugins = dict(root="handlers")
        app = Client(
            "downloader_bot",
            bot_token=BOT_TOKEN,
            api_id=API_ID,
            api_hash=API_HASH,
            plugins=plugins,
        )
    return app


def _start_health_server() -> None:
    """Run a minimal Flask health-check server in a background daemon thread."""
    web_app = Flask(__name__)

    @web_app.route("/")
    def home():
        return "Bot is running", 200

    @web_app.route("/health")
    def health():
        return "OK", 200

    port = int(os.environ.get("PORT", 8080))
    # Use the built-in development server with threading disabled and
    # reloader off so it does not spawn a child process inside the bot.
    web_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    logger.info("Initializing database...")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(init_db())

    logger.info("Starting health-check server...")
    threading.Thread(target=_start_health_server, daemon=True).start()

    # Graceful shutdown: stop the bot on SIGTERM (e.g. from Docker / Render).
    def _handle_sigterm(signum: int, frame: object) -> None:
        logger.info("Received SIGTERM – stopping bot...")
        get_app().stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    logger.info("Starting bot...")
    get_app().run()
