import asyncio
import os
import uuid
import imageio_ffmpeg
from yt_dlp import YoutubeDL
from concurrent.futures import ThreadPoolExecutor
from utils.logger import logger

# Keep max workers low to save CPU (2 downloads at once)
executor = ThreadPoolExecutor(max_workers=2)
DOWNLOAD_DIR = "downloads"

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

def get_base_ydl_opts() -> dict:
    return {
        'quiet': True,
        'no_warnings': True,
        'outtmpl': os.path.join(DOWNLOAD_DIR, f'%(id)s_{uuid.uuid4().hex[:8]}.%(ext)s'),
        'noplaylist': True,
        'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe(),
    }

async def extract_info(url: str) -> dict:
    """Extract metadata without downloading."""
    def _extract():
        opts = get_base_ydl_opts()
        opts['extract_flat'] = True
        try:
            with YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception as e:
            logger.error(f"Error extracting info for {url}: {e}")
            return None
            
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _extract)

async def download_media(url: str, format_spec: str) -> str:
    """Download media and return the filepath."""
    def _download():
        opts = get_base_ydl_opts()
        
        # Audio special handling
        if format_spec == "audio":
            opts['format'] = 'bestaudio/best'
            opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '128',
            }]
        # Specific resolution handling
        elif format_spec == "1080p":
            opts['format'] = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'
        elif format_spec == "720p":
            opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
        elif format_spec == "480p":
            opts['format'] = 'bestvideo[height<=480]+bestaudio/best[height<=480]/best'
        else:
            opts['format'] = 'best' # Fallback
            
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                filepath = ""
                if 'requested_downloads' in info:
                    filepath = info['requested_downloads'][0]['filepath']
                else:
                    filepath = ydl.prepare_filename(info)
                
                # Manual extension fix for audio post-processor if needed
                if format_spec == "audio" and not filepath.endswith('.mp3'):
                    base, _ = os.path.splitext(filepath)
                    if os.path.exists(base + '.mp3'):
                        filepath = base + '.mp3'
                
                return filepath
        except Exception as e:
            logger.error(f"Error downloading media for {url}: {e}")
            return None

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _download)
