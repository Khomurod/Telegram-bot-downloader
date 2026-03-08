# Telegram Downloader Bot

A simple, fast, and robust Telegram bot to download videos and audio from platforms like YouTube, TikTok, Instagram, and more using `yt-dlp` and `pyrogram`.

## Features
- **Support for multiple platforms:** YouTube, TikTok, Instagram, Twitter/X, and more.
- **Dynamic Format Options:** The bot inspects each link and shows the video formats and qualities that yt-dlp reports as available, plus Audio (MP3).
- **Large File Support:** Can upload files up to 2 GB via Telegram Client API (`Pyrogram`).
- **Resource Efficient:** CPU usage limited through a concurrent download queue (max 2 simultaneously).
- **Rate Limit:** Prevents spam (limit of 5 downloads per minute per user).
- **Admin Commands:** Track statistics with `/stats` and message all users with `/broadcast`.
- **Zero Clutter:** Automatically cleans up temporary files after sending.

## Prerequisites
1. **Python 3.10+**
2. **FFmpeg**: Required by `yt-dlp` for extracting audio and merging video formats.
   - For Windows: Download from `https://gyan.dev/ffmpeg/builds/` and add to your System PATH.
   - For Linux: `sudo apt install ffmpeg`
3. **Node.js**: Recommended for full YouTube format detection with modern `yt-dlp` challenge solving.

## Installation

1. Clone or copy the project files to your server/computer.
2. Install the required python packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up the `.env` file:
   - Provide your `BOT_TOKEN` from [@BotFather](https://t.me/BotFather)
   - Provide your `API_ID` and `API_HASH` from [my.telegram.org](https://my.telegram.org/auth)
   - *(Optional)* Add your numeric Telegram User ID to `ADMIN_IDS` to use `/stats` and `/broadcast`.

## Running the Bot

Run the bot directly via:
```bash
python main.py
```

## Security & Deployment
The bot stores statistics in a lightweight SQLite database (`bot_data.db`) located in the same directory.
For 24/7 deployment, use Docker, PM2, or a systemd service. Make sure `ffmpeg` is available in your production environment!
