# -*- coding: utf-8 -*-
"""Скачивает дневные свечи делистнутых/умерших монет с Binance в data_ext/ (формат как data/*_USDT_1d.csv).
Запуск: cd /opt/trading-bot && venv/bin/python /tmp/ext_fetch.py"""
import json, os, time, urllib.request, datetime
CAND = ["LUNA", "LUNC", "USTC", "FTT", "SRM", "ANC", "MIR", "BTT", "XEM", "WAVES", "BZRX", "MDX", "TORN", "VGX", "LEND", "BCC", "XMR", "OMG",
        "REEF", "KNC", "GAL", "BNX", "DREP", "MCO", "WTC", "PERL", "CTXC", "FTM", "MATIC", "RNDR", "ONT", "ICX", "QTUM", "NEO", "ZEC", "DASH", "XTZ",
        "IOTA", "BAT", "ZRX", "HOT", "ENJ", "ZIL", "SC", "STORJ", "HNT", "RUNE", "KAVA", "MKR", "COMP", "SNX", "YFI", "SUSHI", "CAKE", "GRT", "AXS", "MANA", "THETA", "EGLD", "FLOW", "ICP", "APE", "LDO", "OP", "ARB", "INJ", "SUI", "APT"]
BASES = ["https://api.binance.com", "https://data-api.binance.vision"]
os.makedirs("data_ext", exist_ok=True)
have = {f.split("_")[0] for f in os.listdir("data") if f.endswith("_1d.csv")}
got = []
for s in CAND:
    if s in have:
        continue
    rows, start, ok = [], 0, True
    for _ in range(12):
        data = None
        for b in BASES:
            try:
                data = json.load(urllib.request.urlopen("%s/api/v3/klines?symbol=%sUSDT&interval=1d&limit=1000&startTime=%d" % (b, s, start), timeout=20))
                break
            except Exception as e:
                last = str(e)[:60]
                time.sleep(0.5)
        if data is None:
            ok = False
            break
        if not data:
            break
        rows += data
        start = int(data[-1][0]) + 1
        if len(data) < 1000:
            break
        time.sleep(0.1)
    if not ok or len(rows) < 300:
        print("нет/мало данных %s (%s)" % (s, "ошибка" if not ok else len(rows)), flush=True)
        continue
    with open("data_ext/%s_USDT_1d.csv" % s, "w") as f:
        f.write("ts,open,high,low,close,volume,time\n")
        for r in rows:
            f.write("%d,%s,%s,%s,%s,%s,%s\n" % (r[0], r[1], r[2], r[3], r[4], r[5], datetime.datetime.fromtimestamp(r[0] / 1000, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S+00:00")))
    last_d = datetime.datetime.fromtimestamp(rows[-1][0] / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")
    first_d = datetime.datetime.fromtimestamp(rows[0][0] / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")
    got.append((s, first_d, last_d, len(rows)))
    print("ok %-6s %s .. %s  дней %d%s" % (s, first_d, last_d, len(rows), "   <-- закончилась раньше" if last_d < "2026-10-01" else ""), flush=True)
print("получено монет:", len(got), "из них закончились раньше сегодняшнего дня:", sum(1 for g in got if g[2] < "2026-10-01"))
