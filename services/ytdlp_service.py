import asyncio
import copy
import glob
import os
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlparse

import imageio_ffmpeg
from yt_dlp import YoutubeDL

from utils.logger import logger

# Separate pools: extraction is I/O-bound (HTTP) so can have more workers;
# downloads are bandwidth/CPU-heavy so stay limited.
extraction_executor = ThreadPoolExecutor(max_workers=3)
download_executor = ThreadPoolExecutor(max_workers=2)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
COOKIE_FILE = os.path.join(BASE_DIR, "cookies.txt")
_COOKIE_FILE_DISABLED = False
_COOKIE_FILE_LOCK = threading.Lock()
FORMAT_CACHE_TTL_SECONDS = 3600
ANALYSIS_CACHE_TTL_SECONDS = 600
LEGACY_FORMAT_SPECS = {"1080p", "720p", "480p"}
PREFERRED_VIDEO_EXTENSIONS = {
    "mp4": 3,
    "webm": 2,
    "mov": 1,
}
FORMAT_SELECTION_CACHE = {}
ANALYSIS_CACHE = {}
# Telegram's maximum upload size via the client API (MTProto).  Files larger
# than this cannot be sent and should be rejected before we waste bandwidth.
MAX_FILESIZE_BYTES = 2000 * 1024 * 1024  # 2000 MiB ≈ Telegram client-API limit
SOCKET_TIMEOUT_SECONDS = 120

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)


def _get_cookie_file() -> str | None:
    with _COOKIE_FILE_LOCK:
        disabled = _COOKIE_FILE_DISABLED

    if disabled:
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


_JS_RUNTIMES_CACHE: dict | None = None
_JS_RUNTIMES_RESOLVED = False


def _get_js_runtimes() -> dict | None:
    global _JS_RUNTIMES_CACHE, _JS_RUNTIMES_RESOLVED
    if not _JS_RUNTIMES_RESOLVED:
        runtimes = {
            runtime: {}
            for runtime in ("node", "deno", "bun")
            if shutil.which(runtime)
        }
        _JS_RUNTIMES_CACHE = runtimes or None
        _JS_RUNTIMES_RESOLVED = True
    return _JS_RUNTIMES_CACHE


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


def _purge_analysis_cache() -> None:
    expires_before = time.monotonic() - ANALYSIS_CACHE_TTL_SECONDS
    expired_keys = [
        key for key, entry in ANALYSIS_CACHE.items()
        if entry["created_at"] < expires_before
    ]
    for key in expired_keys:
        ANALYSIS_CACHE.pop(key, None)


def get_cached_analysis(url: str) -> dict | None:
    _purge_analysis_cache()
    entry = ANALYSIS_CACHE.get(url)
    if not entry:
        return None
    return entry["info"]


def cache_analysis(url: str, info: dict) -> None:
    _purge_analysis_cache()
    ANALYSIS_CACHE[url] = {
        "created_at": time.monotonic(),
        "info": info,
    }


def _canonicalize_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()

        if host.endswith("youtu.be"):
            video_id = (parsed.path or "").strip("/")
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"

        if host.endswith("youtube.com"):
            query = parse_qs(parsed.query or "")
            video_id = (query.get("v") or [""])[0]
            if video_id:
                return f"https://www.youtube.com/watch?v={video_id}"
    except Exception:
        pass

    return url.split("#", 1)[0]


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


def get_all_cached_format_options(chat_id: int, message_id: int) -> list[dict] | None:
    _purge_format_cache()
    entry = FORMAT_SELECTION_CACHE.get((chat_id, message_id))
    if not entry:
        return None
    return list(entry["options"].values())


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


def get_video_metadata(filepath: str) -> dict:
    try:
        frame_reader = imageio_ffmpeg.read_frames(filepath)
        metadata = next(frame_reader)
        frame_reader.close()
    except Exception as e:
        logger.warning(f"Failed to read video metadata for {filepath}: {e}")
        return {}

    width, height = metadata.get("size") or metadata.get("source_size") or (0, 0)
    rotate = int(metadata.get("rotate") or 0)
    if rotate in {90, 270, -90, -270}:
        width, height = height, width

    duration = metadata.get("duration") or 0
    try:
        duration_seconds = max(0, int(round(float(duration))))
    except (TypeError, ValueError):
        duration_seconds = 0

    return {
        "width": int(width or 0),
        "height": int(height or 0),
        "duration": duration_seconds,
    }


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
    base_opts = _apply_common_ydl_opts({
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignore_no_formats_error": True,
    })

    cookie_file = _get_cookie_file()

    # Try android client FIRST — YouTube Shorts work reliably with it,
    # while the web extractor often returns 0 video formats for Shorts.
    android_opts = copy.deepcopy(base_opts)
    android_opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
    attempts = [("android_client", android_opts)]

    # iOS client as second option — another mobile client that bypasses Shorts restrictions.
    ios_opts = copy.deepcopy(base_opts)
    ios_opts["extractor_args"] = {"youtube": {"player_client": ["ios"]}}
    attempts.append(("ios_client", ios_opts))

    # Web with cookies as third — may work for non-Shorts content.
    web_opts = copy.deepcopy(base_opts)
    if cookie_file:
        web_opts["cookiefile"] = cookie_file
    attempts.append(("web_with_cookies", web_opts))

    # Web without cookies as last resort.
    web_no_cookie_opts = copy.deepcopy(base_opts)
    attempts.append(("web_no_cookies", web_no_cookie_opts))

    return attempts


def _collect_formats(info: dict) -> list[dict]:
    formats = list(info.get("formats") or [])

    if not formats:
        format_id = info.get("format_id")
        if format_id or info.get("vcodec") or info.get("acodec"):
            formats.append(info)

    return formats


def _format_resolution_label(fmt: dict, unknown_label: str = "Unknown") -> str:
    height = fmt.get("height")
    if height:
        return f"{int(height)}p"

    resolution = (fmt.get("resolution") or "").strip()
    if resolution and resolution.lower() != "audio only":
        return resolution

    format_note = (fmt.get("format_note") or "").strip()
    if format_note:
        return format_note

    return unknown_label


def _build_video_label(fmt: dict, unknown_label: str = "Unknown") -> str:
    ext = (fmt.get("ext") or "video").upper()
    parts = [ext, _format_resolution_label(fmt, unknown_label=unknown_label)]

    fps = fmt.get("fps")
    if fps:
        rounded_fps = int(round(float(fps)))
        if rounded_fps > 30:
            parts.append(f"{rounded_fps}fps")

    dynamic_range = (fmt.get("dynamic_range") or "").strip()
    if dynamic_range and dynamic_range != "SDR":
        parts.append(dynamic_range)
        
    filesize = fmt.get("filesize") or fmt.get("filesize_approx")
    if filesize:
        mb_size = filesize / (1024 * 1024)
        parts.append(f"(~{mb_size:.1f}MB)")

    return " ".join(parts)


def _build_video_selector(fmt: dict) -> str | None:
    format_id = str(fmt.get("format_id") or "").strip()
    if not format_id:
        return None

    has_audio = fmt.get("acodec") not in (None, "none")
    if has_audio:
        return format_id

    return f"{format_id}+bestaudio/best"


def build_download_options(
    info: dict,
    unknown_label: str = "Unknown",
    audio_label: str = "Audio (MP3)",
) -> list[dict]:
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
            "label": _build_video_label(fmt, unknown_label=unknown_label),
            "selector": selector,
            "log_format": _build_video_label(fmt, unknown_label=unknown_label),
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

    # Some sources (notably YouTube in certain sessions) may hide format lists
    # while still allowing direct "best" downloads. Offer a safe video fallback.
    if not normalized_video_options:
        normalized_video_options.extend([
            {
                "kind": "video",
                "label": "Best quality",
                "selector": "best",
                "log_format": "best",
            },
            {
                "kind": "video",
                "label": "Good quality",
                "selector": "720p",
                "log_format": "720p",
            },
            {
                "kind": "video",
                "label": "Low quality",
                "selector": "480p",
                "log_format": "480p",
            },
        ])

    normalized_video_options.append({
        "kind": "audio",
        "label": audio_label,
        "selector": "audio",
        "log_format": "audio",
    })

    return normalized_video_options


def _count_video_formats(info: dict) -> int:
    """Fast check: count raw formats with a video codec (no label/sort overhead)."""
    return sum(
        1 for fmt in (info.get("formats") or [])
        if fmt.get("vcodec") not in (None, "none")
    )


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
        "writethumbnail": True,
        "ffmpeg_location": imageio_ffmpeg.get_ffmpeg_exe(),
        "filesize_max": MAX_FILESIZE_BYTES,
        "socket_timeout": SOCKET_TIMEOUT_SECONDS,
    })

    cookie_file = _get_cookie_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file

    return opts


async def extract_info(url: str) -> dict:
    """Extract metadata without downloading."""

    def _extract():
        global _COOKIE_FILE_DISABLED
        canonical_url = _canonicalize_url(url)

        cached_info = get_cached_analysis(canonical_url)
        if cached_info is not None:
            return cached_info

        attempt_errors = []
        best_info = None
        best_video_count = -1
        best_format_count = -1

        for attempt_name, opts in _get_extraction_attempts():
            try:
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    video_count = _count_video_formats(info)
                    format_count = len(_collect_formats(info))

                    if video_count > 0:
                        # First client with video formats wins — return immediately.
                        cache_analysis(canonical_url, info)
                        return info

                    logger.info(
                        f"Extraction attempt '{attempt_name}' returned no selectable video formats for {url}."
                    )

                    # Track best result so far in case no attempt yields video formats.
                    has_core_metadata = bool(
                        info.get("id") and (info.get("title") or info.get("webpage_url"))
                    )
                    if has_core_metadata and best_info is None:
                        best_info = info
                        best_video_count = video_count
                        best_format_count = format_count

                    # For mobile clients, if we got core metadata but no video formats,
                    # return early — web fallbacks are unlikely to help and waste time.
                    if has_core_metadata and attempt_name in {"android_client", "ios_client"}:
                        cache_analysis(canonical_url, info)
                        return info
            except Exception as e:
                err_msg = traceback.format_exc()
                logger.warning(
                    f"Extraction attempt '{attempt_name}' failed for {url}: {e}\n{err_msg}"
                )
                if attempt_name == "primary_web" and opts.get("cookiefile") and _should_disable_cookies(e):
                    with _COOKIE_FILE_LOCK:
                        _COOKIE_FILE_DISABLED = True
                    logger.warning(
                        f"Disabling cookie file for subsequent downloads due to failure: {opts.get('cookiefile')}"
                    )
                attempt_errors.append(f"{attempt_name}: {e}")

        if best_info is not None:
            cache_analysis(canonical_url, best_info)
            return best_info

        return {"error": " | ".join(attempt_errors)[:1000]}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(extraction_executor, _extract)


async def download_media(url: str, format_spec: str) -> dict:
    """Download media and return {'filepath': str|None, 'error': str|None}"""

    def _download():
        global _COOKIE_FILE_DISABLED

        base_opts = get_base_ydl_opts()
        _apply_format_opts(base_opts, format_spec)

        # Android client first — works reliably for YouTube Shorts.
        android_opts = copy.deepcopy(base_opts)
        android_opts.pop("cookiefile", None)
        android_opts["extractor_args"] = {"youtube": {"player_client": ["android"]}}
        attempts = [("android_client", android_opts)]

        # iOS client as second option.
        ios_opts = copy.deepcopy(base_opts)
        ios_opts.pop("cookiefile", None)
        ios_opts["extractor_args"] = {"youtube": {"player_client": ["ios"]}}
        attempts.append(("ios_client", ios_opts))

        # Web with cookies third.
        attempts.append(("web_with_cookies", base_opts))

        # Web without cookies.
        no_cookie_opts = copy.deepcopy(base_opts)
        no_cookie_opts.pop("cookiefile", None)
        attempts.append(("web_no_cookies", no_cookie_opts))

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
                        thumb_path = None
                        base_name, _ = os.path.splitext(filepath)
                        # yt-dlp usually writes thumbnails with the same base name but different extensions
                        for ext in [".jpg", ".webp", ".png"]:
                            possible_thumb = base_name + ext
                            if os.path.exists(possible_thumb):
                                thumb_path = possible_thumb
                                break
                        return {"filepath": filepath, "thumb": thumb_path, "error": None}

                    missing_msg = f"{attempt_name}: yt-dlp finished but no output file was found on disk."
                    attempt_errors.append(missing_msg)
                    logger.error(f"{missing_msg} URL: {url}")
            except Exception as e:
                err_msg = traceback.format_exc()
                logger.warning(
                    f"Download attempt '{attempt_name}' failed for {url}: {e}\n{err_msg}"
                )
                if attempt_name == "web_with_cookies" and opts.get("cookiefile") and _should_disable_cookies(e):
                    with _COOKIE_FILE_LOCK:
                        _COOKIE_FILE_DISABLED = True
                    logger.warning(
                        f"Disabling cookie file for subsequent downloads due to failure: {opts.get('cookiefile')}"
                    )
                attempt_errors.append(f"{attempt_name}: {e}")

        return {"filepath": None, "error": " | ".join(attempt_errors)[:1000]}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(download_executor, _download)
