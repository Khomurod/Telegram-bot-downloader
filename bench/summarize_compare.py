import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BTCH_PATH = ROOT / 'bench' / 'btch_results.json'
YTDLP_PATH = ROOT / 'bench' / 'ytdlp_results.json'
OUT_PATH = ROOT / 'bench' / 'comparison_summary.json'


def _load_rows(path):
    return json.loads(path.read_text(encoding='utf-8'))['rows']


def _safe_median(nums):
    return statistics.median(nums) if nums else None


def _safe_mean(nums):
    return sum(nums) / len(nums) if nums else None


def _tool_summary(rows):
    total = len(rows)
    ok_rows = [r for r in rows if r.get('ok')]
    fail_rows = [r for r in rows if not r.get('ok')]
    durations = [r['duration_ms'] for r in rows]
    ok_durations = [r['duration_ms'] for r in ok_rows]
    errors = Counter((r.get('error') or 'unknown') for r in fail_rows)
    return {
        'total_tests': total,
        'passed': len(ok_rows),
        'failed': len(fail_rows),
        'success_rate': (len(ok_rows) / total) if total else 0,
        'median_duration_ms': _safe_median(durations),
        'mean_duration_ms': _safe_mean(durations),
        'median_duration_ok_ms': _safe_median(ok_durations),
        'mean_duration_ok_ms': _safe_mean(ok_durations),
        'top_errors': errors.most_common(8),
    }


def _per_test(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[r['id']].append(r)

    out = {}
    for test_id, g in groups.items():
        oks = [x for x in g if x['ok']]
        durs = [x['duration_ms'] for x in g]
        out[test_id] = {
            'platform': g[0]['platform'],
            'url': g[0]['url'],
            'runs': len(g),
            'passes': len(oks),
            'success_rate': len(oks) / len(g),
            'median_duration_ms': _safe_median(durs),
            'ok_median_duration_ms': _safe_median([x['duration_ms'] for x in oks]),
            'sample_error': next((x.get('error') for x in g if not x['ok'] and x.get('error')), None),
            'median_media_link_count': _safe_median([x.get('media_link_count', 0) for x in g]),
        }
    return out


def _join_by_run(btch_rows, ytdlp_rows):
    y_map = {(r['id'], r['round']): r for r in ytdlp_rows}
    b_map = {(r['id'], r['round']): r for r in btch_rows}
    ids = sorted(set(k[0] for k in y_map) | set(k[0] for k in b_map))

    compare = {}
    for test_id in ids:
        rounds = sorted(set(r for i, r in y_map if i == test_id) | set(r for i, r in b_map if i == test_id))
        duel = []
        for rd in rounds:
            y = y_map.get((test_id, rd))
            b = b_map.get((test_id, rd))
            if not y or not b:
                continue
            duel.append({
                'round': rd,
                'btch_ok': b['ok'],
                'ytdlp_ok': y['ok'],
                'btch_duration_ms': b['duration_ms'],
                'ytdlp_duration_ms': y['duration_ms'],
                'btch_faster_by_ms': y['duration_ms'] - b['duration_ms'],
            })

        btch_win = sum(1 for x in duel if x['btch_ok'] and not x['ytdlp_ok'])
        ytdlp_win = sum(1 for x in duel if x['ytdlp_ok'] and not x['btch_ok'])
        both_ok = sum(1 for x in duel if x['btch_ok'] and x['ytdlp_ok'])
        both_fail = sum(1 for x in duel if not x['btch_ok'] and not x['ytdlp_ok'])

        compare[test_id] = {
            'rounds_compared': len(duel),
            'btch_only_successes': btch_win,
            'ytdlp_only_successes': ytdlp_win,
            'both_success': both_ok,
            'both_failed': both_fail,
            'median_btch_faster_by_ms': _safe_median([x['btch_faster_by_ms'] for x in duel]),
        }

    return compare


def main():
    btch_rows = _load_rows(BTCH_PATH)
    ytdlp_rows = _load_rows(YTDLP_PATH)

    report = {
        'tool_summaries': {
            'btch_downloader': _tool_summary(btch_rows),
            'ytdlp_service': _tool_summary(ytdlp_rows),
        },
        'per_test': {
            'btch_downloader': _per_test(btch_rows),
            'ytdlp_service': _per_test(ytdlp_rows),
        },
        'head_to_head': _join_by_run(btch_rows, ytdlp_rows),
    }

    OUT_PATH.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Wrote summary to {OUT_PATH}')


if __name__ == '__main__':
    main()
