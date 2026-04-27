import asyncio
import base64
import copy
import glob
import json
import os
import shutil
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

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
ANALYSIS_CACHE_LOCK = threading.Lock()


def reset_analysis_cache() -> None:
    """Clear in-memory URL analysis cache (e.g. after deploy)."""
    with ANALYSIS_CACHE_LOCK:
        ANALYSIS_CACHE.clear()


def log_cookie_configuration() -> None:
    """Log whether YouTube cookie authentication is configured — critical on cloud IPs."""
    env_path = os.getenv("YTDLP_COOKIEFILE", "").strip()
    project_cookie = COOKIE_FILE
    if env_path:
        if os.path.isfile(env_path):
            logger.info("YTDLP_COOKIEFILE is set and readable: %s", env_path)
        else:
            logger.warning(
                "YTDLP_COOKIEFILE points to a missing or unreadable path (%s). "
                "YouTube downloads will fail with “bot” errors until this file exists on disk.",
                env_path,
            )
    elif os.path.isfile(project_cookie):
        logger.info("Using bundled cookies file at %s", project_cookie)
    else:
        logger.warning(
            "No cookie file configured (set YTDLP_COOKIEFILE or add cookies.txt). "
            "YouTube often blocks datacenter IPs unless you pass Netscape cookies from a logged-in browser."
        )
# Telegram's maximum upload size via the client API (MTProto).  Files larger
# than this cannot be sent and should be rejected before we waste bandwidth.
MAX_FILESIZE_BYTES = 2000 * 1024 * 1024  # 2000 MiB ≈ Telegram client-API limit
SOCKET_TIMEOUT_SECONDS = 120
BTCH_BACKEND_BASE_URL = os.getenv("BTCH_BACKEND_BASE_URL", "https://backend1.tioo.eu.org").rstrip("/")
DIRECT_SELECTOR_PREFIX = "direct:"
_DIRECT_DOWNLOAD_CHUNK_BYTES = 256 * 1024

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
    with ANALYSIS_CACHE_LOCK:
        _purge_analysis_cache_locked()


def _purge_analysis_cache_locked() -> None:
    expires_before = time.monotonic() - ANALYSIS_CACHE_TTL_SECONDS
    expired_keys = [
        key for key, entry in ANALYSIS_CACHE.items()
        if entry["created_at"] < expires_before
    ]
    for key in expired_keys:
        ANALYSIS_CACHE.pop(key, None)


def get_cached_analysis(url: str) -> dict | None:
    with ANALYSIS_CACHE_LOCK:
        _purge_analysis_cache_locked()
        entry = ANALYSIS_CACHE.get(url)
    if not entry:
        return None
    return entry["info"]


def cache_analysis(url: str, info: dict) -> None:
    with ANALYSIS_CACHE_LOCK:
        _purge_analysis_cache_locked()
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


def _is_youtube_url(url: str) -> bool:
    try:
        host = (urlparse(url).netloc or "").lower()
    except Exception:
        return False

    if host.startswith("www."):
        host = host[4:]

    return (
        host == "youtu.be"
        or host.endswith("youtube.com")
        or host.endswith("youtube-nocookie.com")
    )


def _ensure_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _infer_media_kind_from_url(media_url: str) -> str:
    path = (urlparse(media_url).path or "").lower()
    _, ext = os.path.splitext(path)
    if ext in {".mp3", ".m4a", ".aac", ".ogg", ".wav", ".flac"}:
        return "audio"
    if ext in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        return "image"
    return "video"


def _is_http_url(value) -> bool:
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _encode_direct_selector(media_url: str, kind: str) -> str:
    payload = json.dumps({"url": media_url, "kind": kind}, separators=(",", ":")).encode("utf-8")
    encoded = base64.urlsafe_b64encode(payload).decode("ascii")
    return f"{DIRECT_SELECTOR_PREFIX}{encoded}"


def _decode_direct_selector(selector: str) -> dict | None:
    if not selector or not selector.startswith(DIRECT_SELECTOR_PREFIX):
        return None
    encoded = selector[len(DIRECT_SELECTOR_PREFIX):]
    try:
        payload = base64.urlsafe_b64decode(encoded.encode("ascii"))
        parsed = json.loads(payload.decode("utf-8"))
    except Exception:
        return None

    media_url = parsed.get("url")
    kind = parsed.get("kind") or "video"
    if not isinstance(media_url, str) or not media_url.startswith(("http://", "https://")):
        return None
    return {"url": media_url, "kind": kind}


def _guess_extension_from_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None

    normalized = content_type.split(";", 1)[0].strip().lower()
    mapping = {
        "video/mp4": ".mp4",
        "video/webm": ".webm",
        "video/quicktime": ".mov",
        "video/x-matroska": ".mkv",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/mp4": ".m4a",
        "audio/aac": ".aac",
        "audio/ogg": ".ogg",
        "audio/wav": ".wav",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    return mapping.get(normalized)


def _guess_extension_from_url(media_url: str) -> str | None:
    ext = os.path.splitext((urlparse(media_url).path or "").lower())[1]
    if ext in {
        ".mp4",
        ".webm",
        ".mov",
        ".mkv",
        ".mp3",
        ".m4a",
        ".aac",
        ".ogg",
        ".wav",
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
    }:
        return ".jpg" if ext == ".jpeg" else ext
    return None


def _download_direct_media(selection: dict, source_url: str) -> dict:
    media_url = selection["url"]
    media_kind = selection.get("kind") or "video"
    request = Request(
        media_url,
        headers={
            "User-Agent": "TelegramDownloaderBot/1.0",
            "Referer": source_url,
        },
        method="GET",
    )

    filepath = None
    try:
        with urlopen(request, timeout=SOCKET_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("Content-Type")
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > MAX_FILESIZE_BYTES:
                        return {
                            "filepath": None,
                            "thumb": None,
                            "error": "Remote media exceeds maximum allowed filesize",
                        }
                except ValueError:
                    pass

            if (content_type or "").lower().startswith("text/html"):
                return {
                    "filepath": None,
                    "thumb": None,
                    "error": "Direct media endpoint returned HTML instead of media",
                }

            extension = (
                _guess_extension_from_content_type(content_type)
                or _guess_extension_from_url(media_url)
                or (".mp3" if media_kind == "audio" else ".mp4")
            )
            filepath = os.path.join(DOWNLOAD_DIR, f"direct_{uuid.uuid4().hex[:10]}{extension}")

            downloaded = 0
            with open(filepath, "wb") as output_file:
                while True:
                    chunk = response.read(_DIRECT_DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    output_file.write(chunk)
                    downloaded += len(chunk)
                    if downloaded > MAX_FILESIZE_BYTES:
                        raise ValueError("filesize exceeds maximum allowed limit")
    except Exception as exc:
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
        return {"filepath": None, "thumb": None, "error": str(exc)}

    return {"filepath": filepath, "thumb": None, "error": None}


def _get_btch_endpoint_for_url(url: str) -> str | None:
    host = (urlparse(url).netloc or "").lower()
    if host.endswith("threads.com") or host.endswith("threads.net"):
        return "threads"
    if host.endswith("instagram.com"):
        return "igdl"
    if (
        host.endswith("tiktok.com")
        or host.endswith("vt.tiktok.com")
        or host.endswith("vm.tiktok.com")
    ):
        return "ttdl"
    if host.endswith("twitter.com") or host.endswith("x.com"):
        return "twitter"
    if host.endswith("facebook.com") or host.endswith("fb.watch"):
        return "fbdown"
    return None


def _fetch_btch_payload(endpoint: str, url: str):
    query = urlencode({"url": url})
    api_url = f"{BTCH_BACKEND_BASE_URL}/{endpoint}?{query}"
    headers = {
        "User-Agent": "TelegramDownloaderBot/1.0",
        "Accept": "application/json",
    }
    request = Request(api_url, headers=headers, method="GET")

    try:
        with urlopen(request, timeout=SOCKET_TIMEOUT_SECONDS) as response:
            payload = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning(f"BTCH fallback request failed for {url}: {exc}")
        return None

    try:
        data = json.loads(payload)
    except Exception:
        logger.warning(f"BTCH fallback returned non-JSON response for {url}")
        return None

    return data


def _append_btch_direct_option(
    options: list[dict],
    *,
    media_url: str,
    label: str,
    log_format: str,
    kind_hint: str | None = None,
) -> None:
    if not _is_http_url(media_url):
        return
    kind = kind_hint or _infer_media_kind_from_url(media_url)
    options.append({
        "kind": "audio" if kind == "audio" else "video",
        "label": label,
        "selector": _encode_direct_selector(media_url, kind),
        "log_format": log_format,
    })


def _extract_btch_direct_options(endpoint: str, payload) -> list[dict]:
    options: list[dict] = []

    if endpoint == "threads":
        if isinstance(payload, dict):
            result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
            media_url = result.get("video") or payload.get("video")
            if _is_http_url(media_url):
                kind = _infer_media_kind_from_url(media_url)
                label = "Image file" if kind == "image" else "Best quality"
                _append_btch_direct_option(
                    options,
                    media_url=media_url,
                    label=label,
                    log_format=f"btch-threads-{kind}",
                    kind_hint=kind,
                )
        return options

    if endpoint == "ttdl":
        if isinstance(payload, dict):
            for index, media_url in enumerate(_ensure_list(payload.get("video")), start=1):
                _append_btch_direct_option(
                    options,
                    media_url=media_url,
                    label=f"Video {index}",
                    log_format=f"btch-video-{index}",
                )

            for index, media_url in enumerate(_ensure_list(payload.get("audio")), start=1):
                _append_btch_direct_option(
                    options,
                    media_url=media_url,
                    label=f"Audio {index}",
                    log_format=f"btch-audio-{index}",
                    kind_hint="audio",
                )
        return options

    if endpoint == "igdl":
        media_items = []
        if isinstance(payload, list):
            media_items = payload
        elif isinstance(payload, dict):
            media_items = _ensure_list(payload.get("result") or payload.get("data"))

        for index, item in enumerate(media_items, start=1):
            media_url = item.get("url") if isinstance(item, dict) else item
            _append_btch_direct_option(
                options,
                media_url=media_url,
                label=f"Video {index}",
                log_format=f"btch-igdl-{index}",
            )
        return options

    if endpoint == "twitter":
        if isinstance(payload, dict):
            for index, media_item in enumerate(_ensure_list(payload.get("url")), start=1):
                if isinstance(media_item, dict):
                    for variant_label, media_url in (
                        ("HD", media_item.get("hd")),
                        ("SD", media_item.get("sd")),
                        ("Default", media_item.get("url")),
                    ):
                        _append_btch_direct_option(
                            options,
                            media_url=media_url,
                            label=f"{variant_label} video {index}",
                            log_format=f"btch-twitter-{variant_label.lower()}-{index}",
                        )
                else:
                    _append_btch_direct_option(
                        options,
                        media_url=media_item,
                        label=f"Video {index}",
                        log_format=f"btch-twitter-{index}",
                    )
        return options

    if endpoint == "fbdown":
        if isinstance(payload, dict):
            _append_btch_direct_option(
                options,
                media_url=payload.get("HD"),
                label="HD video",
                log_format="btch-fb-hd",
            )
            _append_btch_direct_option(
                options,
                media_url=payload.get("Normal_video"),
                label="SD video",
                log_format="btch-fb-sd",
            )

    return options


def _build_info_from_btch(url: str, endpoint: str, payload) -> dict | None:
    direct_options = _extract_btch_direct_options(endpoint, payload)
    if not direct_options:
        return None

    result = payload.get("result") if isinstance(payload, dict) and isinstance(payload.get("result"), dict) else {}
    title = (
        payload.get("title")
        if isinstance(payload, dict)
        else None
    ) or result.get("title") or "Unknown"

    duration_raw = (
        payload.get("duration")
        if isinstance(payload, dict)
        else None
    ) or result.get("duration")
    try:
        duration = int(float(duration_raw))
    except (TypeError, ValueError):
        duration = 0

    return {
        "id": f"btch_{uuid.uuid4().hex[:10]}",
        "title": title,
        "duration": max(0, duration),
        "webpage_url": url,
        "__source": "btch",
        "__direct_options": direct_options,
    }


def _is_btch_fast_fallback_error(error: Exception) -> bool:
    text = str(error).lower()
    return (
        "unsupported url" in text
        or "read timed out" in text
        or "unable to download webpage" in text
    )


def cache_format_options(chat_id: int, message_id: int, options: list[dict]) -> list[dict]:
    _purge_format_cache()

    cached_options = []
    option_map = {}
    video_count = 0
    audio_count = 0

    for option in options:
        if option["kind"] == "audio":
            audio_count += 1
            token = "a" if audio_count == 1 else f"a{audio_count}"
        else:
            video_count += 1
            token = f"v{video_count}"
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
    """Only disable the cookie file when yt-dlp indicates it is unusable — not when YouTube
    asks for login/cookies (that means we must keep trying with a valid cookie file)."""
    err_lower = str(error).lower()
    if any(
        phrase in err_lower
        for phrase in (
            "sign in to confirm",
            "not a bot",
            "pass cookies",
            "cookies-from-browser",
            "--cookies",
        )
    ):
        return False
    return any(
        phrase in err_lower
        for phrase in (
            "could not load cookies",
            "cookie file not found",
            "invalid cookies",
            "cookies are no longer valid",
            "malformed cookie",
        )
    )


def _build_web_attempts(base_opts: dict, cookie_file: str | None) -> list[tuple[str, dict]]:
    attempts: list[tuple[str, dict]] = []

    if cookie_file:
        web_with_cookie_opts = copy.deepcopy(base_opts)
        web_with_cookie_opts["cookiefile"] = cookie_file
        attempts.append(("web_with_cookies", web_with_cookie_opts))

        web_no_cookie_opts = copy.deepcopy(base_opts)
        attempts.append(("web_no_cookies", web_no_cookie_opts))
        return attempts

    attempts.append(("web_no_cookies", copy.deepcopy(base_opts)))
    return attempts


def _build_youtube_attempt_list(
    base_opts: dict,
    cookie_file: str | None,
) -> list[tuple[str, dict]]:
    """Ordered yt-dlp strategies for YouTube.

    Cloud/datacenter IPs are often served a “Sign in to confirm you’re not a bot” page.
    Cookie-based **web** attempts must run before bare mobile clients. Alternate player
    clients (tv_embedded, mweb) are tried early because they sometimes avoid that gate.
    """
    attempts: list[tuple[str, dict]] = []

    def push(name: str, player_client: list[str] | None, use_cookies: bool) -> None:
        if use_cookies and not cookie_file:
            return
        opts = copy.deepcopy(base_opts)
        if player_client is not None:
            opts["extractor_args"] = {"youtube": {"player_client": player_client}}
        else:
            opts.pop("extractor_args", None)
        if use_cookies:
            opts["cookiefile"] = cookie_file
        else:
            opts.pop("cookiefile", None)
        attempts.append((name, opts))

    if cookie_file:
        push("yt_default_with_cookies", None, True)
        push("yt_web_with_cookies", ["web"], True)
        push("yt_tv_embedded_with_cookies", ["tv_embedded"], True)
        push("yt_mweb_with_cookies", ["mweb"], True)

    push("yt_tv_embedded", ["tv_embedded"], False)
    push("yt_mweb", ["mweb"], False)
    push("yt_android", ["android"], False)
    push("yt_ios", ["ios"], False)

    if cookie_file:
        push("yt_android_with_cookies", ["android"], True)
        push("yt_ios_with_cookies", ["ios"], True)

    push("yt_web_default", ["web"], False)

    return attempts


def _get_extraction_attempts(source_url: str) -> list[tuple[str, dict]]:
    base_opts = _apply_common_ydl_opts({
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "ignore_no_formats_error": True,
    })

    cookie_file = _get_cookie_file()
    if not _is_youtube_url(source_url):
        # Non-YouTube sites should use the default extractor behavior.
        return _build_web_attempts(base_opts, cookie_file)

    return _build_youtube_attempt_list(base_opts, cookie_file)


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
    direct_options = info.get("__direct_options")
    if isinstance(direct_options, list) and direct_options:
        normalized_direct_options = []
        for option in direct_options:
            if not isinstance(option, dict):
                continue

            kind = option.get("kind")
            if kind not in {"video", "audio"}:
                continue

            label = option.get("label")
            selector = option.get("selector")
            if not isinstance(label, str) or not isinstance(selector, str):
                continue

            normalized_direct_options.append({
                "kind": kind,
                "label": label,
                "selector": selector,
                "log_format": option.get("log_format") or selector,
            })

        if normalized_direct_options:
            return normalized_direct_options

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
        btch_endpoint = _get_btch_endpoint_for_url(canonical_url)

        cached_info = get_cached_analysis(canonical_url)
        if cached_info is not None:
            return cached_info

        attempt_errors = []
        best_info = None

        for attempt_name, opts in _get_extraction_attempts(canonical_url):
            try:
                with YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(canonical_url, download=False)
                    video_count = _count_video_formats(info)

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
            except Exception as e:
                err_msg = traceback.format_exc()
                logger.warning(
                    f"Extraction attempt '{attempt_name}' failed for {url}: {e}\n{err_msg}"
                )
                if opts.get("cookiefile") and _should_disable_cookies(e):
                    with _COOKIE_FILE_LOCK:
                        _COOKIE_FILE_DISABLED = True
                    logger.warning(
                        f"Disabling cookie file for subsequent downloads due to failure: {opts.get('cookiefile')}"
                    )
                attempt_errors.append(f"{attempt_name}: {e}")
                if btch_endpoint and _is_btch_fast_fallback_error(e):
                    logger.info(
                        "Fast fallback to BTCH triggered for %s due to extraction error: %s",
                        url,
                        e,
                    )
                    break

        if btch_endpoint:
            payload = _fetch_btch_payload(btch_endpoint, canonical_url)
            fallback_info = _build_info_from_btch(canonical_url, btch_endpoint, payload or {})
            if fallback_info:
                cache_analysis(canonical_url, fallback_info)
                return fallback_info
            attempt_errors.append("btch_fallback: no downloadable media found")

        # YouTube: do not cache or present “pick quality” UI when zero video formats exist.
        # Otherwise users see buttons but every download hits the same bot/IP block.
        if _is_youtube_url(canonical_url):
            merged = " | ".join(attempt_errors).strip()
            tail = (
                "YouTube did not expose any downloadable formats from this server (typical on cloud IPs). "
                "Export Netscape-format cookies while logged into youtube.com and set YTDLP_COOKIEFILE."
            )
            payload_err = (merged + " — " + tail if merged else tail)[:1000]
            return {"error": payload_err, "__youtube_cookie_hint": True}

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

        direct_selection = _decode_direct_selector(format_spec)
        if direct_selection:
            return _download_direct_media(direct_selection, source_url=url)

        base_opts = get_base_ydl_opts()
        _apply_format_opts(base_opts, format_spec)

        attempts: list[tuple[str, dict]] = []
        no_cookie_opts: dict

        cookie_path = _get_cookie_file()

        if _is_youtube_url(url):
            attempts.extend(_build_youtube_attempt_list(base_opts, cookie_path))
            no_cookie_opts = copy.deepcopy(base_opts)
            no_cookie_opts.pop("cookiefile", None)
        elif base_opts.get("cookiefile"):
            attempts.append(("web_with_cookies", copy.deepcopy(base_opts)))
            no_cookie_opts = copy.deepcopy(base_opts)
            no_cookie_opts.pop("cookiefile", None)
            attempts.append(("web_no_cookies", no_cookie_opts))
        else:
            no_cookie_opts = copy.deepcopy(base_opts)
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
                if opts.get("cookiefile") and _should_disable_cookies(e):
                    with _COOKIE_FILE_LOCK:
                        _COOKIE_FILE_DISABLED = True
                    logger.warning(
                        f"Disabling cookie file for subsequent downloads due to failure: {opts.get('cookiefile')}"
                    )
                attempt_errors.append(f"{attempt_name}: {e}")

        return {"filepath": None, "error": " | ".join(attempt_errors)[:1000]}

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(download_executor, _download)
