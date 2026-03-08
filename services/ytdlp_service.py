import asyncio
import copy
import glob
import os
import traceback
import uuid
import imageio_ffmpeg
from yt_dlp import YoutubeDL
from concurrent.futures import ThreadPoolExecutor
from utils.logger import logger

# Keep max workers low to save CPU (2 downloads at once)
executor = ThreadPoolExecutor(max_workers=2)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
COOKIE_FILE = os.path.join(BASE_DIR, "cookies.txt")
COOKIE_FILE_DISABLED = False

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)


def _get_cookie_file() -> str | None:
    global COOKIE_FILE_DISABLED

    if COOKIE_FILE_DISABLED:
        return None

    env_cookie = os.getenv("YTDLP_COOKIEFILE", "").strip()
    if env_cookie and os.path.exists(env_cookie):
        return env_cookie

    if os.path.exists(COOKIE_FILE):
        return COOKIE_FILE

    return None


def _normalize_path(path: str | None) -> str | None:
    if not path:
        return None
    return path if os.path.isabs(path) else os.path.abspath(path)


def _resolve_output_path(info: dict, ydl: YoutubeDL, format_spec: str) -> str | None:
    candidates = []

    requested_downloads = info.get("requested_downloads") or []
    for item in requested_downloads:
        for key in ("filepath", "filename", "_filename"):
            value = item.get(key)
            if value:
                candidates.append(value)

    for key in ("filepath", "_filename", "filename"):
        value = info.get(key)
        if value:
            candidates.append(value)

    try:
        prepared = ydl.prepare_filename(info)
    except Exception:
        prepared = None

    if prepared:
        candidates.append(prepared)
        base, _ = os.path.splitext(prepared)
        if format_spec == "audio":
            candidates.append(base + ".mp3")
        else:
            candidates.append(base + ".mp4")

    for candidate in candidates:
        normalized = _normalize_path(candidate)
        if normalized and os.path.exists(normalized):
            return normalized

    media_id = info.get("id")
    if media_id:
        pattern = os.path.join(DOWNLOAD_DIR, f"{media_id}_*")
        matches = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if matches:
            return os.path.abspath(matches[0])

    return _normalize_path(candidates[0] if candidates else None)


def _apply_format_opts(opts: dict, format_spec: str) -> None:
    # Audio special handling
    if format_spec == "audio":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }]
        return

    # Specific resolution handling (prioritize mp4/m4a for Telegram compatibility)
    if format_spec == "1080p":
        opts["format"] = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
    elif format_spec == "720p":
        opts["format"] = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best"
    elif format_spec == "480p":
        opts["format"] = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/bestvideo[height<=480]+bestaudio/best[height<=480]/best"
    else:
        opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/bestvideo+bestaudio/best"

    opts["merge_output_format"] = "mp4"


def get_base_ydl_opts() -> dict:
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'retries': 3,
        'fragment_retries': 3,
        'continuedl': True,
        'outtmpl': os.path.join(DOWNLOAD_DIR, f'%(id)s_{uuid.uuid4().hex[:8]}.%(ext)s'),
        'noplaylist': True,
        'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe(),
    }

    cookie_file = _get_cookie_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file

    return opts

async def extract_info(url: str) -> dict:
    """Extract metadata without downloading."""
    def _extract():
        # Use an isolated, barebones options dict for info extraction
        opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': True,
            'ignore_no_formats_error': True, # Bypass "Requested format is not available"
        }
        
        try:
            with YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception as e:
            err_msg = traceback.format_exc()
            logger.error(f"Error extracting info for {url}: {e}\n{err_msg}")
            return {"error": str(e), "traceback": err_msg}
            
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _extract)

async def download_media(url: str, format_spec: str) -> dict:
    """Download media and return {'filepath': str|None, 'error': str|None}."""
    def _download():
        global COOKIE_FILE_DISABLED

        # 1. Primary: Use cookies + default (web) client for max quality
        primary_opts = get_base_ydl_opts()
        _apply_format_opts(primary_opts, format_spec)
        attempts = [("primary_web", primary_opts)]

        # 2. Fallback: Use cookies + android/ios clients if web is blocked (limited quality)
        if primary_opts.get("cookiefile"):
            mobile_opts = copy.deepcopy(primary_opts)
            mobile_opts["extractor_args"] = {"youtube": {"player_client": ["android", "ios"]}}
            attempts.append(("mobile_client_fallback", mobile_opts))

        # 3. Fallback: No cookies + default client
        no_cookie_opts = copy.deepcopy(primary_opts)
        no_cookie_opts.pop("cookiefile", None)
        attempts.append(("no_cookie_fallback", no_cookie_opts))

        # 4. Final Fallback: Non-specific format + no cookies
        if format_spec != "audio":
            best_fallback = copy.deepcopy(no_cookie_opts)
            best_fallback["format"] = "best"
            best_fallback.pop("merge_output_format", None)
            attempts.append(("best_fallback", best_fallback))

        attempt_errors = []

        for attempt_name, opts in attempts:
            try:
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    filepath = _resolve_output_path(info, ydl, format_spec)

                    if filepath and os.path.exists(filepath):
                        return {"filepath": filepath, "error": None}

                    missing_msg = f"{attempt_name}: yt-dlp finished but no output file was found on disk."
                    attempt_errors.append(missing_msg)
                    logger.error(f"{missing_msg} URL: {url}")
            except Exception as e:
                err_msg = traceback.format_exc()
                logger.warning(
                    f"Download attempt '{attempt_name}' failed for {url}: {e}\n{err_msg}"
                )
                if attempt_name == "primary" and opts.get("cookiefile"):
                    err_lower = str(e).lower()
                    if "sign in" in err_lower or "cookie" in err_lower:
                        COOKIE_FILE_DISABLED = True
                        logger.warning(
                            f"Disabling cookie file for subsequent downloads due to failure: {opts.get('cookiefile')}"
                        )
                attempt_errors.append(f"{attempt_name}: {e}")

        return {"filepath": None, "error": " | ".join(attempt_errors)[:1000]}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _download)
