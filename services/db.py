import aiosqlite
import os
from datetime import datetime

DB_PATH = "bot_data.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                link TEXT,
                format TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_seen DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()

async def register_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()

async def log_download(user_id: int, link: str, format_choice: str, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO downloads (user_id, link, format, status) VALUES (?, ?, ?, ?)",
            (user_id, link, format_choice, status)
        )
        await db.commit()

async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM downloads") as cursor:
            total_downloads = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM downloads WHERE date(timestamp) = date('now')") as cursor:
            today_downloads = (await cursor.fetchone())[0]
            
        return total_users, total_downloads, today_downloads
