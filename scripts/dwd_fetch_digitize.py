#!/usr/bin/env python3
"""Скачивает карты DWD с opendata.dwd.de, оцифровывает фронты и кладёт GeoJSON в репо (data/dwd_fronts/).
Запуск по cron (идемпотентно): анализ ana_bwkman_dwdna (00/06/12/18Z) + прогноз ico_tkb_na последнего прогона.
PNG остаются только на VPS (/opt/dwd-fronts/cache, 7 суток); в репо идут лишь небольшие GeoJSON через GitHub API
(рабочую копию репо и git-блокировки не трогаем)."""
import os, re, sys, json, base64, urllib.request, urllib.parse, urllib.error, time
from datetime import datetime, timedelta, timezone
BASE = os.environ.get("DWD_BASE", "/opt/dwd-fronts")
CACHE = os.path.join(BASE, "cache"); STATE = os.path.join(BASE, "state.json")
TOKEN_FILE = os.environ.get("DWD_TOKEN_FILE", "/etc/vps-github-bridge/token")
REPO = "ruslan591/weather-_Odessa"; API = "https://api.github.com/repos/%s/contents/" % REPO
FC = "https://opendata.dwd.de/weather/charts/forecasts/icon/global/na/"
AN = "https://opendata.dwd.de/weather/charts/analysis/"
UA = {"User-Agent": "weather-odessa-research/1.0"}
KEEP_DAYS = 7
def log(*a): print(datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"), *a, flush=True)
def http(url, data=None, headers=None, method=None, timeout=180):
    req = urllib.request.Request(url, data=data, headers=dict(UA, **(headers or {})), method=method)
    return urllib.request.urlopen(req, timeout=timeout).read()
def read_token():
    raw = open(TOKEN_FILE).read().strip(); tok = None
    for l in raw.splitlines():
        l = l.strip()
        if l.startswith("GITHUB_TOKEN="): tok = l.split("=", 1)[1].strip().strip("\"'")
    return tok or raw
TOK = None
def gh(): return {"Authorization": "token " + TOK, "Accept": "application/vnd.github+json"}
def gh_put(path, text, msg):
    sha = None
    try: sha = json.loads(http(API + path + "?ref=main", headers=gh()))["sha"]
    except urllib.error.HTTPError as e:
        if e.code != 404: raise
    body = {"message": msg, "content": base64.b64encode(text.encode()).decode(), "branch": "main"}
    if sha: body["sha"] = sha
    r = json.loads(http(API + path, data=json.dumps(body).encode(), headers=dict(gh(), **{"Content-Type": "application/json"}), method="PUT"))
    return r["commit"]["sha"][:8]
def refresh_digitizer():
    """свежая версия оцифровщика из репо (если GitHub недоступен — работаем со старой копией)"""
    try:
        txt = http(API + "scripts/dwd_fronts_digitize.py?ref=main", headers={"Authorization": "token " + TOK, "Accept": "application/vnd.github.raw"}).decode()
        compile(txt, "dwd_fronts_digitize.py", "exec")
        open(os.path.join(BASE, "dwd_fronts_digitize.py"), "w").write(txt)
    except Exception as e:
        log("оцифровщик не обновлён:", repr(e))
def listing(url):
    html = http(url).decode("utf-8", "replace")
    return [urllib.parse.unquote(x) for x in re.findall(r'href="([^"]+)"', html)]
def load_state():
    try: return set(json.load(open(STATE)))
    except Exception: return set()
def process(base, name, tag, valid, st, D):
    if tag in st: return
    os.makedirs(CACHE, exist_ok=True); png = os.path.join(CACHE, tag + ".png")
    open(png, "wb").write(http(base + urllib.parse.quote(name)))
    t0 = time.time(); fc, _ = D.digitize(png)
    fc["properties"].update({"valid_time": valid, "src": name})
    c = gh_put("data/dwd_fronts/%s.geojson" % tag, json.dumps(fc, separators=(",", ":")), "dwd_fronts: " + tag)
    st.add(tag); json.dump(sorted(st), open(STATE, "w"))
    log("OK", tag, "valid", valid, "отрезков", len(fc["features"]), "%.0f c" % (time.time() - t0), "commit", c)
def main():
    global TOK
    os.makedirs(BASE, exist_ok=True); TOK = read_token(); refresh_digitizer()
    sys.path.insert(0, BASE); import dwd_fronts_digitize as D
    st = load_state()
    try:
        pat = re.compile(r"ana_bwkman_dwdna_O_000000_000000_(\d{12})_WV12\.png$")
        found = sorted((m.group(1), n) for n in listing(AN) for m in [pat.search(n)] if m)
        for d, n in found[-8:]:
            valid = datetime.strptime(d, "%Y%m%d%H%M").replace(tzinfo=timezone.utc).isoformat()
            try: process(AN, n, "ana_" + d[:10], valid, st, D)
            except Exception as e: log("FAIL ana", d, repr(e))
    except Exception as e: log("анализ: ошибка листинга", repr(e))
    try:
        pat = re.compile(r"ico_tkb_na_N_(\d{6})_000000_(\d{12})_WV12\.png$")
        found = [(m.group(2), m.group(1), n) for n in listing(FC) for m in [pat.search(n)] if m]
        if found:
            run = max(found)[0]
            for d, lead, n in sorted(found):
                if d != run: continue
                valid = (datetime.strptime(d, "%Y%m%d%H%M").replace(tzinfo=timezone.utc) + timedelta(hours=int(lead))).isoformat()
                try: process(FC, n, "fc_%s_%s" % (d[:10], lead), valid, st, D)
                except Exception as e: log("FAIL fc", d, lead, repr(e))
    except Exception as e: log("прогноз: ошибка листинга", repr(e))
    if os.path.isdir(CACHE):
        for f in os.listdir(CACHE):
            p = os.path.join(CACHE, f)
            if time.time() - os.path.getmtime(p) > KEEP_DAYS * 86400: os.remove(p)
    log("готово")
if __name__ == "__main__":
    main()
