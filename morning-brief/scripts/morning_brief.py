#!/usr/bin/env python3
"""Generate a daily morning brief voice message and post to a Telegram forum topic.

Current design:
- Weather forecast: aggregate 10 forecast models/sources for Haishu, Ningbo,
  cross-check them, and build a compact consensus summary.
- RSS-AI daily report: fetch latest daily report.
- Ask the morning agent to draft a broadcast script from compact weather consensus
  + RSS report, then TTS it with local piper-http.
- Send divider text + greeting text + Telegram voice message.

This script is intended to be called by cron.
"""

import argparse
import base64
import concurrent.futures
import json
import math
import os
import random
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None

DEFAULT_MODELS = [
    "ecmwf_ifs025",
    "ecmwf_aifs025_single",
    "gfs_seamless",
    "gfs_graphcast025",
    "icon_seamless",
    "gem_seamless",
    "jma_seamless",
    "ukmo_seamless",
    "kma_seamless",
    "bom_access_global",
]

TRANSIENT_HTTP_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}
TRANSIENT_ERROR_SNIPPETS = (
    'timed out',
    'timeout',
    'too many requests',
    'temporarily unavailable',
    'connection reset',
    'connection aborted',
    'unexpected eof',
    'handshake',
    'gateway time-out',
    'gateway timeout',
)

WMO_DESC = {
    0: "晴",
    1: "基本晴",
    2: "局部多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "较强毛毛雨",
    56: "冻毛毛雨",
    57: "强冻毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "强冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "冰粒",
    80: "零星阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "零星阵雪",
    86: "阵雪",
    95: "雷阵雨",
    96: "雷阵雨伴小冰雹",
    99: "强雷暴伴冰雹",
}


def sh(args, *, timeout=180, check=True, capture=True, text=True):
    p = subprocess.run(args, timeout=timeout, check=check,
                       capture_output=capture, text=text)
    return p.stdout if text else p.stdout


def _is_transient_error(exc):
    if isinstance(exc, HTTPError):
        return exc.code in TRANSIENT_HTTP_STATUSES
    if isinstance(exc, URLError):
        msg = str(exc.reason or exc).lower()
        return any(snippet in msg for snippet in TRANSIENT_ERROR_SNIPPETS)
    msg = str(exc).lower()
    return any(snippet in msg for snippet in TRANSIENT_ERROR_SNIPPETS)


def http_json(url, *, timeout=30, method='GET', headers=None, data=None,
              retries=0, backoff=1.2):
    h = {
        'User-Agent': 'openclaw-morning-brief/2.1',
        'Accept': 'application/json',
        'Connection': 'close',
    }
    if headers:
        h.update(headers)
    if data is not None:
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
            h['Content-Type'] = 'application/json'
        elif isinstance(data, str):
            data = data.encode('utf-8')

    attempts = max(1, int(retries) + 1)
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            req = Request(url, method=method, headers=h, data=data)
            with urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode('utf-8'))
        except Exception as e:
            last_exc = e
            if attempt >= attempts or not _is_transient_error(e):
                raise
            sleep_s = backoff * (2 ** (attempt - 1)) + random.uniform(0, 0.35)
            time.sleep(sleep_s)
    raise last_exc


def now_in_tz(tz_name: str):
    if ZoneInfo is None:
        return datetime.now()
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return datetime.now()


def safe_round(x, ndigits=0):
    if x is None:
        return None
    return round(float(x), ndigits)


def safe_median(values, ndigits=0):
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return round(statistics.median(vals), ndigits)


def safe_min(values, ndigits=0):
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return round(min(vals), ndigits)


def safe_max(values, ndigits=0):
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return round(max(vals), ndigits)


def wind_dir_to_cn(deg):
    if deg is None:
        return None
    dirs = ["北", "东北偏北", "东北", "东北偏东", "东", "东南偏东", "东南", "东南偏南",
            "南", "西南偏南", "西南", "西南偏西", "西", "西北偏西", "西北", "西北偏北"]
    idx = int(((float(deg) + 11.25) % 360) / 22.5)
    return dirs[idx]


def wmo_desc_cn(code):
    try:
        return WMO_DESC.get(int(code), f"天气码{code}")
    except Exception:
        return str(code)


def wmo_category(code):
    try:
        c = int(code)
    except Exception:
        return "未知"
    if c in (0, 1):
        return "晴"
    if c == 2:
        return "多云"
    if c == 3:
        return "阴"
    if c in (45, 48):
        return "雾"
    if c in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        return "雨"
    if c in (71, 73, 75, 77, 85, 86):
        return "雪"
    if c in (95, 96, 99):
        return "雷雨"
    return "其他"


def hour_slot_label(hour):
    if hour <= 8:
        return "早间"
    if hour <= 14:
        return "午间"
    if hour <= 19:
        return "傍晚"
    return "夜间"


def fetch_openmeteo_model_forecast(latitude, longitude, timezone, model, forecast_days=2,
                                  *, retries=2, backoff=1.2):
    params = {
        'latitude': str(latitude),
        'longitude': str(longitude),
        'timezone': timezone,
        'forecast_days': str(forecast_days),
        'models': model,
        'daily': ','.join([
            'weather_code',
            'temperature_2m_max',
            'temperature_2m_min',
            'precipitation_probability_max',
            'precipitation_sum',
            'wind_speed_10m_max',
            'wind_direction_10m_dominant',
        ]),
        'hourly': ','.join([
            'temperature_2m',
            'precipitation_probability',
            'weather_code',
            'wind_speed_10m',
            'relative_humidity_2m',
        ]),
    }
    url = 'https://api.open-meteo.com/v1/forecast?' + urlencode(params)
    return http_json(url, timeout=40, retries=retries, backoff=backoff)


def find_day_index(times, target_date):
    try:
        return times.index(target_date)
    except ValueError:
        return 0 if times else None


def hourly_indices_for_date(times, target_date):
    return [i for i, t in enumerate(times or []) if str(t).startswith(target_date + 'T')]


def find_hour_index(times, target_date, target_hour):
    idxs = hourly_indices_for_date(times, target_date)
    if not idxs:
        return None
    exact = f"{target_date}T{target_hour:02d}:00"
    for i in idxs:
        if times[i] == exact:
            return i
    best = None
    best_delta = 999
    for i in idxs:
        try:
            hh = int(times[i][11:13])
        except Exception:
            continue
        d = abs(hh - target_hour)
        if d < best_delta:
            best_delta = d
            best = i
    return best


def normalize_model_forecast(model, payload, target_date):
    daily = payload.get('daily') or {}
    hourly = payload.get('hourly') or {}
    di = find_day_index(daily.get('time') or [], target_date)
    if di is None:
        raise RuntimeError(f'{model}: no daily data for {target_date}')

    daily_code = (daily.get('weather_code') or [None])[di]
    hourly_times = hourly.get('time') or []
    day_hour_idxs = hourly_indices_for_date(hourly_times, target_date)

    humidity_vals = [(hourly.get('relative_humidity_2m') or [None])[i] for i in day_hour_idxs]
    period_hours = [7, 12, 18, 21]
    periods = []
    for hh in period_hours:
        hi = find_hour_index(hourly_times, target_date, hh)
        if hi is None:
            continue
        periods.append({
            'hour': hh,
            'slot': hour_slot_label(hh),
            'temperature': (hourly.get('temperature_2m') or [None])[hi],
            'precipitation_probability': (hourly.get('precipitation_probability') or [None])[hi],
            'weather_code': (hourly.get('weather_code') or [None])[hi],
            'weather_desc': wmo_desc_cn((hourly.get('weather_code') or [None])[hi]),
            'weather_category': wmo_category((hourly.get('weather_code') or [None])[hi]),
            'wind_speed': (hourly.get('wind_speed_10m') or [None])[hi],
            'humidity': (hourly.get('relative_humidity_2m') or [None])[hi],
        })

    item = {
        'model': model,
        'weather_code': daily_code,
        'weather_desc': wmo_desc_cn(daily_code),
        'weather_category': wmo_category(daily_code),
        'temperature_max': (daily.get('temperature_2m_max') or [None])[di],
        'temperature_min': (daily.get('temperature_2m_min') or [None])[di],
        'precipitation_probability_max': (daily.get('precipitation_probability_max') or [None])[di],
        'precipitation_sum': (daily.get('precipitation_sum') or [None])[di],
        'wind_speed_max': (daily.get('wind_speed_10m_max') or [None])[di],
        'wind_direction_dominant': (daily.get('wind_direction_10m_dominant') or [None])[di],
        'humidity_min': min([h for h in humidity_vals if h is not None], default=None),
        'humidity_max': max([h for h in humidity_vals if h is not None], default=None),
        'periods': periods,
    }
    return item


def build_condition_text(category_votes, rain_support_ratio):
    if not category_votes:
        return '多云'
    most = category_votes.most_common()
    top_cat, top_n = most[0]
    second_cat, second_n = (most[1] if len(most) > 1 else (None, 0))

    if rain_support_ratio >= 0.7:
        if top_cat in ('阴', '多云', '晴'):
            return f"{top_cat}，局部有雨"
        return '有降水天气'
    if rain_support_ratio >= 0.35:
        if top_cat in ('阴', '多云', '晴'):
            return f"{top_cat}，有零星降水风险"
        return top_cat
    if top_cat in ('晴', '多云', '阴') and second_cat in ('晴', '多云', '阴') and second_n >= max(2, top_n - 1):
        pair = {top_cat, second_cat}
        if pair == {'阴', '多云'}:
            return '阴到多云'
        if pair == {'晴', '多云'}:
            return '晴到多云'
        if pair == {'晴', '阴'}:
            return '晴转阴'
    return top_cat


def build_disagreements(models, rain_support_count, tmax_span, tmin_span, category_votes):
    notes = []
    total = len(models)
    if total == 0:
        return notes
    if 0 < rain_support_count < total:
        notes.append(f"在是否下雨上存在分歧：{rain_support_count}/{total} 个来源支持有降水。")
    if tmax_span is not None and tmax_span >= 3:
        notes.append(f"最高气温判断存在一定分歧，来源区间跨度约 {tmax_span:.1f}℃。")
    if tmin_span is not None and tmin_span >= 3:
        notes.append(f"最低气温判断存在一定分歧，来源区间跨度约 {tmin_span:.1f}℃。")
    if len(category_votes) >= 3:
        notes.append("天空状况判断略有差异，但主流结论相近。")
    return notes[:3]


def build_period_consensus(models, period_hour):
    rows = []
    for m in models:
        for p in m.get('periods') or []:
            if p.get('hour') == period_hour:
                rows.append(p)
                break
    if not rows:
        return None
    cat_votes = Counter([r.get('weather_category') for r in rows if r.get('weather_category')])
    desc_votes = Counter([r.get('weather_desc') for r in rows if r.get('weather_desc')])
    return {
        'hour': period_hour,
        'slot': hour_slot_label(period_hour),
        'temperature': safe_median([r.get('temperature') for r in rows], 1),
        'precipitation_probability': safe_median([r.get('precipitation_probability') for r in rows], 0),
        'wind_speed': safe_median([r.get('wind_speed') for r in rows], 1),
        'humidity': safe_median([r.get('humidity') for r in rows], 0),
        'weather_category': (cat_votes.most_common(1)[0][0] if cat_votes else None),
        'weather_desc': (desc_votes.most_common(1)[0][0] if desc_votes else None),
    }


def fetch_weather_consensus(location_cfg, weather_cfg):
    timezone = location_cfg.get('timezone', 'Asia/Shanghai')
    target_now = now_in_tz(timezone)
    target_date = target_now.strftime('%Y-%m-%d')
    models = weather_cfg.get('models') or DEFAULT_MODELS
    workers = max(1, min(int(weather_cfg.get('parallel_workers', 3)), len(models)))
    request_retries = max(0, int(weather_cfg.get('request_retries', 2)))
    request_backoff = float(weather_cfg.get('request_backoff_seconds', 1.2))
    retry_failed_serially = bool(weather_cfg.get('retry_failed_serially', True))

    results = []
    errors = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(
                fetch_openmeteo_model_forecast,
                location_cfg['latitude'], location_cfg['longitude'], timezone, model, 2,
                retries=request_retries, backoff=request_backoff,
            ): model
            for model in models
        }
        for fut in concurrent.futures.as_completed(futs):
            model = futs[fut]
            try:
                payload = fut.result()
                results.append(normalize_model_forecast(model, payload, target_date))
            except Exception as e:
                errors[model] = str(e)

    if errors and retry_failed_serially:
        for model in list(errors.keys()):
            try:
                payload = fetch_openmeteo_model_forecast(
                    location_cfg['latitude'], location_cfg['longitude'], timezone, model, 2,
                    retries=request_retries, backoff=request_backoff,
                )
                results.append(normalize_model_forecast(model, payload, target_date))
                del errors[model]
            except Exception as e:
                errors[model] = str(e)

    results.sort(key=lambda x: models.index(x['model']) if x['model'] in models else 999)
    if not results:
        raise RuntimeError(f'weather aggregation failed: {errors}')

    category_votes = Counter([m.get('weather_category') for m in results if m.get('weather_category')])
    desc_votes = Counter([m.get('weather_desc') for m in results if m.get('weather_desc')])
    rain_support_count = 0
    for m in results:
        prob = m.get('precipitation_probability_max') or 0
        psum = m.get('precipitation_sum') or 0
        cat = m.get('weather_category')
        if prob >= 30 or psum >= 0.2 or cat in ('雨', '雷雨', '雪'):
            rain_support_count += 1
    rain_support_ratio = rain_support_count / max(1, len(results))

    tmax_vals = [m.get('temperature_max') for m in results]
    tmin_vals = [m.get('temperature_min') for m in results]
    hum_min_vals = [m.get('humidity_min') for m in results]
    hum_max_vals = [m.get('humidity_max') for m in results]
    wind_vals = [m.get('wind_speed_max') for m in results]
    wind_dir_vals = [m.get('wind_direction_dominant') for m in results]
    precip_prob_vals = [m.get('precipitation_probability_max') for m in results]
    precip_sum_vals = [m.get('precipitation_sum') for m in results]

    tmax_span = None
    if safe_min(tmax_vals, 1) is not None and safe_max(tmax_vals, 1) is not None:
        tmax_span = round(safe_max(tmax_vals, 1) - safe_min(tmax_vals, 1), 1)
    tmin_span = None
    if safe_min(tmin_vals, 1) is not None and safe_max(tmin_vals, 1) is not None:
        tmin_span = round(safe_max(tmin_vals, 1) - safe_min(tmin_vals, 1), 1)

    consensus = {
        'location': location_cfg['name'],
        'date': target_date,
        'timezone': timezone,
        'source_count_ok': len(results),
        'source_count_target': len(models),
        'sources_ok': [m['model'] for m in results],
        'sources_failed': errors,
        'condition_votes': dict(category_votes),
        'condition_desc_votes': dict(desc_votes),
        'condition_consensus': build_condition_text(category_votes, rain_support_ratio),
        'temperature': {
            'min_consensus_c': safe_median(tmin_vals, 1),
            'max_consensus_c': safe_median(tmax_vals, 1),
            'min_range_c': [safe_min(tmin_vals, 1), safe_max(tmin_vals, 1)],
            'max_range_c': [safe_min(tmax_vals, 1), safe_max(tmax_vals, 1)],
        },
        'humidity': {
            'min_consensus_pct': safe_median(hum_min_vals, 0),
            'max_consensus_pct': safe_median(hum_max_vals, 0),
            'range_pct': [safe_min(hum_min_vals, 0), safe_max(hum_max_vals, 0), safe_min(hum_max_vals, 0), safe_max(hum_max_vals, 0)],
        },
        'precipitation': {
            'support_sources': rain_support_count,
            'support_ratio': round(rain_support_ratio, 2),
            'probability_max_consensus_pct': safe_median(precip_prob_vals, 0),
            'probability_max_range_pct': [safe_min(precip_prob_vals, 0), safe_max(precip_prob_vals, 0)],
            'precipitation_sum_consensus_mm': safe_median(precip_sum_vals, 1),
            'precipitation_sum_range_mm': [safe_min(precip_sum_vals, 1), safe_max(precip_sum_vals, 1)],
        },
        'wind': {
            'speed_max_consensus_kmh': safe_median(wind_vals, 1),
            'speed_max_range_kmh': [safe_min(wind_vals, 1), safe_max(wind_vals, 1)],
            'direction_consensus': wind_dir_to_cn(safe_median(wind_dir_vals, 0)),
        },
        'periods': [p for p in [
            build_period_consensus(results, 7),
            build_period_consensus(results, 12),
            build_period_consensus(results, 18),
            build_period_consensus(results, 21),
        ] if p],
        'disagreements': build_disagreements(results, rain_support_count, tmax_span, tmin_span, category_votes),
    }
    return consensus


def compact_json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':'))


def clamp_text(text, max_chars):
    s = (text or '').strip()
    if not max_chars or len(s) <= max_chars:
        return s, False
    clipped = s[:max_chars].rstrip()
    cut = clipped.rfind('\n\n')
    if cut >= max_chars * 0.6:
        clipped = clipped[:cut].rstrip()
    return clipped, True


def fetch_rssai_daily(rssai_base_url: str):
    url = f"{rssai_base_url.rstrip('/')}/api/reports?limit=1&report_type=daily"
    j = http_json(url, timeout=30, retries=2, backoff=1.0)
    items = j.get('items', [])
    if not items:
        return None
    it = items[0]
    return it.get('title', ''), it.get('summary_text', '')


def piper_tts_to_wav(piper_url: str, text: str, speaker: str, out_wav: str, timeout=180):
    payload = {'text': text, 'speaker': speaker}
    tried = []
    for path in ['/api/tts', '/tts', '/']:
        try:
            url = piper_url.rstrip('/') + path
            req = Request(url, headers={'Content-Type': 'application/json'},
                          data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                          method='POST')
            with urlopen(req, timeout=timeout) as r:
                data = r.read()
                ct = r.headers.get('Content-Type', '')

            if data[:4] == b'RIFF':
                with open(out_wav, 'wb') as f:
                    f.write(data)
                return

            if data[:1] in (b'{', b'['):
                j = json.loads(data.decode('utf-8'))
                b64 = j.get('audio') or j.get('wav') or j.get('data')
                if b64:
                    wav = base64.b64decode(b64)
                    with open(out_wav, 'wb') as f:
                        f.write(wav)
                    return
                u = j.get('url')
                if u:
                    with urlopen(u, timeout=timeout) as r2:
                        wav = r2.read()
                    with open(out_wav, 'wb') as f:
                        f.write(wav)
                    return

            tried.append((path, ct, len(data)))
        except Exception as e:
            tried.append((path, 'ERR', str(e)))
    raise RuntimeError(f"piper-http TTS failed: {tried}")


def wav_to_ogg_opus(in_wav: str, out_ogg: str):
    sh([
        'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
        '-i', in_wav,
        '-c:a', 'libopus', '-b:a', '32k', '-vbr', 'on',
        out_ogg
    ], timeout=180)


def telegram_send_message(token: str, chat_id: int, thread_id: int, text: str, timeout=30):
    params = {
        'chat_id': str(chat_id),
        'text': text,
        'disable_web_page_preview': 'true',
    }
    if thread_id and int(thread_id) != 1:
        params['message_thread_id'] = str(thread_id)
    url = f"https://api.telegram.org/bot{token}/sendMessage?{urlencode(params)}"
    with urlopen(url, timeout=timeout) as r:
        resp = json.loads(r.read().decode('utf-8'))
    if not resp.get('ok'):
        raise RuntimeError(resp)
    return resp


def telegram_send_voice(token: str, chat_id: int, thread_id: int, ogg_path: str, caption: str = None, timeout=60):
    import uuid

    boundary = '----openclawBoundary' + uuid.uuid4().hex

    def part(name, value=None, *, filename=None, content_type=None, data=None):
        if data is None:
            data = ("" if value is None else str(value)).encode('utf-8')
        header = f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
        if filename:
            header += f'; filename="{filename}"'
        header += '\r\n'
        if content_type:
            header += f'Content-Type: {content_type}\r\n'
        header += '\r\n'
        return header.encode('utf-8') + data + b'\r\n'

    with open(ogg_path, 'rb') as f:
        voice_bytes = f.read()

    body = b''
    body += part('chat_id', chat_id)
    if thread_id and int(thread_id) != 1:
        body += part('message_thread_id', thread_id)
    body += part('voice', filename=os.path.basename(ogg_path), content_type='audio/ogg', data=voice_bytes)
    if caption:
        body += part('caption', caption)
    body += f'--{boundary}--\r\n'.encode('utf-8')

    url = f'https://api.telegram.org/bot{token}/sendVoice'
    req = Request(url, method='POST',
                  headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
                  data=body)
    with urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode('utf-8'))
    if not resp.get('ok'):
        raise RuntimeError(resp)
    return resp


def daily_session_id(prefix: str):
    day = now_in_tz('Asia/Shanghai').strftime('%Y%m%d')
    return f"{prefix}-{day}"



def build_greeting(cfg):
    assistant_cfg = cfg.get('assistant') or {}
    tz_name = ((cfg.get('location') or {}).get('timezone')) or assistant_cfg.get('timezone') or 'Asia/Shanghai'
    tz_now = now_in_tz(tz_name)
    yday = (tz_now - timedelta(days=1)).strftime('%Y-%m-%d')
    workspace_dir = assistant_cfg.get('workspace_dir') or os.environ.get('OPENCLAW_WORKSPACE', '')
    mem_text = ''
    lt_text = ''
    if workspace_dir:
        mem_path = os.path.join(workspace_dir, 'memory', f'{yday}.md')
        try:
            with open(mem_path, 'r', encoding='utf-8') as f:
                mem_text = f.read().strip()
        except FileNotFoundError:
            mem_text = ''
        lt_path = os.path.join(workspace_dir, 'MEMORY.md')
        try:
            with open(lt_path, 'r', encoding='utf-8') as f:
                lt_text = f.read().strip()
        except Exception:
            lt_text = ''

    def tail(s: str, n: int):
        return s[-n:] if s and len(s) > n else s

    user_name = (assistant_cfg.get('user_name') or '').strip()
    addressing = (
        f'- 如果要称呼，只自然称呼一次“{user_name}”，不要句首直呼，也不要以“{user_name}，”开头。'
        if user_name else
        '- 如果要称呼，只自然称呼一次，不要句首直呼。'
    )

    greet_prompt = f"""请生成一段早安问候，要求：
- 像贴心的小助手，轻轻带过即可：2-5 句。
- emoji 2-5 个（分散在句子中，不要堆满一行）。
- 允许换行：至少分成 2 段（每段 1-3 句）。
{addressing}
- 参考记忆时，请优先选择“现实生活类型”的线索：作息、出行、天气与穿衣、情绪状态、工作节奏、健康与饮食、轻量待办提醒。
- 关于服务器/配置/重启/脚本等运维内容：尽量不提；若必须提到，只能一句话轻描淡写带过，且不要出现命令、路径、参数。
- 不要复述日志细节，不要像在念记录；更不要编造没有依据的细节。

昨天的记录（仅供参考，不要逐条复述）：
{tail(mem_text, 2500) or '(无)'}

长期偏好/背景（节选，仅供参考）：
{tail(lt_text, 800) or '(无)'}

只输出问候正文，不要标题，不要列表。"""

    gr_raw = sh([
        'openclaw', 'agent', '--agent', assistant_cfg.get('agent_id', 'morning'),
        '--session-id', daily_session_id(assistant_cfg.get('greeting_session_id_prefix', 'morning-greeting')),
        '--message', greet_prompt, '--json', '--timeout', '180'
    ], timeout=220)
    gr_j = json.loads(gr_raw)
    gr_payloads = (((gr_j.get('result') or {}).get('payloads')) or [])
    greeting = (gr_payloads[0].get('text') if gr_payloads else '') or '早上好。'
    return greeting.strip()


def draft_brief(weather_consensus, rss_body, cfg):
    assistant_cfg = cfg.get('assistant') or {}
    limits = cfg.get('limits') or {}
    weather_json, weather_truncated = clamp_text(
        json.dumps(weather_consensus, ensure_ascii=False, indent=2),
        int(limits.get('weather_prompt_max_chars', 12000)),
    )
    rss_body_prompt, rss_truncated = clamp_text(
        rss_body,
        int(limits.get('rss_prompt_max_chars', 45000)),
    )
    location_name = ((cfg.get('location') or {}).get('name')) or '目标地区'
    user_name = (assistant_cfg.get('user_name') or '').strip()
    salutation_rule = (
        f'开头可自然称呼一次“{user_name}”，后续不再反复称呼。'
        if user_name else
        '开头可自然称呼一次用户，后续不再反复称呼。'
    )
    source_target = weather_consensus.get('source_count_target') or len(DEFAULT_MODELS)
    prompt = f"""你是早报Claw。请把下面两段材料整理成适合TTS的中文口播稿。

口播风格（必须遵守，央视《新闻联播》/央广新闻口吻）：
- {salutation_rule}
- 语言正式、克制、客观，短句为主；不用网络词、口头禅、夸张形容。
- 不要念任何“标题/栏目名/分隔线”，不要说“第一部分/第二部分/重点事件/一般事件/数据统计/原文”等。
- 允许使用正式承接词：例如“据汇总信息显示”“综合来看”“同时”“此外”。

内容要求：
1) 天气部分：下面给你的不是单一来源，而是“{location_name} {source_target} 个预报源/模型交叉比对后的共识结果”。
   - 必须明确按“交叉比对后的结论”来讲，不要假装来自单一来源。
   - 必须覆盖：整体天气、温度范围、体感与湿度、降水、风、通勤建议。
   - 如果存在明显分歧，要用一句话点出，例如“多个来源里多数认为傍晚有零星雨风险”。
   - 时段变化只挑关键时段来讲（早间、午间、傍晚、夜间），不要为凑数硬念表。
2) 日报部分：尽量不要改写事实与措辞，主要做口播化结构整理（合并重复、按重要性排序、去掉冗余），不做主观点评。
3) 结尾追加一句固定收尾："以上为今日早报。"
4) 输出只给最终口播稿，不要输出分析过程。

天气交叉比对结果（JSON）：
{weather_json}

RSS-AI 日报原文：
{rss_body_prompt}
"""
    if weather_truncated or rss_truncated:
        prompt += "\n\n补充说明（仅供你内部参考，不要在最终口播里说出来）："
        if weather_truncated:
            prompt += "\n- 天气 JSON 过长，已为本次生成截断到安全长度；请优先保留其中关键数值与结论。"
        if rss_truncated:
            prompt += "\n- RSS 日报原文过长，已为本次生成截断到安全长度；请优先保留已提供部分中的事实与数字。"

    raw = sh([
        'openclaw', 'agent', '--agent', assistant_cfg.get('agent_id', 'morning'),
        '--session-id', daily_session_id(assistant_cfg.get('brief_session_id_prefix', 'morning-brief')),
        '--message', prompt, '--json', '--timeout', '900'
    ], timeout=950)
    jr = json.loads(raw)
    payloads = (((jr.get('result') or {}).get('payloads')) or [])
    drafted = (payloads[0].get('text') if payloads else '') or ''
    return drafted.strip() + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    cfg = json.load(open(args.config, 'r', encoding='utf-8'))
    tg = cfg['telegram']
    src = cfg['sources']
    tts = cfg['tts']
    limits = cfg.get('limits', {})
    location = cfg.get('location') or {
        'name': '北京市东城区',
        'latitude': 39.9042,
        'longitude': 116.4074,
        'timezone': 'Asia/Shanghai',
    }
    weather_cfg = cfg.get('weather') or {}

    weather_consensus = fetch_weather_consensus(location, weather_cfg)
    print(json.dumps({
        'date': weather_consensus.get('date'),
        'ok': weather_consensus.get('source_count_ok'),
        'target': weather_consensus.get('source_count_target'),
        'sources_ok': weather_consensus.get('sources_ok'),
        'sources_failed': weather_consensus.get('sources_failed'),
    }, ensure_ascii=False), file=sys.stderr, flush=True)

    rep = fetch_rssai_daily(src['rssai_base_url'])
    rss_title, rss_body = rep if rep else ('', '')

    text = draft_brief(weather_consensus, rss_body, cfg)

    max_chars = int(limits.get('max_chars', 20000))
    if len(text) > max_chars:
        text = text[:max_chars - 30].rstrip() + "\n\n（内容过长已截断）\n"

    if args.dry_run:
        sys.stdout.write(text)
        return

    caption = "早上好｜今日早报"

    with tempfile.TemporaryDirectory() as td:
        ogg = os.path.join(td, 'out.ogg')

        chunk_chars = int(tts.get('chunk_chars', 3500))
        chunks = []
        s = text.strip() + "\n"
        while s:
            if len(s) <= chunk_chars:
                chunks.append(s)
                break
            cut = s.rfind('\n\n', 0, chunk_chars)
            if cut == -1:
                cut = s.rfind('\n', 0, chunk_chars)
            if cut == -1:
                cut = chunk_chars
            chunks.append(s[:cut].strip() + "\n")
            s = s[cut:].lstrip()

        wavs = []
        for i, ch in enumerate(chunks):
            w = os.path.join(td, f'chunk_{i:03d}.wav')
            piper_tts_to_wav(tts['base_url'], ch, tts.get('speaker', ''), w)
            wavs.append(w)

        if len(wavs) == 1:
            wav_to_ogg_opus(wavs[0], ogg)
        else:
            lst = os.path.join(td, 'concat.txt')
            with open(lst, 'w', encoding='utf-8') as f:
                for w in wavs:
                    f.write(f"file '{w}'\n")
            joined = os.path.join(td, 'joined.wav')
            sh(['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', joined], timeout=180)
            wav_to_ogg_opus(joined, ogg)

        divider = "——————————————"
        greeting = build_greeting(cfg)

        telegram_send_message(tg['bot_token'], int(tg['chat_id']), int(tg['message_thread_id']), divider)
        telegram_send_message(tg['bot_token'], int(tg['chat_id']), int(tg['message_thread_id']), greeting)
        telegram_send_voice(
            tg['bot_token'], int(tg['chat_id']), int(tg['message_thread_id']),
            ogg, caption=caption
        )

    print('OK')


if __name__ == '__main__':
    main()
