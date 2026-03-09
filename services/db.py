import aiosqlite

DB_PATH = "bot_data.db"
DEFAULT_LANGUAGE = "en"


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                link TEXT,
                format TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT
            )
            """
        )
        await db.execute(
            f"""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                language_code TEXT NOT NULL DEFAULT '{DEFAULT_LANGUAGE}'
            )
            """
        )

        async with db.execute("PRAGMA table_info(users)") as cursor:
            columns = {row[1] async for row in cursor}

        if "language_code" not in columns:
            await db.execute(
                f"ALTER TABLE users ADD COLUMN language_code TEXT NOT NULL DEFAULT '{DEFAULT_LANGUAGE}'"
            )

        await db.execute(
            "UPDATE users SET language_code = ? WHERE language_code IS NULL OR TRIM(language_code) = ''",
            (DEFAULT_LANGUAGE,),
        )
        await db.commit()


async def register_user(user_id: int, language_code: str = DEFAULT_LANGUAGE):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, language_code) VALUES (?, ?)",
            (user_id, language_code or DEFAULT_LANGUAGE),
        )
        await db.execute(
            "UPDATE users SET language_code = ? WHERE user_id = ? AND (language_code IS NULL OR TRIM(language_code) = '')",
            (DEFAULT_LANGUAGE, user_id),
        )
        await db.commit()


async def get_user_language(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT language_code FROM users WHERE user_id = ?",
            (user_id,),
        ) as cursor:
            row = await cursor.fetchone()

    if not row or not row[0]:
        return DEFAULT_LANGUAGE
    return row[0]


async def set_user_language(user_id: int, language_code: str):
    await register_user(user_id)

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET language_code = ? WHERE user_id = ?",
            (language_code or DEFAULT_LANGUAGE, user_id),
        )
        await db.commit()


async def log_download(user_id: int, link: str, format_choice: str, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO downloads (user_id, link, format, status) VALUES (?, ?, ?, ?)",
            (user_id, link, format_choice, status),
        )
        await db.commit()


async def get_stats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            total_users = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM downloads") as cursor:
            total_downloads = (await cursor.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM downloads WHERE date(timestamp) = date('now')"
        ) as cursor:
            today_downloads = (await cursor.fetchone())[0]

        return total_users, total_downloads, today_downloads
