#!/usr/bin/env python3
"""
calibrate_pws_pressure.py — автокалибровка pressureOffset PWS-станций
по совпадениям времени с SYNOP (data/synop_YYYY.txt) и BUFR (data/bufr_YYYY.json).

Сверяется давление, приведённое к уровню моря (SYNOP-группа 4ppp, BUFR-поле slp) —
та же величина, что и в pws.html/synop.js (synopLastPressure.pressure = seaPressure).

Окно сверки: ±30 мин. SYNOP/BUFR отчитываются строго по целым часам, а pws_raw.json
архивируется тоже с привязкой к целому часу (pick_hourly уже гарантирует ≤10 мин
разброс) — так что 30 мин с запасом покрывает реальную разницу.

Офсет — скользящее среднее по последним 5 сверкам на станцию (не перезапись одним
замером), чтобы шум одного момента не улетал прямиком в постоянную коррекцию.

Запуск (из check_model_runs.py, в конце main(), после check_pws_sync()):
    python3 scripts/calibrate_pws_pressure.py
"""

import os, sys, json, re, subprocess
from datetime import datetime, timezone, timedelta

BASE_DIR      = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OFFSETS_FILE  = os.path.join(BASE_DIR, "data", "pws_pressure_offsets.json")
STATIONS_JS   = os.path.join(BASE_DIR, "pws_stations.js")
WINDOW_MIN    = 30
MAX_SAMPLES   = 5
MAX_PROCESSED = 60
MAX_PER_RUN   = 4    # не более N новых сверок за один прогон — не забиваем WU API разом
REF_LOOKBACK_H = 48

os.environ.setdefault("GITHUB_TOKEN", "_local_")
sys.path.insert(0, os.path.join(BASE_DIR, "scripts"))

import pws_sync as _pws
import update as _upd
from fetch_bufr_obs import load_bufr_json


def load_offsets():
    if not os.path.exists(OFFSETS_FILE):
        data = {s["id"]: {"offset": s.get("pressureOffset", 0), "samples": [], "updatedAt": None}
                for s in _pws.PWS_STATIONS}
        data["_processedRefs"] = []
        return data
    with open(OFFSETS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("_processedRefs", [])
    for s in _pws.PWS_STATIONS:
        data.setdefault(s["id"], {"offset": s.get("pressureOffset", 0), "samples": [], "updatedAt": None})
    return data


def save_offsets(data):
    with open(OFFSETS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def collect_references(now):
    """SYNOP + BUFR отсчёты за последние REF_LOOKBACK_H часов: (ref_id, dt, seaPressure)."""
    refs = []
    year = now.year

    synop_path = os.path.join(BASE_DIR, f"data/synop_{year}.txt")
    if os.path.exists(synop_path):
        with open(synop_path, "r", encoding="utf-8") as f:
            for line in f:
                parsed = _upd.parse_synop_line(line)
                if not parsed:
                    continue
                p = parsed["obs"].get("pressure")
                if p is None:
                    continue
                try:
                    dt = datetime.strptime(parsed["synopTime"], "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                except Exception:
                    continue
                if now - dt > timedelta(hours=REF_LOOKBACK_H):
                    continue
                refs.append((f"synop:{dt.isoformat()}", dt, p))

    for rec in load_bufr_json(year):
        p = rec.get("slp")
        if p is None:
            continue
        try:
            dt = datetime.strptime(rec["dt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if now - dt > timedelta(hours=REF_LOOKBACK_H):
            continue
        refs.append((f"bufr:{dt.isoformat()}", dt, p))

    return refs


def raw_station_pressure(sid, dt, now):
    """Сырое (без офсета) давление станции sid около момента dt, в пределах WINDOW_MIN."""
    date_ymd = dt.strftime("%Y%m%d")
    is_current = date_ymd == now.strftime("%Y%m%d")
    try:
        observations = _pws.fetch_station(sid, date_ymd, is_current)
    except Exception as e:
        print(f"    {sid}: не удалось получить наблюдения ({e})")
        return None
    hourly = _pws.pick_hourly(observations)
    hk = dt.strftime("%Y-%m-%dT%H")
    for h in hourly:
        if h["hourKey"] != hk or h["pressure"] is None:
            continue
        try:
            obs_dt = datetime.strptime(h["obsTimeUtc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        if abs((obs_dt - dt).total_seconds()) <= WINDOW_MIN * 60:
            return h["pressure"]
    return None


def regenerate_stations_js(offsets):
    """Перегенерировать pws_stations.js из того же источника, что и pws_sync.py —
    чтобы браузерная копия офсетов больше не расходилась с реальной (Python)."""
    if not os.path.exists(STATIONS_JS):
        return False
    with open(STATIONS_JS, "r", encoding="utf-8") as f:
        content = f.read()

    lines = []
    for s in _pws.PWS_STATIONS:
        off = offsets.get(s["id"], {}).get("offset", s.get("pressureOffset", 0))
        lines.append(f'    {{ id: "{s["id"]}", name: "{s["name"]}",  pressureOffset: {off} }},')
    body = "var PWS_SYNC_STATIONS = [\n" + "\n".join(lines) + "\n];"

    new_content, n = re.subn(r"var PWS_SYNC_STATIONS = \[.*?\];", body, content, count=1, flags=re.S)
    if n == 0 or new_content == content:
        return False
    with open(STATIONS_JS, "w", encoding="utf-8") as f:
        f.write(new_content)
    return True


def git_commit_push(paths, message):
    subprocess.run(["git", "-C", BASE_DIR, "add"] + paths, check=True, capture_output=True)
    result = subprocess.run(
        ["git", "-C", BASE_DIR, "commit", "-m", message],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  git commit: {result.stdout.strip() or result.stderr.strip()}")
        return
    push = subprocess.run(
        ["git", "-C", BASE_DIR, "push", "--force-with-lease"],
        capture_output=True, text=True
    )
    if push.returncode == 0:
        print("  git push ✓")
    else:
        print(f"  git push ✗: {push.stderr.strip()}")


def main():
    now = datetime.now(timezone.utc)
    print(f"=== calibrate_pws_pressure.py запущен {now.isoformat()} ===")

    offsets = load_offsets()
    processed = set(offsets.get("_processedRefs", []))

    refs = collect_references(now)
    new_refs = sorted(((rid, dt, p) for rid, dt, p in refs if rid not in processed),
                       key=lambda r: r[1])

    if not new_refs:
        print("  Новых SYNOP/BUFR-отсчётов для сверки нет")
        return

    if len(new_refs) > MAX_PER_RUN:
        print(f"  Найдено {len(new_refs)} новых отсчётов, обрабатываю последние {MAX_PER_RUN} "
              f"(остальные — в следующий раз)")
    to_process = new_refs[-MAX_PER_RUN:]

    for rid, dt, ref_pressure in to_process:
        print(f"  Сверка по {rid} (эталон {ref_pressure} гПа)...")
        for s in _pws.PWS_STATIONS:
            sid = s["id"]
            raw = raw_station_pressure(sid, dt, now)
            if raw is None:
                continue
            diff = round((ref_pressure - raw) * 10) / 10
            if abs(diff) > 50:
                print(f"    {sid}: выброс diff={diff:+.1f}, пропускаю")
                continue
            entry = offsets.setdefault(
                sid, {"offset": s.get("pressureOffset", 0), "samples": [], "updatedAt": None}
            )
            entry["samples"].append({"ts": dt.isoformat(), "diff": diff})
            entry["samples"] = entry["samples"][-MAX_SAMPLES:]
            entry["offset"] = round(sum(x["diff"] for x in entry["samples"]) / len(entry["samples"]) * 10) / 10
            entry["updatedAt"] = now.isoformat()
            print(f"    {sid}: diff={diff:+.1f} → offset={entry['offset']:+.1f} "
                  f"(по {len(entry['samples'])} посл. сверкам)")
        processed.add(rid)

    offsets["_processedRefs"] = sorted(processed)[-MAX_PROCESSED:]
    save_offsets(offsets)

    changed_paths = ["data/pws_pressure_offsets.json"]
    if regenerate_stations_js(offsets):
        changed_paths.append("pws_stations.js")
        print("  💾 pws_stations.js обновлён")

    git_commit_push(changed_paths, "calibrate_pws_pressure: офсеты давления по SYNOP/BUFR")
    print("=== Готово ===")


if __name__ == "__main__":
    main()
