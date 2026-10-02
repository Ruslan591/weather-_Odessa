#!/usr/bin/env python3
"""icon_cyclone_case_saver.py — копилка замороженных снимков для отладки фронтов и поиска малых циклонов.

Раз в несколько часов берёт самый свежий run ICON-EU и сохраняет сырые поля (формат ICON_FRONT_SAVE_TESTCASE,
грузится icon_front_very_far_snapshot.load_testcase). Два вида случаев, оба на VPS вне репозитория (CASE_DIR):
  1) РЕГИОНАЛЬНЫЙ — всегда, кроп вокруг Чёрного моря/Одессы (REG_*), хранится последние ICON_CASE_REG_KEEP.
     Нужен, чтобы не пропустить малые циклоны над Чёрным морем с окклюзией и сильными осадками: у них давление в
     центре может быть любым (и 1013), а размер — десятки км, текущий детектор L/H (сглаживание ~30 км, окно 500 км)
     их по построению не видит, поэтому отбор по центру тут не делается вообще.
  2) СИНОПТИЧЕСКИЙ — вся область ICON-EU, если есть L с p ≤ ICON_CASE_MAX_P и глубиной ≥ ICON_CASE_MIN_DEPTH_HPA
     (глубина = среднее по квадрату 1500 км минус давление в центре), не ближе ICON_CASE_EDGE_DEG к краю. Нужен для
     отладки секторной схемы фронтов от центра циклона.

ENV: ICON_CASE_DIR, ICON_CASE_MAX_P (1015), ICON_CASE_MIN_DEPTH_HPA (4), ICON_CASE_EDGE_DEG (5), ICON_CASE_KEEP (30),
     ICON_CASE_REG_KEEP (40), ICON_CASE_FORCE=1 (игнорировать «уже проверяли run» и дедупликацию).
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
MAX_P = float(os.environ.get("ICON_CASE_MAX_P", "1015"))
MIN_DEPTH = float(os.environ.get("ICON_CASE_MIN_DEPTH_HPA", "4"))
DEPTH_WINDOW_KM = 1500.0
EDGE_DEG = float(os.environ.get("ICON_CASE_EDGE_DEG", "5"))
KEEP = int(os.environ.get("ICON_CASE_KEEP", "30"))
REG_KEEP = int(os.environ.get("ICON_CASE_REG_KEEP", "40"))
REG_W, REG_S, REG_E, REG_N = 20.0, 40.0, 44.0, 53.0   # Чёрное море + Одесса
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


def prune(st_list, keep, protect_strong=False):
    """Удаляет лишние случаи: сначала слабые (глубина <8) от старых к новым, иначе просто самые старые."""
    while len(st_list) > keep:
        weak = [c for c in st_list[:-1] if protect_strong and c.get("depth", 99) < 8]
        victim = weak[0] if weak else st_list[0]
        st_list.remove(victim)
        try:
            os.remove(os.path.join(CASE_DIR, victim["file"]))
        except OSError:
            pass


def prune(st_list, keep, protect_strong=False):
    """Удаляет лишние случаи: сначала слабые (глубина <8) от старых к новым, иначе просто самые старые."""
    while len(st_list) > keep:
        weak = [c for c in st_list[:-1] if protect_strong and c.get("depth", 99) < 8]
        victim = weak[0] if weak else st_list[0]
        st_list.remove(victim)
        try:
            os.remove(os.path.join(CASE_DIR, victim["file"]))
        except OSError:
            pass


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
    st.setdefault("regional", [])
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
    fields = {"pmsl": pmsl, "hsurf": hs_g}
    for k, spec in SPECS_REST.items():
        fields[k] = fetch(k, run_dt, lead, spec)[0]
    valid = run_dt.timestamp() + lead * 3600
    now_iso = datetime.now(timezone.utc).isoformat()

    # 1) региональный кроп — всегда
    rf, rlats, rlons = {}, None, None
    for k, v in fields.items():
        rf[k], rlats, rlons = vf.crop_to_bbox(v, lats, lons, REG_W, REG_S, REG_E, REG_N)
    rname = f"case_reg_{tag}_{lead:03d}.npz"
    vf.save_testcase(os.path.join(CASE_DIR, rname), rf, rlats, rlons, run_dt, lead)
    st["regional"] = [c for c in st["regional"] if c["file"] != rname]
    st["regional"].append({"file": rname, "run": run_dt.isoformat(), "lead": lead, "valid_ts": valid, "saved_utc": now_iso})
    prune(st["regional"], REG_KEEP)
    vf.log(f"региональный случай {rname} ({os.path.getsize(os.path.join(CASE_DIR, rname))/1e6:.1f} МБ), "
           f"в копилке региональных {len(st['regional'])}")

    # 2) синоптический — если есть развитый циклон
    centers = vf.find_pressure_centers(pmsl, hs_g, lats, lons)
    depths = center_depths(pmsl, lats, lons, centers)
    for c, d in zip(centers, depths):
        if c[2] == "L":
            vf.log(f"  L {c[3]:.0f} гПа на {c[0]:.1f}N {c[1]:.1f}E, глубина {d:.1f} гПа")
    ok = [(c, d) for c, d in zip(centers, depths) if c[2] == "L" and c[3] <= MAX_P and d >= MIN_DEPTH
          and FULL_S + EDGE_DEG <= c[0] <= FULL_N - EDGE_DEG and FULL_W + EDGE_DEG <= c[1] <= FULL_E - EDGE_DEG]
    vf.log(f"L-центров всего {sum(1 for c in centers if c[2]=='L')}, подходящих (≤{MAX_P:.0f} гПа, глубина ≥{MIN_DEPTH:.0f}, "
           f"≥{EDGE_DEG:.0f}° от края): {len(ok)}")
    st["checked_runs"].append(tag)
    if not ok:
        save_state(st)
        return
    best, best_d = max(ok, key=lambda cd: cd[1])   # самый глубокий (по глубине, а не по давлению)
    if not FORCE:
        for c in st["cases"]:
            if abs(valid - c["valid_ts"]) < 24 * 3600 and dist_deg(best[0], best[1], c["lat"], c["lon"]) < 8:
                vf.log(f"тот же циклон уже сохранён ({c['file']}) — пропускаем")
                save_state(st)
                return
    fname = f"case_{tag}_{lead:03d}.npz"
    path = os.path.join(CASE_DIR, fname)
    vf.save_testcase(path, fields, lats, lons, run_dt, lead)
    st["cases"].append({"file": fname, "run": run_dt.isoformat(), "lead": lead, "valid_ts": valid,
                        "lat": best[0], "lon": best[1], "p": best[3], "depth": best_d,
                        "centers": [[round(c[0], 3), round(c[1], 3), c[2], round(c[3], 1)] for c in centers],
                        "saved_utc": now_iso})
    prune(st["cases"], KEEP, protect_strong=True)
    save_state(st)
    vf.log(f"СОХРАНЁН синоптический случай {fname}: L {best[3]:.0f} гПа (глубина {best_d:.1f}) на {best[0]:.1f}N {best[1]:.1f}E "
           f"({os.path.getsize(path)/1e6:.1f} МБ), всего в копилке {len(st['cases'])}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
