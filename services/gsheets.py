import asyncio
import json
import time
from datetime import datetime, timezone

import aiohttp

from utils.logger import logger

GOOGLE_SHEETS_WEBHOOK_URL = "https://script.google.com/macros/s/AKfycbxxqjurAjuHfCG3IXZJJLJs7oo9wp5OoQvF12r0nDePbUKihx21PzfYt48310qaHeZc/exec"
DEFAULT_LANGUAGE = "en"
REQUEST_TIMEOUT_SECONDS = 15
STATS_CACHE_TTL_SECONDS = 30

_USER_LANGUAGE_CACHE: dict[int, str] = {}
_KNOWN_USER_IDS: set[int] = set()
_TOTAL_DOWNLOADS_SEEN = 0
_TODAY_DOWNLOADS_SEEN = 0
_TODAY_KEY = ""
_STATS_CACHE: tuple[int, int, int] | None = None
_STATS_CACHE_AT = 0.0
_WARNED_UNSUPPORTED_ACTIONS: set[str] = set()


def _normalize_language_code(language_code: str | None) -> str:
    if not language_code:
        return DEFAULT_LANGUAGE
    normalized = language_code.strip().lower().replace("_", "-").split("-", 1)[0]
    return normalized or DEFAULT_LANGUAGE


def _today_key_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _rollover_download_day() -> None:
    global _TODAY_KEY, _TODAY_DOWNLOADS_SEEN
    key = _today_key_utc()
    if _TODAY_KEY != key:
        _TODAY_KEY = key
        _TODAY_DOWNLOADS_SEEN = 0


def _mark_user(user_id: int, language_code: str | None = None) -> None:
    _KNOWN_USER_IDS.add(int(user_id))
    if language_code:
        _USER_LANGUAGE_CACHE[int(user_id)] = _normalize_language_code(language_code)


def _record_download_seen() -> None:
    global _TOTAL_DOWNLOADS_SEEN, _TODAY_DOWNLOADS_SEEN
    _rollover_download_day()
    _TOTAL_DOWNLOADS_SEEN += 1
    _TODAY_DOWNLOADS_SEEN += 1


def _warn_once(action_name: str, message: str, *args) -> None:
    if action_name in _WARNED_UNSUPPORTED_ACTIONS:
        return
    _WARNED_UNSUPPORTED_ACTIONS.add(action_name)
    logger.warning(message, *args)


def _coerce_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _extract_language_from_response(data) -> str | None:
    containers = []
    if isinstance(data, dict):
        containers.append(data)
        for key in ("result", "data", "user"):
            nested = data.get(key)
            if isinstance(nested, dict):
                containers.append(nested)

    for container in containers:
        for key in ("language_code", "language", "lang", "default_language"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return _normalize_language_code(value)
    return None


def _extract_user_ids_from_response(data) -> list[int]:
    def _extract_from_iterable(values) -> list[int]:
        ids: list[int] = []
        if not isinstance(values, list):
            return ids
        for item in values:
            if isinstance(item, (int, float, str)):
                coerced = _coerce_int(item, default=-1)
                if coerced >= 0:
                    ids.append(coerced)
                continue
            if isinstance(item, dict):
                for key in ("user_id", "id"):
                    if key in item:
                        coerced = _coerce_int(item.get(key), default=-1)
                        if coerced >= 0:
                            ids.append(coerced)
                            break
        return ids

    candidates = []
    if isinstance(data, dict):
        candidates.extend([
            data.get("user_ids"),
            data.get("users"),
            data.get("ids"),
        ])
        for key in ("result", "data"):
            nested = data.get(key)
            if isinstance(nested, dict):
                candidates.extend([
                    nested.get("user_ids"),
                    nested.get("users"),
                    nested.get("ids"),
                ])
            else:
                candidates.append(nested)
    elif isinstance(data, list):
        candidates.append(data)

    ids: list[int] = []
    for candidate in candidates:
        ids.extend(_extract_from_iterable(candidate))
    return sorted(set(ids))


def _extract_stats_from_response(data) -> tuple[int, int, int] | None:
    if not isinstance(data, dict):
        return None

    containers = [data]
    for key in ("result", "data"):
        nested = data.get(key)
        if isinstance(nested, dict):
            containers.append(nested)

    key_sets = [
        ("total_users", "total_downloads", "today_downloads"),
        ("users_count", "downloads_count", "downloads_today"),
    ]
    for container in containers:
        for users_key, downloads_key, today_key in key_sets:
            if users_key in container or downloads_key in container or today_key in container:
                return (
                    _coerce_int(container.get(users_key)),
                    _coerce_int(container.get(downloads_key)),
                    _coerce_int(container.get(today_key)),
                )

    return None


def _is_success_status(data, allow_existing: bool = False) -> bool:
    if not isinstance(data, dict):
        return False

    status = data.get("status")
    if isinstance(status, bool):
        return status
    if isinstance(status, str):
        normalized = status.strip().lower()
        success_values = {"success", "ok", "true", "updated", "done"}
        if allow_existing:
            success_values.update({"user_already_exists", "already_exists"})
        return normalized in success_values
    return False


async def _post_webhook(payload: dict, request_name: str) -> tuple[int | None, object | None, str]:
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(GOOGLE_SHEETS_WEBHOOK_URL, json=payload) as response:
                body_text = await response.text()
                if response.status >= 400:
                    logger.warning(
                        "Google Sheets %s failed with HTTP %s: %s",
                        request_name,
                        response.status,
                        body_text[:500],
                    )
                    return response.status, None, body_text

                try:
                    parsed = json.loads(body_text) if body_text else {}
                except Exception:
                    logger.warning(
                        "Google Sheets %s returned non-JSON body: %s",
                        request_name,
                        body_text[:500],
                    )
                    return response.status, None, body_text

                return response.status, parsed, body_text
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        logger.warning("Google Sheets %s request failed: %s", request_name, exc)
        return None, None, ""
    except Exception as exc:
        logger.exception("Unexpected Google Sheets %s error: %s", request_name, exc)
        return None, None, ""


def _fallback_stats() -> tuple[int, int, int]:
    _rollover_download_day()
    return (len(_KNOWN_USER_IDS), _TOTAL_DOWNLOADS_SEEN, _TODAY_DOWNLOADS_SEEN)


async def register_user_to_sheet(user_id, first_name, language_code):
    language_code = _normalize_language_code(language_code)
    payload = {
        "action": "register_user",
        "user_id": int(user_id),
        "first_name": first_name or "",
        "language_code": language_code,
    }

    _, data, raw = await _post_webhook(payload, "register_user")
    if data is not None and _is_success_status(data, allow_existing=True):
        _mark_user(int(user_id), language_code)
        return

    if data is not None:
        logger.warning("Google Sheets register_user returned unexpected payload: %s", str(data)[:500])
        _mark_user(int(user_id), language_code)
        return

    if raw:
        logger.warning("Google Sheets register_user raw response: %s", raw[:500])


async def ensure_user_and_get_language_sheet(
    user_id: int,
    first_name: str = "",
    default_language: str = DEFAULT_LANGUAGE,
) -> str:
    default_language = _normalize_language_code(default_language)
    payload = {
        "action": "ensure_user_and_get_language",
        "user_id": int(user_id),
        "first_name": first_name or "",
        "default_language": default_language,
    }

    _, data, _ = await _post_webhook(payload, "ensure_user_and_get_language")
    if data is not None and _is_success_status(data, allow_existing=True):
        language = _extract_language_from_response(data) or _USER_LANGUAGE_CACHE.get(int(user_id)) or default_language
        _mark_user(int(user_id), language)
        return language

    # Compatibility fallback for webhook variants that only support registration.
    await register_user_to_sheet(int(user_id), first_name, default_language)
    language = _USER_LANGUAGE_CACHE.get(int(user_id)) or default_language
    _mark_user(int(user_id), language)
    return language


async def set_user_language_in_sheet(user_id: int, language_code: str) -> None:
    language_code = _normalize_language_code(language_code)
    payload = {
        "action": "set_user_language",
        "user_id": int(user_id),
        "language_code": language_code,
    }

    _, data, _ = await _post_webhook(payload, "set_user_language")
    if data is None or not _is_success_status(data, allow_existing=False):
        if data is not None:
            _warn_once(
                "set_user_language",
                "Google Sheets set_user_language returned unsupported payload: %s",
                str(data)[:500],
            )
        # Fallback: write through registration endpoint with updated language.
        await register_user_to_sheet(int(user_id), "", language_code)

    _mark_user(int(user_id), language_code)


async def log_download_to_sheet(user_id: int, link: str, format_choice: str, status: str) -> None:
    payload = {
        "action": "log_download",
        "user_id": int(user_id),
        "link": link or "",
        "format": format_choice or "",
        "status": status or "",
    }

    _, data, _ = await _post_webhook(payload, "log_download")
    if data is not None and not _is_success_status(data, allow_existing=False):
        _warn_once(
            "log_download",
            "Google Sheets log_download returned unsupported payload: %s",
            str(data)[:500],
        )

    _mark_user(int(user_id), _USER_LANGUAGE_CACHE.get(int(user_id)))
    _record_download_seen()


async def get_stats_from_sheet() -> tuple[int, int, int]:
    global _STATS_CACHE, _STATS_CACHE_AT
    now = time.monotonic()
    if _STATS_CACHE and (now - _STATS_CACHE_AT) <= STATS_CACHE_TTL_SECONDS:
        return _STATS_CACHE

    payload = {"action": "get_stats"}
    _, data, _ = await _post_webhook(payload, "get_stats")
    if data is not None and _is_success_status(data, allow_existing=False):
        parsed = _extract_stats_from_response(data)
        if parsed is not None:
            _STATS_CACHE = parsed
            _STATS_CACHE_AT = now
            return parsed

    fallback = _fallback_stats()
    _STATS_CACHE = fallback
    _STATS_CACHE_AT = now
    return fallback


async def get_all_user_ids_from_sheet() -> list[int]:
    for action_name in ("get_all_user_ids", "get_users"):
        payload = {"action": action_name}
        _, data, _ = await _post_webhook(payload, action_name)
        if data is None or not _is_success_status(data, allow_existing=False):
            continue

        user_ids = _extract_user_ids_from_response(data)
        if user_ids:
            for user_id in user_ids:
                _mark_user(user_id, _USER_LANGUAGE_CACHE.get(user_id))
            return user_ids

    return sorted(_KNOWN_USER_IDS)
