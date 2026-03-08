import asyncio
import copy
import glob
import os
import shutil
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

import imageio_ffmpeg
from yt_dlp import YoutubeDL

from utils.logger import logger

# Keep max workers low to save CPU (2 downloads at once)
executor = ThreadPoolExecutor(max_workers=2)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
COOKIE_FILE = os.path.join(BASE_DIR, "cookies.txt")
COOKIE_FILE_DISABLED = False
FORMAT_CACHE_TTL_SECONDS = 3600
LEGACY_FORMAT_SPECS = {"1080p", "720p", "480p"}
PREFERRED_VIDEO_EXTENSIONS = {
    "mp4": 3,
    "webm": 2,
    "mov": 1,
}
FORMAT_SELECTION_CACHE = {}

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


def _get_js_runtimes() -> dict | None:
    runtimes = {
        runtime: {}
        for runtime in ("node", "deno", "bun")
        if shutil.which(runtime)
    }
    return runtimes or None


def _apply_common_ydl_opts(opts: dict) -> dict:
    js_runtimes = _get_js_runtimes()
    if js_runtimes:
        opts["js_runtimes"] = js_runtimes
    return opts


def _purge_format_cache() -> None:
    expires_before = time.monotonic() - FORMAT_CACHE_TTL_SECONDS
    expired_keys = [
        key for key, entry in FORMAT_SELECTION_CACHE.items()
        if entry["created_at"] < expires_before
    ]
    for key in expired_keys:
        FORMAT_SELECTION_CACHE.pop(key, None)


def cache_format_options(chat_id: int, message_id: int, options: list[dict]) -> list[dict]:
    _purge_format_cache()

    cached_options = []
    option_map = {}

    for index, option in enumerate(options, start=1):
        token = "a" if option["kind"] == "audio" else f"v{index}"
        cached_option = {
            "kind": option["kind"],
            "label": option["label"],
            "selector": option["selector"],
            "log_format": option["log_format"],
            "token": token,
        }
        cached_options.append(cached_option)
        option_map[token] = cached_option

    FORMAT_SELECTION_CACHE[(chat_id, message_id)] = {
        "created_at": time.monotonic(),
        "options": option_map,
    }
    return cached_options


def get_cached_format_option(chat_id: int, message_id: int, token: str) -> dict | None:
    _purge_format_cache()
    entry = FORMAT_SELECTION_CACHE.get((chat_id, message_id))
    if not entry:
        return None
    return entry["options"].get(token)


def clear_cached_format_options(chat_id: int, message_id: int) -> None:
    FORMAT_SELECTION_CACHE.pop((chat_id, message_id), None)


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
    if format_spec == "audio":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "128",
        }]
        return

    if format_spec == "1080p":
        opts["format"] = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
    elif format_spec == "720p":
        opts["format"] = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/bestvideo[height<=720]+bestaudio/best[height<=720]/best"
    elif format_spec == "480p":
        opts["format"] = "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/bestvideo[height<=480]+bestaudio/best[height<=480]/best"
    else:
        opts["format"] = format_spec

    opts["merge_output_format"] = "mp4"


def _should_disable_cookies(error: Exception) -> bool:
    err_lower = str(error).lower()
    return "sign in" in err_lower or "cookie" in err_lower


def _get_extraction_attempts() -> list[tuple[str, dict]]:
    opts = _apply_common_ydl_opts({
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignore_no_formats_error": True,
    })

    cookie_file = _get_cookie_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file

    attempts = [("primary_web", opts)]

    android_opts = copy.deepcopy(opts)
    android_opts.pop("cookiefile", None)
    android_opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
    attempts.append(("android_client_fallback", android_opts))

    no_cookie_opts = copy.deepcopy(opts)
    no_cookie_opts.pop("cookiefile", None)
    attempts.append(("no_cookie_fallback", no_cookie_opts))

    return attempts


def _collect_formats(info: dict) -> list[dict]:
    formats = list(info.get("formats") or [])

    if not formats:
        format_id = info.get("format_id")
        if format_id or info.get("vcodec") or info.get("acodec"):
            formats.append(info)

    return formats


def _format_resolution_label(fmt: dict) -> str:
    height = fmt.get("height")
    if height:
        return f"{int(height)}p"

    resolution = (fmt.get("resolution") or "").strip()
    if resolution and resolution.lower() != "audio only":
        return resolution

    format_note = (fmt.get("format_note") or "").strip()
    if format_note:
        return format_note

    return "Unknown"


def _build_video_label(fmt: dict) -> str:
    ext = (fmt.get("ext") or "video").upper()
    parts = [ext, _format_resolution_label(fmt)]

    fps = fmt.get("fps")
    if fps:
        rounded_fps = int(round(float(fps)))
        if rounded_fps > 30:
            parts.append(f"{rounded_fps}fps")

    dynamic_range = (fmt.get("dynamic_range") or "").strip()
    if dynamic_range and dynamic_range != "SDR":
        parts.append(dynamic_range)

    return " ".join(parts)


def _build_video_selector(fmt: dict) -> str | None:
    format_id = str(fmt.get("format_id") or "").strip()
    if not format_id:
        return None

    has_audio = fmt.get("acodec") not in (None, "none")
    if has_audio:
        return format_id

    return f"{format_id}+bestaudio/best"


def build_download_options(info: dict) -> list[dict]:
    formats = _collect_formats(info)
    best_by_label = {}

    for fmt in formats:
        if fmt.get("vcodec") in (None, "none"):
            continue

        selector = _build_video_selector(fmt)
        if not selector:
            continue

        ext = (fmt.get("ext") or "").lower()
        option = {
            "kind": "video",
            "label": _build_video_label(fmt),
            "selector": selector,
            "log_format": _build_video_label(fmt),
            "sort_height": int(fmt.get("height") or 0),
            "sort_fps": int(round(float(fmt.get("fps") or 0))),
            "sort_ext": PREFERRED_VIDEO_EXTENSIONS.get(ext, 0),
            "sort_tbr": float(fmt.get("tbr") or 0),
            "sort_has_audio": 1 if fmt.get("acodec") not in (None, "none") else 0,
        }

        current = best_by_label.get(option["label"])
        if current is None:
            best_by_label[option["label"]] = option
            continue

        current_score = (
            current["sort_height"],
            current["sort_fps"],
            current["sort_has_audio"],
            current["sort_ext"],
            current["sort_tbr"],
        )
        new_score = (
            option["sort_height"],
            option["sort_fps"],
            option["sort_has_audio"],
            option["sort_ext"],
            option["sort_tbr"],
        )
        if new_score > current_score:
            best_by_label[option["label"]] = option

    video_options = sorted(
        best_by_label.values(),
        key=lambda option: (
            -option["sort_height"],
            -option["sort_fps"],
            -option["sort_has_audio"],
            -option["sort_ext"],
            -option["sort_tbr"],
            option["label"],
        ),
    )

    normalized_video_options = [
        {
            "kind": option["kind"],
            "label": option["label"],
            "selector": option["selector"],
            "log_format": option["log_format"],
        }
        for option in video_options
    ]

    normalized_video_options.append({
        "kind": "audio",
        "label": "Audio (MP3)",
        "selector": "audio",
        "log_format": "audio",
    })

    return normalized_video_options


def _count_video_options(info: dict) -> int:
    return sum(1 for option in build_download_options(info) if option["kind"] == "video")


def get_base_ydl_opts() -> dict:
    opts = _apply_common_ydl_opts({
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "retries": 3,
        "fragment_retries": 3,
        "continuedl": True,
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"%(id)s_{uuid.uuid4().hex[:8]}.%(ext)s"),
        "noplaylist": True,
        "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
    })

    cookie_file = _get_cookie_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file

    return opts


async def extract_info(url: str) -> dict:
    """Extract metadata without downloading."""

    def _extract():
        global COOKIE_FILE_DISABLED

        attempt_errors = []
        best_info = None
        best_video_count = -1
        best_format_count = -1

        for attempt_name, opts in _get_extraction_attempts():
            try:
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    video_count = _count_video_options(info)
                    format_count = len(_collect_formats(info))

                    if (
                        video_count > best_video_count
                        or (video_count == best_video_count and format_count > best_format_count)
                    ):
                        best_info = info
                        best_video_count = video_count
                        best_format_count = format_count

                    if video_count == 0:
                        logger.info(
                            f"Extraction attempt '{attempt_name}' returned no selectable video formats for {url}."
                        )
            except Exception as e:
                err_msg = traceback.format_exc()
                logger.warning(
                    f"Extraction attempt '{attempt_name}' failed for {url}: {e}\n{err_msg}"
                )
                if attempt_name == "primary_web" and opts.get("cookiefile") and _should_disable_cookies(e):
                    COOKIE_FILE_DISABLED = True
                    logger.warning(
                        f"Disabling cookie file for subsequent downloads due to failure: {opts.get('cookiefile')}"
                    )
                attempt_errors.append(f"{attempt_name}: {e}")

        if best_info is not None:
            return best_info

        return {"error": " | ".join(attempt_errors)[:1000]}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _extract)


async def download_media(url: str, format_spec: str) -> dict:
    """Download media and return {'filepath': str|None, 'error': str|None}."""

    def _download():
        global COOKIE_FILE_DISABLED

        primary_opts = get_base_ydl_opts()
        _apply_format_opts(primary_opts, format_spec)
        attempts = [("primary_web", primary_opts)]

        android_opts = copy.deepcopy(primary_opts)
        android_opts.pop("cookiefile", None)
        android_opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
        attempts.append(("android_client_fallback", android_opts))

        no_cookie_opts = copy.deepcopy(primary_opts)
        no_cookie_opts.pop("cookiefile", None)
        attempts.append(("no_cookie_fallback", no_cookie_opts))

        if format_spec not in LEGACY_FORMAT_SPECS and format_spec != "audio":
            exact_selector = True
        else:
            exact_selector = False

        if not exact_selector and format_spec != "audio":
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
                if attempt_name == "primary_web" and opts.get("cookiefile") and _should_disable_cookies(e):
                    COOKIE_FILE_DISABLED = True
                    logger.warning(
                        f"Disabling cookie file for subsequent downloads due to failure: {opts.get('cookiefile')}"
                    )
                attempt_errors.append(f"{attempt_name}: {e}")

        return {"filepath": None, "error": " | ".join(attempt_errors)[:1000]}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, _download)
