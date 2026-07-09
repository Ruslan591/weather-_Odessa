"""
marine_history.py — полная история морских наблюдений (Open-Meteo Marine + ветер/давление
над морем). Пишется на каждом прогоне облачного пайплайна (~раз в 15 мин).

Хранение: полное 15-минутное разрешение — FULL_RES_DAYS дней, старше —
прореживается до 1 записи в час (thin_old_records), чтобы файл не рос бесконечно.

Заменяет sst_compare.py (который писал только SST раз в час). Старый
data/sst_compare.json больше не используется, но не удаляется (история сохранена
миграцией в data/marine_history.json).
"""
import json, os
from datetime import datetime, timezone, timedelta
import requests

DATA_FILE = 'data/marine_history.json'
LAT, LON = 46.35, 30.90  # та же точка, что и loadMarine() в pws_page.js
FULL_RES_DAYS = 90  # полное разрешение хранится столько дней, дальше — 1 запись/час

MARINE_URL = (
    f'https://marine-api.open-meteo.com/v1/marine?latitude={LAT}&longitude={LON}'
    '&current=wave_height,wave_direction,wave_period,wave_peak_period'
    ',wind_wave_height,wind_wave_direction'
    ',swell_wave_height,swell_wave_period,swell_wave_direction'
    ',sea_surface_temperature'
    ',ocean_current_velocity,ocean_current_direction'
    '&hourly=sea_level_height_msl&timezone=auto&forecast_days=1'
)
WIND_URL = (
    f'https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}'
    '&current=wind_speed_10m,wind_gusts_10m,wind_direction_10m,surface_pressure'
    '&wind_speed_unit=ms&timezone=auto'
)


def fetch_json(url):
    try:
        r = requests.get(url, timeout=15)
        return r.json()
    except Exception as e:
        print(f'  [WARN] fetch {url[:50]}...: {e}')
        return {}


def nearest_sea_level(marine_json):
    """Ближайшее к текущему моменту значение sea_level_height_msl из hourly-блока
    (в marine API это только прогнозное/текущее поле, своей 'current' величины нет)."""
    try:
        times = marine_json.get('hourly', {}).get('time', [])
        vals  = marine_json.get('hourly', {}).get('sea_level_height_msl', [])
        if not times or not vals:
            return None
        now = datetime.now(timezone.utc)
        best_i, best_diff = 0, None
        for i, t in enumerate(times):
            try:
                tt = datetime.fromisoformat(t)
                if tt.tzinfo is None:
                    tt = tt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            diff = abs((tt - now).total_seconds())
            if best_diff is None or diff < best_diff:
                best_diff, best_i = diff, i
        return vals[best_i]
    except Exception:
        return None


def build_record():
    marine = fetch_json(MARINE_URL)
    wind   = fetch_json(WIND_URL)
    c  = marine.get('current', {}) or {}
    wc = wind.get('current', {}) or {}
    return {
        'time':           datetime.now(timezone.utc).isoformat(),
        'sst':            c.get('sea_surface_temperature'),
        'waveH':          c.get('wave_height'),
        'waveDir':        c.get('wave_direction'),
        'wavePeriod':     c.get('wave_period'),
        'wavePeakPeriod': c.get('wave_peak_period'),
        'windWaveH':      c.get('wind_wave_height'),
        'windWaveDir':    c.get('wind_wave_direction'),
        'swellH':         c.get('swell_wave_height'),
        'swellPeriod':    c.get('swell_wave_period'),
        'swellDir':       c.get('swell_wave_direction'),
        'currentV':       c.get('ocean_current_velocity'),
        'currentDir':     c.get('ocean_current_direction'),
        'seaLevel':       nearest_sea_level(marine),
        'seaWindSpeed':   wc.get('wind_speed_10m'),
        'seaWindGust':    wc.get('wind_gusts_10m'),
        'seaWindDir':     wc.get('wind_direction_10m'),
        'seaPressure':    wc.get('surface_pressure'),
    }


def thin_old_records(records, full_res_days=FULL_RES_DAYS):
    """Полное разрешение только для последних full_res_days дней; всё старше —
    оставляем максимум 1 запись в час, чтобы файл не рос бесконечно."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=full_res_days)
    recent, old = [], []
    for r in records:
        try:
            t = datetime.fromisoformat(r['time'])
        except Exception:
            recent.append(r)
            continue
        (recent if t >= cutoff else old).append(r)

    seen, thinned_old = set(), []
    for r in old:
        try:
            hk = datetime.fromisoformat(r['time']).strftime('%Y-%m-%dT%H')
        except Exception:
            hk = None
        if hk is None or hk not in seen:
            thinned_old.append(r)
            if hk:
                seen.add(hk)

    result = thinned_old + recent
    result.sort(key=lambda r: r.get('time', ''))
    return result


def main():
    data = []
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
    data.append(build_record())
    data = thin_old_records(data)
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(data[-1])


if __name__ == '__main__':
    main()
