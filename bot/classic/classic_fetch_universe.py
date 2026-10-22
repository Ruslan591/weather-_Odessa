"""classic_fetch_universe.py [N] — исследовательская выборка: топ-N USDT-пар Binance по обороту за сутки (без стейблов и «плечевых»), свечи 1h (365 дн.) и 1d (до 1800 дн.) в research/<SYM>/ (отдельно от pairs/, боевых пар не касается).
Оговорка: выборка по ТЕКУЩЕМУ обороту — монеты, которых уже нет или которые вылетели из топа, не попали (смещение выжившего)."""
import sys, os, json, time
sys.path.insert(0, "/opt/trading-bot/classic")
import classic_learn as L
N = int(sys.argv[1]) if len(sys.argv) > 1 else 120
R = "/opt/trading-bot/classic/research"
STABLE = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "EUR", "EURI", "AEUR", "USD1", "BFUSD", "XUSD", "USDE", "PAXG", "WBTC", "WBETH", "BETH", "GBP", "TRY", "BRL", "ARS", "RUB", "UAH", "JPY", "IDRT", "BIDR", "VAI", "UST", "USTC", "AUD", "CZK", "PLN", "RON", "ZAR", "MXN", "COP"}
tk = L._get("/api/v3/ticker/24hr", {})
rows = []
for x in tk:
    s = x["symbol"]
    if not s.endswith("USDT"):
        continue
    b = s[:-4]
    if b in STABLE or b.endswith(("UP", "DOWN", "BULL", "BEAR")) or b.startswith(("LD",)):
        continue
    rows.append((float(x["quoteVolume"]), s))
rows.sort(reverse=True)
syms = [s for _, s in rows[:N]]
json.dump(syms, open(os.path.join(R + "_universe.json"), "w"))
print("universe", len(syms), syms[:10], flush=True)
for k, s in enumerate(syms):
    d = os.path.join(R, s); os.makedirs(d, exist_ok=True)
    try:
        a = L.download(s, "1h", 365, d); b = L.download(s, "1d", 1800, d)
        print(k + 1, s, len(a), len(b), flush=True)
    except Exception as e:
        print(s, "ошибка", repr(e)[:120], flush=True)
print("done")
