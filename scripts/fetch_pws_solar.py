"""
Скачивает 5-минутные наблюдения solarRad с WU за апрель 2026
для станций IODESS44, IODESS16, IODESS37.
Берёт срез HH:04 для синоптических часов (0,3,6,9,12,15,18,21).
Сохраняет в pws_solar_april2026.json
"""

import json, time, urllib.request
from datetime import date, timedelta

STATIONS = ["IODESS44", "IODESS16", "IODESS37"]
API_KEYS  = [
    "6532d6454b8aa370768e63d6ba5a832e",
    "e1f10a1e78da46f5b10a1e78da96f525",
]
SYNOP_HOURS = {0, 3, 6, 9, 12, 15, 18, 21}

def fetch_day(station, date_str, key):
    url = (f"https://api.weather.com/v2/pws/history/all"
           f"?stationId={station}&format=json&units=m"
           f"&numericPrecision=decimal&date={date_str}&apiKey={key}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

def main():
    start = date(2026, 4, 1)
    end   = date(2026, 4, 30)
    results = []  # {date, hour_utc, station, solarRad}
    key_idx = 0

    d = start
    while d <= end:
        date_str = d.strftime("%Y%m%d")
        for station in STATIONS:
            key = API_KEYS[key_idx % len(API_KEYS)]
            try:
                data = fetch_day(station, date_str, key)
                obs_list = data.get("observations", [])
                # Для каждого синоптического часа берём ближайшее наблюдение
hour_best = {}  # hh -> (abs_diff, sr)
for obs in obs_list:
    t = obs.get("obsTimeUtc", "")
    if len(t) < 16: continue
    try:
        hh = int(t[11:13])
        mm = int(t[14:16])
    except ValueError: continue
    if hh not in SYNOP_HOURS: continue
    diff = abs(mm - 4)
    if diff > 10: continue   # не дальше ±10 мин от :04
    sr = obs.get("solarRadiationHigh") or obs.get("solarRadiation")
    if sr is None: continue
    if hh not in hour_best or diff < hour_best[hh][0]:
        hour_best[hh] = (diff, float(sr))

for hh, (_, sr) in hour_best.items():
    results.append({
        "date":     d.isoformat(),
        "hourUtc":  hh,
        "station":  station,
        "solarRad": sr
    })
                print(f"  {date_str} {station}: {len([r for r in results if r['date']==d.isoformat() and r['station']==station])} записей")
            except Exception as e:
                print(f"  ОШИБКА {date_str} {station}: {e}")
            key_idx += 1
            time.sleep(0.5)
        d += timedelta(days=1)

    with open("data/pws/pws_solar_april2026.json", "w") as f:
        json.dump(results, f)
    print(f"\nГотово: {len(results)} записей → pws_solar_april2026.json")

if __name__ == "__main__":
    main()
