import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from services.ytdlp_service import build_download_options, extract_info  # noqa: E402
from utils.logger import logger  # noqa: E402

logger.setLevel(logging.CRITICAL)

CONFIG_PATH = ROOT / 'bench' / 'compare_config.json'
OUT_PATH = ROOT / 'bench' / 'ytdlp_results.json'


def _extract_links(value, out):
    if value is None:
        return
    if isinstance(value, str):
        if value.startswith('http://') or value.startswith('https://'):
            out.append(value)
        return
    if isinstance(value, list):
        for item in value:
            _extract_links(item, out)
        return
    if isinstance(value, dict):
        for v in value.values():
            _extract_links(v, out)


async def _run_one(test, round_num):
    started = time.perf_counter()
    error = None
    ok = False
    media_link_sample = []
    media_link_count = 0
    format_count = 0
    video_format_count = 0
    download_option_count = 0
    title = None

    try:
        info = await asyncio.wait_for(extract_info(test['url']), timeout=90)
        if isinstance(info, dict) and 'error' not in info:
            ok = True
            title = info.get('title')
            raw_formats = info.get('formats') or []
            format_count = len(raw_formats)
            video_format_count = sum(1 for f in raw_formats if f.get('vcodec') not in (None, 'none'))
            options = build_download_options(info)
            download_option_count = len(options)

            links = []
            _extract_links(info, links)
            # Keep only direct-ish media links for a fair comparison
            direct_like = [
                u for u in links
                if any(ext in u.lower() for ext in ('.mp4', '.m4a', '.webm', '.mp3', '.m3u8', '.mpd'))
            ]
            uniq = list(dict.fromkeys(direct_like))
            media_link_count = len(uniq)
            media_link_sample = uniq[:5]
        elif isinstance(info, dict):
            error = info.get('error', 'unknown error')
        else:
            error = f'unexpected return type: {type(info).__name__}'
    except asyncio.TimeoutError:
        error = 'timeout'
    except Exception as exc:  # noqa: BLE001
        error = str(exc)

    return {
        'tool': 'ytdlp_service',
        'round': round_num,
        'id': test['id'],
        'platform': test['platform'],
        'url': test['url'],
        'ok': ok,
        'duration_ms': int((time.perf_counter() - started) * 1000),
        'media_link_count': media_link_count,
        'media_link_sample': media_link_sample,
        'format_count': format_count,
        'video_format_count': video_format_count,
        'download_option_count': download_option_count,
        'title': title,
        'error': error,
    }


async def main():
    config = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
    rows = []

    for round_num in range(1, int(config['rounds']) + 1):
        for test in config['tests']:
            row = await _run_one(test, round_num)
            rows.append(row)

    OUT_PATH.write_text(json.dumps({'generated_at': datetime.utcnow().isoformat() + 'Z', 'rows': rows}, indent=2), encoding='utf-8')
    print(f'Wrote {len(rows)} rows to {OUT_PATH}')


if __name__ == '__main__':
    asyncio.run(main())
