import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
if "score_filter" in s:
    print("ALREADY"); sys.exit(0)
i = s.index("def _side_block(it):")
j = s.index("def _tick_gate(E, it):")
new = '''def _side_block(it):
    """Предфильтры входа теней (shadow_cfg.json, каждый свой выключатель, отфильтрованное ведётся вхолостую cf):
    side_filter: режим down - только short, up - только long, flat - обе стороны (по it["rg"]);
    score_filter: счёт bull-bear режима BTC 1h (tg_regime.json detail) против стороны - не входить;
    btc_rsi_filter: RSI14 BTC 1m вне 40-60 (b1.rsi_ok=0, старое условие);
    counter_filter: контртрендовый сигнал канала (feat.counter);
    rsi5_filter: RSI5 монеты у экстремума против отбоя (long: <30, short: >70);
    width_filter: ширина канала в ATR (feat.width) >= width_max (по умолчанию 8)."""
    try:
        c = cfg(); sd = it.get("side"); ft = it.get("feat") or {}; b1 = it.get("b1") or {}
        if c.get("side_filter", False):
            rg = (it.get("rg") or {}).get("regime")
            if (rg == "down" and sd == "long") or (rg == "up" and sd == "short"):
                return "фильтр стороны: режим %s, %s не разрешён" % (rg, sd)
        if c.get("score_filter", False):
            try:
                st = json.load(open(os.path.join(D, "tg_regime.json"), encoding="utf-8"))
                if time.time() * 1000 - int(st.get("t", 0)) <= 45 * 60000:
                    dt = st.get("detail") or {}; bu = int(dt.get("bull", 0)); be = int(dt.get("bear", 0))
                    al = (bu - be) * (1 if sd == "long" else -1)
                    if al < 0: return "фильтр режима (счёт): быки %d / медведи %d против %s" % (bu, be, sd)
            except Exception: pass
        if c.get("btc_rsi_filter", False) and b1.get("rsi_ok") in (0, False):
            return "фильтр BTC 1m: RSI14 вне 40-60"
        if c.get("counter_filter", False) and ft.get("counter"):
            return "фильтр: сигнал против тренда канала"
        if c.get("rsi5_filter", False) and ft.get("rsi5") is not None:
            r5 = float(ft["rsi5"]); ar = r5 if sd == "long" else 100 - r5
            if ar < 30: return "фильтр RSI5: экстремум %.0f против отбоя (%s)" % (r5, sd)
        if c.get("width_filter", False) and ft.get("width") is not None and float(ft["width"]) >= float(c.get("width_max", 8)):
            return "фильтр ширины канала: %.1f ATR" % float(ft["width"])
    except Exception: pass
    return None


'''
s = s[:i] + new + s[j:]
open(p, "w", encoding="utf-8").write(s)
print("PATCHED")
