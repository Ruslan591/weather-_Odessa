#!/usr/bin/env python3
"""icon_cyclone_case_saver.py — копилка случаев для отладки фронтов (секторная схема от центра циклона).

Раз в несколько часов смотрит самый свежий run ICON-EU ПО ВСЕЙ ОБЛАСТИ (а не по кропу very_far) и, если
внутри неё есть хорошо развитый циклон НЕ у самого края данных, сохраняет замороженный снимок сырых полей
(тот же формат, что ICON_FRONT_SAVE_TESTCASE: грузится icon_front_very_far_snapshot.load_testcase).

Ничего не публикует и не трогает git: файлы лежат на VPS вне репозитория (CASE_DIR), хранятся последние
KEEP штук. Дешёвая проверка: сначала скачивается только PMSL (+HSURF); остальные 8 полей — только если
циклон найден.

Критерий «развитого циклона»: давление в центре ≤ ICON_CASE_MAX_P И глубина ≥ ICON_CASE_MIN_DEPTH_HPA —
давление в центре минус среднее по квадрату 1500 км вокруг (одно давление в центре плохой критерий: 1012 гПа
в области высокого давления — слабая ложбина, а 1008 в низком фоне — уже циклон).

ENV: ICON_CASE_DIR, ICON_CASE_MAX_P (гПа, по умолч. 1010), ICON_CASE_MIN_DEPTH_HPA (8), ICON_CASE_EDGE_DEG (5),
     ICON_CASE_KEEP (20), ICON_CASE_FORCE=1 (игнорировать «уже проверяли этот run» и дедупликацию).
"""
import json
import math
import os
import sys
import fcntl
import time
import traceback
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import icon_front_very_far_snapshot as vf  # noqa: E402

CASE_DIR = os.environ.get("ICON_CASE_DIR", "/opt/weather-pipeline/cases")
MAX_P = float(os.environ.get("ICON_CASE_MAX_P", "1010"))
MIN_DEPTH = float(os.environ.get("ICON_CASE_MIN_DEPTH_HPA", "8"))
DEPTH_WINDOW_KM = 1500.0
EDGE_DEG = float(os.environ.get("ICON_CASE_EDGE_DEG", "5"))
KEEP = int(os.environ.get("ICON_CASE_KEEP", "20"))
FORCE = os.environ.get("ICON_CASE_FORCE") == "1"
LOCK = "/tmp/icon_cyclone_case_saver.lock"

# вся область ICON-EU regular-lat-lon (скачанные файлы — весь домен; кроп делает download_and_parse)
FULL_W, FULL_S, FULL_E, FULL_N = -23.5, 29.5, 62.5, 70.5

SPECS_REST = {
    "fi500": ("fi", "pressure-level", 500, "FI"),
    "fi1000": ("fi", "pressure-level", 1000, "FI"),
    "u850": ("u", "pressure-level", 850, "U"),
    "v850": ("v", "pressure-level", 850, "V"),
    "relhum850": ("relhum", "pressure-level", 850, "RELHUM"),
    "t850": ("t", "pressure-level", 850, "T"),
    "fr_land": ("fr_land", "time-invariant", None, "FR_LAND"),
    "fr_lake": ("fr_lake", "time-invariant", None, "FR_LAKE"),
}


def dist_deg(la1, lo1, la2, lo2):
    dx = (lo1 - lo2) * math.cos(math.radians((la1 + la2) / 2))
    return math.hypot(dx, la1 - la2)


def center_depths(pmsl, lats, lons, centers):
    """Глубина каждого L: среднее по квадрату DEPTH_WINDOW_KM минус давление в центре (гПа)."""
    import numpy as np
    from scipy.ndimage import gaussian_filter, uniform_filter
    dy_km, dx_km = vf.km_scale(lats, lons)
    p = gaussian_filter(pmsl, 5.0)
    wy = max(3, min(p.shape[0] - 1, int(round(DEPTH_WINDOW_KM / abs(dy_km))) | 1))
    wx = max(3, min(p.shape[1] - 1, int(round(DEPTH_WINDOW_KM / abs(dx_km))) | 1))
    mean = uniform_filter(p, size=(wy, wx), mode="nearest")
    out = []
    for la, lo, kind, pv in centers:
        i = int(np.argmin(np.abs(lats - la)))
        j = int(np.argmin(np.abs(lons - lo)))
        out.append(float(mean[i, j] - p[i, j]))
    return out


def load_state():
    p = os.path.join(CASE_DIR, "state.json")
    try:
        return json.load(open(p))
    except Exception:
        return {"checked_runs": [], "cases": []}


def save_state(st):
    st["checked_runs"] = st["checked_runs"][-40:]
    tmp = os.path.join(CASE_DIR, "state.json.tmp")
    json.dump(st, open(tmp, "w"), ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(CASE_DIR, "state.json"))


def fetch(key, run_dt, lead, spec):
    param_dir, level_type, level, upper = spec
    url = vf.build_url(run_dt, 0 if level_type == "time-invariant" else lead, param_dir, level_type, level, upper)
    res, meta = vf.download_and_parse(url, "case_" + key)
    if res is None:
        raise RuntimeError(f"не скачалось {key}: {meta}")
    return res


def main():
    lock = open(LOCK, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        vf.log("уже запущен — выходим")
        return
    os.makedirs(CASE_DIR, exist_ok=True)
    vf.DL_WEST, vf.DL_SOUTH, vf.DL_EAST, vf.DL_NORTH = FULL_W, FULL_S, FULL_E, FULL_N
    st = load_state()
    run_dt, lead = vf.find_latest_run_lead()
    if run_dt is None:
        vf.log("нет опубликованного run — выходим")
        return
    tag = f"{run_dt.strftime('%Y%m%d%H')}"
    vf.log(f"run={run_dt.isoformat()} lead={lead}")
    if tag in st["checked_runs"] and not FORCE:
        vf.log("этот run уже проверяли — выходим")
        return

    pmsl_g, lats, lons = fetch("pmsl", run_dt, lead, ("pmsl", "single-level", None, "PMSL"))
    pmsl = pmsl_g / 100.0
    hs_g, _, _ = fetch("hsurf", run_dt, lead, ("hsurf", "time-invariant", None, "HSURF"))
    centers = vf.find_pressure_centers(pmsl, hs_g, lats, lons)
    depths = center_depths(pmsl, lats, lons, centers)
    for c, d in zip(centers, depths):
        if c[2] == "L":
            vf.log(f"  L {c[3]:.0f} гПа на {c[0]:.1f}N {c[1]:.1f}E, глубина {d:.1f} гПа")
    ok = [c for c, d in zip(centers, depths) if c[2] == "L" and c[3] <= MAX_P and d >= MIN_DEPTH
          and FULL_S + EDGE_DEG <= c[0] <= FULL_N - EDGE_DEG and FULL_W + EDGE_DEG <= c[1] <= FULL_E - EDGE_DEG]
    vf.log(f"L-центров всего {sum(1 for c in centers if c[2]=='L')}, подходящих (≤{MAX_P:.0f} гПа, глубина ≥{MIN_DEPTH:.0f}, "
           f"≥{EDGE_DEG:.0f}° от края): {len(ok)}")
    st["checked_runs"].append(tag)
    if not ok:
        save_state(st)
        return
    best = min(ok, key=lambda c: c[3])  # самый глубокий по давлению в центре
    valid = run_dt.timestamp() + lead * 3600
    if not FORCE:
        for c in st["cases"]:
            if abs(valid - c["valid_ts"]) < 24 * 3600 and dist_deg(best[0], best[1], c["lat"], c["lon"]) < 8:
                vf.log(f"тот же циклон уже сохранён ({c['file']}) — пропускаем")
                save_state(st)
                return

    fields = {"pmsl": pmsl, "hsurf": hs_g}
    for k, spec in SPECS_REST.items():
        fields[k] = fetch(k, run_dt, lead, spec)[0]
    fname = f"case_{tag}_{lead:03d}.npz"
    path = os.path.join(CASE_DIR, fname)
    vf.save_testcase(path, fields, lats, lons, run_dt, lead)
    st["cases"].append({"file": fname, "run": run_dt.isoformat(), "lead": lead, "valid_ts": valid,
                        "lat": best[0], "lon": best[1], "p": best[3],
                        "centers": [[round(c[0], 3), round(c[1], 3), c[2], round(c[3], 1)] for c in centers],
                        "saved_utc": datetime.now(timezone.utc).isoformat()})
    while len(st["cases"]) > KEEP:
        old = st["cases"].pop(0)
        try:
            os.remove(os.path.join(CASE_DIR, old["file"]))
        except OSError:
            pass
    save_state(st)
    vf.log(f"СОХРАНЁН случай {fname}: L {best[3]:.0f} гПа на {best[0]:.1f}N {best[1]:.1f}E "
           f"({os.path.getsize(path)/1e6:.1f} МБ), всего в копилке {len(st['cases'])}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
