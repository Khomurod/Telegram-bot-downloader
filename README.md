# Telegram Downloader Bot

A Telegram bot for downloading video and audio from YouTube, TikTok, Instagram, Twitter/X, and other sites supported by yt-dlp. It uses Pyrogram for Telegram delivery, offers compact quality buttons by default, and can expand to show the full list of available formats.

## Features
- Supports multiple platforms through yt-dlp.
- Multi-language interface: English, Russian, and Uzbek.
- Compact format picker: users first see `Best`, `Good`, `Bad`, and `Audio (MP3)`.
- Expanded format picker: tapping `More options` reveals all detected video formats.
- Fallback video choices for links where yt-dlp returns metadata but hides detailed format lists.
- Uploads files up to Telegram's client API limit of about 2 GB.
- Simple queueing with up to 2 concurrent downloads.
- Per-user rate limit of 5 downloads per minute.
- Admin-only `/stats` and `/broadcast` commands.
- Automatic cleanup of downloaded files and thumbnails after sending.
- In-memory analysis caching to speed up repeated requests for the same link.

## User Flow
1. Send a supported media link in a private chat.
2. The bot analyzes the link and shows title and duration.
3. The first keyboard shows a compact set of actions:
   - `Best`
   - `Good`
   - `Bad`
   - `Audio (MP3)`
   - `More options` when extra video formats are available
4. If the user taps `More options`, the bot replaces the compact keyboard with the full list of available video formats.
5. After the user chooses an option, the bot downloads the media and uploads it back to Telegram.

## Commands
- `/start` - show the welcome message and language selector
- `/help` - show usage instructions
- `/language` - change bot language
- `/stats` - admin only
- `/broadcast` - admin only, must be used as a reply to a message

## Requirements
1. Python 3.10+
2. FFmpeg
   - Linux: `sudo apt install ffmpeg`
   - Windows: install FFmpeg and add it to `PATH`
3. Node.js is recommended for better YouTube extraction reliability with modern yt-dlp JS challenge handling

## Installation
1. Clone the repository.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create your environment file:

```bash
cp .env.example .env
```

4. Fill in these values in `.env`:
- `BOT_TOKEN` from [@BotFather](https://t.me/BotFather)
- `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org/auth)
- `ADMIN_IDS` as a comma-separated list of numeric Telegram user IDs for admin commands
- `YTDLP_COOKIEFILE` optionally, if you want yt-dlp to use an external cookies file for authenticated or restricted downloads

## Running Locally
Start the bot with:

```bash
python main.py
```

The app also starts a minimal HTTP server for deployment health checks:
- `/` returns `Bot is running`
- `/health` returns `OK`

## Deployment Notes
- SQLite data is stored locally in `bot_data.db`.
- Temporary downloads are stored in `downloads/` and removed after upload.
- A sample Render deployment file is included in `render.yaml`.
- For 24/7 hosting, make sure FFmpeg is available in the runtime environment.
- If YouTube extraction is unreliable in production, install Node.js and optionally provide a valid cookies file.

## Configuration Summary
- `BOT_TOKEN` - required
- `API_ID` - required
- `API_HASH` - required
- `ADMIN_IDS` - optional
- `YTDLP_COOKIEFILE` - optional
