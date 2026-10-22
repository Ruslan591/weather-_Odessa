"""classic_fetch_htf.py — докачка свечей старших ТФ (1d, 1w, 1M) для пар из pairs.json и базовых ТФ для новых пар (BNB). Ничего не перезаписывает, только докачивает."""
import sys, os, json, time
sys.path.insert(0, "/opt/trading-bot/classic")
import pandas as pd
import classic_learn as L
syms = json.load(open("/opt/trading-bot/classic/pairs.json"))
BASE = ["15m", "30m", "1h", "2h", "4h", "6h", "12h"]
def fetch_big(sym, tf, d):
    """1w / 1M: все закрытые свечи с начала истории (до ~1000 штук одним запросом)."""
    fn = os.path.join(d, "klines_%s.csv" % tf)
    now = int(time.time() * 1000)
    data = L._get("/api/v3/klines", {"symbol": sym, "interval": tf, "startTime": 1262304000000, "limit": 1000})
    rows = [(int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]), int(x[6])) for x in data]
    df = pd.DataFrame(rows, columns=["t", "o", "h", "l", "c", "v", "ct"])
    df = df[df["ct"] < now].drop_duplicates("t").sort_values("t").reset_index(drop=True)
    df.to_csv(fn, index=False)
    return df
for sym in syms:
    d = L.pair_dir(sym)
    try:
        if not os.path.exists(os.path.join(d, "klines_15m.csv")):
            for tf in BASE:
                df = L.download(sym, tf, 365, d); print(sym, tf, len(df), flush=True)
        df = L.download(sym, "1d", 1800, d); print(sym, "1d", len(df), flush=True)
        for tf in ("1w", "1M"):
            df = fetch_big(sym, tf, d); print(sym, tf, len(df), flush=True)
    except Exception as e:
        print(sym, "ошибка", repr(e)[:200], flush=True)
print("done")
