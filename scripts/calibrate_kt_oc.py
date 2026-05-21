"""
Калибровка kt_oc по реальным данным:
  - data/synop_2026.txt          → N (октавы), время UTC
  - data/pws/pws_solar_april2026.json → solarRad PWS
Одесса: lat=46.477, lon=30.733
Запуск: cd /storage/emulated/0/Documents/weather
python3 scripts/calibrate_kt_oc.py IODESS16
"""

import json, math, re, statistics
from datetime import datetime, timezone
from collections import defaultdict

LAT = 46.477
LON = 30.733

def solar_elevation(dt_utc):
    jd  = dt_utc.timestamp() / 86400 + 2440587.5
    n   = jd - 2451545.0
    L   = (280.46 + 0.9856474 * n) % 360
    g   = math.radians((357.528 + 0.9856003 * n) % 360)
    lam = math.radians(L + 1.915 * math.sin(g) + 0.020 * math.sin(2*g))
    eps = math.radians(23.439 - 0.0000004 * n)
    ra  = math.atan2(math.cos(eps)*math.sin(lam), math.cos(lam))
    dec = math.asin(math.sin(eps)*math.sin(lam))
    gmst = (6.697375 + 0.0657098242 * n + dt_utc.hour +
            dt_utc.minute/60 + dt_utc.second/3600) % 24
    ha  = math.radians((gmst * 15 + LON - math.degrees(ra)) % 360)
    lat = math.radians(LAT)
    sin_elev = (math.sin(lat)*math.sin(dec) +
                math.cos(lat)*math.cos(dec)*math.cos(ha))
    return math.degrees(math.asin(max(-1, min(1, sin_elev))))

def clearsky(elev_deg):
    if elev_deg <= 0: return 0
    sin_e = math.sin(math.radians(elev_deg))
    am    = 1 / (sin_e + 0.50572 * (elev_deg + 6.07995)**-1.6364)
    return 1361 * (0.7 ** (am**0.678)) * sin_e

def parse_synop(pattern):
    """→ dict { "YYYY-MM-DD|HH" : N }"""
    import glob
    files = glob.glob(pattern)
    print(f"SYNOP файлов загружено: {len(files)}: {[f.split('/')[-1] for f in sorted(files)]}")
    records = {}
    for path in sorted(files):
      with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            parts = line.split(",", 6)
            if len(parts) < 7: continue
            try:
                yr,mo,dd,hh = int(parts[1]),int(parts[2]),int(parts[3]),int(parts[4])
            except ValueError: continue
            telegram = parts[6]
            m = re.search(r"33837\s+[\d\/]{5}\s+([\d\/])", telegram)
            if not m: continue
            n_str = m.group(1)
            if n_str in ("/","9"): continue
            key = f"{yr:04d}-{mo:02d}-{dd:02d}|{hh:02d}"
            records[key] = int(n_str)
    return records

def load_pws(pattern):
    """→ dict { "YYYY-MM-DD|HH" : [sr, ...] }"""
    import glob
    files = glob.glob(pattern)
    if not files:
        print(f"PWS файлы не найдены: {pattern}")
    buckets = defaultdict(list)
    for path in files:
        with open(path) as f:
            data = json.load(f)
        for rec in data:
            key = f"{rec['date']}|{rec['hourUtc']:02d}"
            buckets[key].append(rec["solarRad"])
    print(f"PWS файлов загружено: {len(files)}")
    return buckets

def build_table(pairs):
    """pairs = [(elev, N, kt), ...]  →  (table, stats)"""
    bin_edges = list(range(8, 91, 5))
    data = defaultdict(lambda: defaultdict(list))
    for elev, N, kt in pairs:
        b = max(e for e in bin_edges if e <= elev)
        data[b][N].append(kt)
    table = {}
    stats = []
    for b in sorted(data.keys()):
        row = {}
        for N in sorted(data[b].keys()):
            vals = sorted(data[b][N])
            if len(vals) < 5: continue
            med = statistics.median(vals)
            p25 = vals[int(len(vals) * 0.25)]
            p75 = vals[int(len(vals) * 0.75)]
            row[N] = round(med, 3)
            stats.append((b, N, len(vals), round(med, 3), round(p25, 3), round(p75, 3)))
        if row:
            table[b] = row
    return table, stats

def save_table(table, stats, path):
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(table, f)
    csv_path = path.replace(".json", "_stats.csv")
    with open(csv_path, "w") as f:
        f.write("elev,N,count,median,p25,p75\n")
        for row in stats:
            f.write(",".join(str(x) for x in row) + "\n")
    print(f"  → {path}  ({len(table)} бинов)")
    print(f"  → {csv_path}  ({len(stats)} строк)")

WARM_MONTHS = {4, 5, 6, 7, 8, 9}

# Конфиг станций для общей таблицы: station → функция-фильтр пар
# filter(elev, month, N) → True = включить, False = исключить
COMBINED_STATIONS = {
    "IODESS35": lambda elev, month, N: True,
    "IODESS16": lambda elev, month, N: not (month in WARM_MONTHS and 25 <= elev < 30),
    "IODESS37": lambda elev, month, N: elev >= 18,
    "IKRASN91": lambda elev, month, N: True,
}

def collect_pairs(synop, station, filter_fn):
    """Собирает пары (elev, N, kt, month, year) для одной станции."""
    pws = load_pws(f"data/pws/stations/{station}/pws_solar_*.json")
    pairs = []
    for key, N in synop.items():
        sr_list = pws.get(key)
        if not sr_list: continue
        date_str, hh_str = key.split("|")
        dt = datetime.fromisoformat(f"{date_str}T{hh_str}:00:00+00:00")
        elev = solar_elevation(dt)
        if elev < 8: continue
        cs = clearsky(elev)
        if cs < 30: continue
        sr = statistics.median(sr_list)
        kt = sr / cs
        if not (0 <= kt <= 1.1): continue
        month = dt.month
        year  = dt.year
        if not filter_fn(elev, month, N): continue
        pairs.append((elev, N, kt, month, year))
    print(f"  {station}: {len(pairs)} пар")
    return pairs

def main():
    import os, sys

    synop = parse_synop("data/synop_*.txt")

    # Режим одной станции
    if len(sys.argv) > 1:
        station = sys.argv[1]
        base = f"data/pws/stations/{station}"
        pairs_raw = collect_pairs(synop, station, lambda e, m, n: True)
        pairs_all      = [(e, n, kt) for e, n, kt, mo, yr in pairs_raw]
        pairs_seasonal = {"warm": [], "cold": []}
        pairs_monthly  = defaultdict(list)
        pairs_yearly   = defaultdict(list)
        for e, n, kt, mo, yr in pairs_raw:
            season = "warm" if mo in WARM_MONTHS else "cold"
            pairs_seasonal[season].append((e, n, kt))
            pairs_monthly[mo].append((e, n, kt))
            pairs_yearly[yr].append((e, n, kt))
        save_table(*build_table(pairs_all),      f"{base}/kt_oc_table.json")
        for s, p in pairs_seasonal.items():
            save_table(*build_table(p), f"{base}/seasonal/kt_oc_table_{s}.json")
        for mo, p in pairs_monthly.items():
            save_table(*build_table(p), f"{base}/monthly/kt_oc_table_{mo:02d}.json")
        for yr, p in pairs_yearly.items():
            save_table(*build_table(p), f"{base}/yearly/kt_oc_table_{yr}.json")
        return

    # Режим общей таблицы
    print("\n=== Общая таблица ===")
    base = "data/pws/combined"
    all_pairs = []
    for station, filter_fn in COMBINED_STATIONS.items():
        all_pairs.extend(collect_pairs(synop, station, filter_fn))

    print(f"Итого пар: {len(all_pairs)}\n")

    pairs_all      = [(e, n, kt) for e, n, kt, mo, yr in all_pairs]
    pairs_seasonal = {"warm": [], "cold": []}
    pairs_monthly  = defaultdict(list)
    pairs_yearly   = defaultdict(list)
    for e, n, kt, mo, yr in all_pairs:
        season = "warm" if mo in WARM_MONTHS else "cold"
        pairs_seasonal[season].append((e, n, kt))
        pairs_monthly[mo].append((e, n, kt))
        pairs_yearly[yr].append((e, n, kt))

    save_table(*build_table(pairs_all),      f"{base}/kt_oc_table.json")
    for s, p in pairs_seasonal.items():
        save_table(*build_table(p), f"{base}/seasonal/kt_oc_table_{s}.json")
    for mo, p in pairs_monthly.items():
        save_table(*build_table(p), f"{base}/monthly/kt_oc_table_{mo:02d}.json")
    for yr, p in pairs_yearly.items():
        save_table(*build_table(p), f"{base}/yearly/kt_oc_table_{yr}.json")

if __name__ == "__main__":
    main()