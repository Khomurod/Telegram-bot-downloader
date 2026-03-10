import os
import sys
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

# Validate required configuration at startup so the process fails fast with a
# clear message rather than crashing later with a cryptic error.
_missing = [name for name, value in (
    ("BOT_TOKEN", BOT_TOKEN),
    ("API_ID", API_ID),
    ("API_HASH", API_HASH),
) if not value]

if _missing:
    sys.exit(
        f"[config] Missing required environment variable(s): {', '.join(_missing)}. "
        "Copy .env.example to .env and fill in the values."
    )

# Parse ADMIN_IDS as a list of integers if provided
admin_ids_str = os.getenv("ADMIN_IDS", "")
ADMIN_IDS = [int(x.strip()) for x in admin_ids_str.split(",") if x.strip().isdigit()]

API_ID = int(API_ID)
