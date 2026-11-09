# -*- coding: utf-8 -*-
"""tg_notify.py -- уведомления в Telegram с графиком ордера (счёт «Регрессия» и др.).

Секреты читаются из /opt/trading-bot/tg.env (TG_TOKEN, TG_CHAT_ID, TG_USER_ID); в репозиторий и логи они не попадают.
render_order(o, kl): PNG-график по ордеру из orders.json (свечи 5m, границы канала с цветом по типу up/down/flat, вход, стоп, цель, зоны риска и цели).
send_photo(png, caption, buttons=None) / send_text(text): отправка пользователю. Только исходящие запросы к api.telegram.org.
Запускать в окружении с matplotlib: /opt/tg-notify/venv/bin/python."""
import io, json, os, urllib.request, urllib.parse, uuid
from datetime import datetime, timezone, timedelta

ENV = "/opt/trading-bot/tg.env"
BAR_MS = 300000
UP, DOWN, FLAT = "#48a67e", "#c95b65", "#89919e"      # цвета канала как в индикаторе: растущий, падающий, flat
BG, GRID, TXT = "#0b0e14", "#1b212c", "#c9d1d9"


def _env():
    e = {}
    for ln in open(ENV, encoding="utf-8"):
        if "=" in ln:
            k, v = ln.strip().split("=", 1); e[k] = v
    return e


def _tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Kyiv")
    except Exception:
        return timezone(timedelta(hours=2))


def fmt_px(p):
    p = float(p)
    if p >= 1000: return "%.1f" % p
    if p >= 100: return "%.2f" % p
    if p >= 10: return "%.3f" % p
    if p >= 1: return "%.4f" % p
    if p >= 0.01: return "%.5f" % p
    return "%.7f" % p


def _lighter(hexcol, f=0.5):
    h = hexcol.lstrip("#"); r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % tuple(int(v + (255 - v) * f) for v in (r, g, b))


def chan_color(ctype):
    c = str(ctype or "")
    if "up" in c: return UP
    if "down" in c: return DOWN
    return FLAT


def render_order(o, kl, nbars=96, title=None, watch=False):
    """o: ордер из orders.json; kl: список свечей Binance [[t, o, h, l, c, v, ...], ...]. Возвращает PNG bytes."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    tz = _tz()
    t_end = int(o.get("expire_t") or (o["placed_t"] + 12 * BAR_MS)) + 8 * BAR_MS
    t_start = int(o["placed_t"]) - (nbars - 20) * BAR_MS
    ks = [k for k in kl if t_start <= k[0] <= t_end]
    if len(ks) < 10: raise ValueError("мало свечей для графика")
    x0 = ks[0][0]
    X = lambda t: (t - x0) / BAR_MS
    fig = plt.figure(figsize=(7.2, 6.3), dpi=DPI_OUT)
    gs = fig.add_gridspec(2, 1, height_ratios=[4.3, 1], hspace=0.04)
    ax = fig.add_subplot(gs[0]); axv = fig.add_subplot(gs[1], sharex=ax)
    fig.patch.set_facecolor(BG); ax.set_facecolor(BG); axv.set_facecolor(BG)
    vol_all = [float(k[5]) for k in kl]; idx0 = kl.index(ks[0])
    lows, highs = [], []
    for ii, k in enumerate(ks):
        op, hi, lo, cl = float(k[1]), float(k[2]), float(k[3]), float(k[4]); x = X(k[0]); col = "#26a69a" if cl >= op else "#ef5350"
        ax.plot([x, x], [lo, hi], color=col, lw=0.9, zorder=3)
        ax.add_patch(Rectangle((x - 0.32, min(op, cl)), 0.64, max(abs(cl - op), 1e-12), color=col, zorder=4)); lows.append(lo); highs.append(hi)
        axv.bar(x, float(k[5]), width=0.72, color=col, alpha=0.85, zorder=3)
    xr = X(t_end)
    ch = o.get("chan") or {}; cc = chan_color(o.get("ctype") or ch.get("type"))
    if ch.get("upper") and ch.get("lower"):
        U, L = ch["upper"], ch["lower"]; xa = X(max(U["t1"], x0)); ts = [x0 + xa * BAR_MS, t_end]
        up = [U["p1"] + U["s"] * (t - U["t1"]) for t in ts]; lw = [L["p1"] + L["s"] * (t - L["t1"]) for t in ts]; md = [(a + b) / 2 for a, b in zip(up, lw)]
        xs = [xa, xr]
        ax.fill_between(xs, lw, up, color=cc, alpha=0.08, zorder=1)
        ax.plot(xs, up, color=cc, lw=1.8, zorder=2); ax.plot(xs, lw, color=cc, lw=1.8, zorder=2); ax.plot(xs, md, color=cc, lw=1.0, ls="--", zorder=2)
        lows += [min(lw)]; highs += [max(up)]
    c0 = o.get("chan0") if watch else None
    if c0 and c0.get("upper") and c0.get("lower") and c0 != ch:      # канал на момент касания (начало слежения): тот же цвет, светлее, пунктиром
        U0, L0 = c0["upper"], c0["lower"]; xa0 = X(max(U0["t1"], x0)); ts0 = [x0 + xa0 * BAR_MS, t_end]; c0c = _lighter(chan_color(o.get("ctype") or c0.get("type")), 0.55)
        up0 = [U0["p1"] + U0["s"] * (t - U0["t1"]) for t in ts0]; lw0 = [L0["p1"] + L0["s"] * (t - L0["t1"]) for t in ts0]; xs0 = [xa0, xr]
        ax.plot(xs0, up0, color=c0c, lw=1.5, ls=(0, (5, 3)), zorder=2); ax.plot(xs0, lw0, color=c0c, lw=1.5, ls=(0, (5, 3)), zorder=2)
        ax.plot(xs0, [(p + q) / 2 for p, q in zip(up0, lw0)], color=c0c, lw=0.8, ls=(0, (2, 3)), zorder=2)
        lows += [min(lw0)]; highs += [max(up0)]
        ax.text(0.01, 0.02, "светлый пунктир — канал на момент касания · цветной — текущий", transform=ax.transAxes, color=c0c, fontsize=7, va="bottom", ha="left", zorder=8)
    xp = X(o["placed_t"]); labs = []
    if watch:      # слежение: без входа/стопа/цели, отметка касания и текущая цена
        lc = float(ks[-1][4]); labs.append([lc, lc, "#e6edf3", "цена"]); ax.plot([xp, xr], [lc, lc], color="#e6edf3", lw=1.0, ls=":", zorder=5)
        if o.get("touch_px") is not None:
            tpx = float(o["touch_px"]); my = tpx + (max(highs) - min(lows) or tpx * 0.01) * 0.045 * (1 if o.get("side") == "short" else -1)     # маркер отнесён от экстремума наружу, чтобы не сливался со свечой и линией канала
            ax.plot([xp], [my], marker="v" if o.get("side") == "short" else "^", color="#e3b341", mec=BG, mew=0.8, ms=9, zorder=7); lows.append(my); highs.append(my)
        lows.append(lc); highs.append(lc)
        ln = (ch.get("upper") if o.get("side") == "short" else ch.get("lower")) if ch else None
        if ln:      # свечи, закрывшиеся за линией (по текущей линии): кружки на закрытии
            for k in ks:
                if k[0] < o["placed_t"]: continue
                v = ln["p1"] + ln["s"] * (k[0] - ln["t1"]); cl = float(k[4])
                if (o["side"] == "short" and cl > v) or (o["side"] == "long" and cl < v): ax.plot([X(k[0])], [cl], marker="o", mfc="none", mec="#e3b341", ms=6, mew=1.4, zorder=7)
    else:
        en, st, tp = float(o["price"]), float(o["stop"]), float(o["tp"])
        ax.add_patch(Rectangle((xp, min(en, st)), xr - xp, abs(st - en), color="#ef5350", alpha=0.16, zorder=1))
        ax.add_patch(Rectangle((xp, min(en, tp)), xr - xp, abs(tp - en), color="#26a69a", alpha=0.14, zorder=1))
        for y, col, name in ((en, "#e6edf3", "вход"), (st, "#ef5350", "стоп"), (tp, "#26a69a", "цель")):
            ax.plot([xp, xr], [y, y], color=col, lw=1.3, ls="--" if name != "вход" else "-", zorder=5); labs.append([y, y, col, name])
        lows += [st, tp, en]; highs += [st, tp, en]
    lo_, hi_ = min(lows), max(highs); pad = (hi_ - lo_) * 0.06 or lo_ * 0.001
    ax.set_ylim(lo_ - pad, hi_ + pad); gap = (hi_ - lo_ + 2 * pad) * 0.055
    labs.sort(key=lambda r: r[1])
    for i in range(1, len(labs)):
        if labs[i][1] - labs[i - 1][1] < gap: labs[i][1] = labs[i - 1][1] + gap
    for y, ty, col, name in labs:
        ax.text(xr + 0.4, ty, "%s %s" % (name, fmt_px(y)), color=BG, fontsize=7.5, va="center", fontweight="bold", zorder=6, bbox=dict(boxstyle="square,pad=0.25", fc=col, ec="none"))
        if abs(ty - y) > 1e-12: ax.plot([xr, xr + 0.4], [y, ty], color=col, lw=0.8, zorder=5)
    ax.axvline(xp, color="#8b949e", lw=0.8, ls=":", zorder=2); axv.axvline(xp, color="#8b949e", lw=0.8, ls=":", zorder=2)
    ma = []
    for ii in range(len(ks)):
        g = idx0 + ii; w = vol_all[max(0, g - 19):g + 1]; ma.append(sum(w) / len(w))
    axv.plot([X(k[0]) for k in ks], ma, color="#e3b341", lw=1.1, zorder=4)
    last = [i for i, k in enumerate(ks) if k[0] <= o["placed_t"]][-1]; ratio = float(ks[last][5]) / ma[last] if ma[last] else 0
    axv.text(0.005, 0.95, ("объём · линия = среднее за 20 свечей · на свече касания ×%.1f" if watch else "объём · линия = среднее за 20 свечей · на свече выставления ×%.1f") % ratio, transform=axv.transAxes, color=TXT, fontsize=7, va="top")
    axv.set_ylim(0, max(float(k[5]) for k in ks) * 1.15)
    ax.text(xp, 1.0, " " + o.get("mark", "лимит выставлен") + " " + datetime.fromtimestamp(o["placed_t"] / 1000, tz).strftime("%H:%M"), transform=ax.get_xaxis_transform(), color=TXT, fontsize=7.5, va="top", ha="left")
    ax.set_xlim(-1, xr + 14)
    step = 12; xt = [i for i in range(0, int(xr) + 1, step)]
    axv.set_xticks(xt); axv.set_xticklabels([datetime.fromtimestamp((x0 + i * BAR_MS) / 1000, tz).strftime("%H:%M") for i in xt], color=TXT, fontsize=7.5)
    ax.tick_params(axis="x", labelbottom=False); ax.tick_params(axis="y", labelleft=False, labelright=False, left=False)
    axv.tick_params(axis="y", labelleft=False, left=False)
    for a_ in (ax, axv): a_.grid(color=GRID, lw=0.6); [sp.set_color(GRID) for sp in a_.spines.values()]
    ax.set_title(title or "%s  %s  %s" % (o.get("sym"), str(o.get("side", "")).upper(), RULE_RU.get(o.get("rule"), o.get("rule", ""))), color=TXT, fontsize=10, loc="left")
    fig.subplots_adjust(left=0.02, right=0.99, top=0.94, bottom=0.05)
    buf = io.BytesIO(); fig.savefig(buf, format="png", facecolor=BG); plt.close(fig)
    return buf.getvalue()


DPI_OUT = 175  # 7.2in*175=1260px; Telegram sendPhoto режет всё свыше 1280px по длинной стороне

RULE_RU = {"tg_stop": "стоп-ордер на вход (из слежения)", "tg_market": "по рынку (из слежения)", "tg_limit": "лимит у линии (из слежения)", "watch": "слежение за касанием", "chan_top": "отбой от верхней границы канала", "chan_bottom": "отбой от нижней границы канала", "retest_up": "ретест после пробоя вверх", "retest_down": "ретест после пробоя вниз", "breakout_up": "пробой вверх", "breakout_down": "пробой вниз"}


def caption_order(o, acct="Регрессия"):
    en, st, tp = float(o["price"]), float(o["stop"]), float(o["tp"]); s = 1 if o["side"] == "long" else -1
    risk = abs(en - st) / en * 100; rew = abs(tp - en) / en * 100
    ctype = {"channel_up": "восходящий", "channel_down": "нисходящий"}.get(str(o.get("ctype")), "flat")
    ct = str(o.get("ctype") or "")
    counter = (s > 0 and "down" in ct) or (s < 0 and "up" in ct)
    ew = {"tg_market": "по рынку", "tg_stop": "стоп-ордер (вход при срабатывании)"}.get(o.get("rule"), "лимит")
    txt = "%s · %s %s %s %s\nстоп %s (−%.2f%%) · цель %s (+%.2f%%) · R:R %.1f\nканал: %s · сетап: %s" % (
        acct, o["sym"], "LONG" if s > 0 else "SHORT", ew, fmt_px(en), fmt_px(st), risk, fmt_px(tp), rew, rew / risk if risk else 0, ctype, RULE_RU.get(o.get("rule"), o.get("rule", "")))
    if o.get("setup"): txt += "\nтип: %s %s линии" % ("пробой" if o["setup"] == "breakout" else "отбой от", "верхней" if o.get("line") == "upper" else "нижней")
    if counter: txt += "\n⚠️ Направление сделки против направления канала (ретест/пробой)."
    return txt


def render_watch(w, kl):
    """График слежения: свечи, текущие границы канала, отметка касания, цена, объём."""
    L = w.get("last") or {}; last_t = int(L.get("t") or w["t_alert"])
    mark = {"touch": "касание", "cross": "выход за линию", "break": "начало пробоя", "back": "выход и возврат"}.get(w.get("state0"), "касание")
    o = {"sym": w["sym"], "side": w["side"], "rule": "watch", "placed_t": int(w.get("t_ref") or w["t_alert"]), "expire_t": last_t + 2 * BAR_MS, "ctype": w.get("ctype"), "chan": w.get("chan"), "chan0": w.get("chan0"), "touch_px": w.get("touch_px"), "mark": mark}
    return render_order(o, kl, title="%s  %s  слежение за касанием линии" % (w["sym"], str(w["side"]).upper()), watch=True)


STATE_RU = {"touch": "касание линии", "cross": "свеча закрылась за линией (первая)", "break": "ПРОБОЙ ФОРМИРУЕТСЯ: несколько закрытий за линией", "back": "выход за линию и возврат внутрь", "away": "цена отошла от линии"}


def caption_watch(w, kind):
    """kind: alert | update. Состояние у линии считается по текущим линиям канала на последних свечах."""
    L = w.get("last") or {}; down = w["side"] == "short"; line = "верхнюю" if down else "нижнюю"; ctd = w.get("ctype") == "channel_down"; ct = "нисходящего" if ctd else "восходящего"; a = float(w.get("atr") or L.get("atr") or 0)
    hm = lambda ms: datetime.fromtimestamp(int(ms) / 1000, _tz()).strftime("%H:%M")
    pos_ = ""
    if L.get("R") is not None and L["R"] != L["S"]: pos_ = " · в канале на %d%% высоты" % round((float(L["c"]) - L["S"]) / (L["R"] - L["S"]) * 100)
    if kind == "alert":
        st = w.get("state0", "touch"); lp = float(w["line_px"]); sp = float(w["touch_px"]); nb = w.get("n_beyond", 0); nr = w.get("n_run", 1)
        head = {"touch": "касается", "cross": "пересекла", "break": "ПРОБИВАЕТ", "back": "вышла за и вернулась к"}.get(st, "у")
        if st == "touch": body = "свеча %s коснулась линии: экстремум %s, линия %s" % (hm(L.get("t") or w["t_alert"]), fmt_px(sp), fmt_px(lp))
        elif st == "back": body = "%d св. закрылись за линией, последняя вернулась внутрь; эпизод с %s (экстремум %s)" % (nb, hm(w.get("t_ref") or w["t_alert"]), fmt_px(sp))
        else: body = "%d из %d последних свечей закрылись за линией; эпизод с %s (экстремум %s, линия сейчас %s)" % (nb, nr, hm(w.get("t_ref") or w["t_alert"]), fmt_px(sp), fmt_px(lp))
        note = ("\nЭто линия против тренда: отбой от неё = коррекция, пробой = продолжение тренда." if w.get("counter") else "\nЭто линия по тренду: отбой от неё = по тренду, пробой = разворот.")
        return "⚡ %s: цена %s %s линию %s канала\n%s%s\nКанал %s.%s\nСледить или отклонить?" % (w["sym"], head, line if st != "back" else "", ct, body, pos_, "нисходящий" if ctd else "восходящий", note)
    d = ((float(L["R"]) - float(L["c"])) / a if down else (float(L["c"]) - float(L["S"])) / a) if a and L.get("R") is not None else 0
    txt = "👁 %s: свеча %s закрыта, close %s%s\nСостояние: %s · до линии %+.2f ATR (минус = за линией) · слежу %d-ю свечу" % (w["sym"], hm(L.get("t") or 0), fmt_px(L.get("c") or 0), pos_, STATE_RU.get(w.get("state"), "—"), d, w.get("updates", 0))
    sh = w.get("shift")
    if sh is not None and abs(sh) >= 0.5: txt += "\n⚠️ Канал перестроился: линия сместилась на %+.1f ATR за последнюю свечу (картинка показывает новые линии)." % sh
    return txt


def render_status(d):
    """Карточка счёта картинкой (тёмная тема как у графиков). d: acct, sub, mode, mode_ru, info[], equity, chg_usd, chg_pct, tiles[(подпись, значение, цвет)],
    orders {pend, prop, rows[]}, positions[{sym, side, pct, usd, be, part}], watches[(текст, цвет)], max_watch, err, stamp."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    W = 936; PAD = 30; CARD = "#131a24"; DIM = "#7d8590"; GRN = "#26a69a"; RED = "#ef5350"; YEL = "#e3b341"; BLU = "#58a6ff"; LINE = "#222b38"
    MODEC = {"monitor": GRN, "sleep": DIM, "auto": BLU}

    def lay(ax):
        y = 26
        def T_(x, yy, s, **kw):
            if ax is not None: ax.text(x, yy, str(s).replace("$", r"\$"), **kw)     # \$: иначе пара $ уходит в mathtext
        def box(x, yy, w, h, fc, ec="none", r=10, alpha=1.0):
            if ax is not None: ax.add_patch(FancyBboxPatch((x, yy), w, h, boxstyle="round,pad=0,rounding_size=%d" % r, fc=fc, ec=ec, lw=1.0, alpha=alpha))
        def sect(title, y, right=None):
            if ax is not None:
                ax.text(PAD, y, title, color=DIM, fontsize=9, fontweight="bold", va="top")
                if right: ax.text(W - PAD, y, right, color=DIM, fontsize=9, va="top", ha="right")
                ax.plot([PAD, W - PAD], [y + 24, y + 24], color=LINE, lw=1.0)
            return y + 36
        # заголовок
        T_(PAD, y, "Счёт «%s»" % d["acct"], color="#e6edf3", fontsize=18, fontweight="bold", va="top")
        T_(PAD, y + 42, d.get("sub", ""), color=DIM, fontsize=9.5, va="top")
        mc = MODEC.get(d.get("mode"), DIM)
        box(W - PAD - 150, y + 2, 150, 38, mc, ec=mc, r=19, alpha=0.18)
        T_(W - PAD - 75, y + 21, d.get("mode_ru", ""), color=mc, fontsize=12, fontweight="bold", va="center", ha="center")
        y += 84
        # эквити
        if d.get("equity") is not None:
            cc = GRN if d["chg_usd"] >= 0 else RED
            T_(PAD, y, "%.2f $" % d["equity"], color="#f0f6fc", fontsize=36, fontweight="bold", va="top")
            T_(PAD + 3, y + 70, "%+.2f $  (%+.2f%%) к старту" % (d["chg_usd"], d["chg_pct"]), color=cc, fontsize=13, fontweight="bold", va="top")
            y += 116
            n = len(d["tiles"]); gap = 12; tw = (W - 2 * PAD - gap * (n - 1)) / n
            for i, (lab, val, col) in enumerate(d["tiles"]):
                x = PAD + i * (tw + gap); box(x, y, tw, 74, CARD, ec=LINE)
                T_(x + 14, y + 12, lab, color=DIM, fontsize=8.5, va="top"); T_(x + 14, y + 36, val, color=col, fontsize=15, fontweight="bold", va="top")
            y += 74 + 26
        else:
            T_(PAD, y, "Баланс и позиции сейчас получить не удалось", color=YEL, fontsize=12, va="top"); y += 44
        # ордера
        o = d["orders"]; y = sect("ОРДЕРА", y)
        for x0, n_, lab in ((PAD, o["pend"], "ждут исполнения"), (PAD + 300, o["prop"], "ждут вашего решения")):
            T_(x0, y - 2, str(n_), color="#e6edf3" if n_ else DIM, fontsize=16, fontweight="bold", va="top"); T_(x0 + 30, y + 2, lab, color=DIM, fontsize=11.5, va="top")
        y += 38
        for (sym, side, rest) in o.get("rows", []):
            sc = RED if side == "SHORT" else GRN
            T_(PAD, y, sym, color="#e6edf3", fontsize=11, fontweight="bold", va="top"); T_(PAD + 92, y, side, color=sc, fontsize=10.5, fontweight="bold", va="top"); T_(PAD + 170, y, rest, color=DIM, fontsize=9.5, va="top")
            y += 26
        y += 14
        # позиции
        ps = d.get("positions", []); y = sect("ОТКРЫТЫЕ ПОЗИЦИИ", y, "%d" % len(ps))
        if not ps: T_(PAD, y, "Открытых позиций нет", color=DIM, fontsize=11.5, va="top"); y += 34
        else:
            for c, x in (("пара", PAD + 14), ("net", 370), ("PnL", 500), ("БУ", 640)): T_(x, y, c, color=DIM, fontsize=8.5, va="top")
            y += 22
            for i, p in enumerate(ps):
                box(PAD, y, W - 2 * PAD, 40, CARD, ec="none", r=8)
                sc = RED if p["side"] == "SHORT" else GRN; pc = GRN if p["usd"] >= 0 else RED
                T_(PAD + 14, y + 20, p["sym"], color="#e6edf3", fontsize=12.5, fontweight="bold", va="center")
                box(PAD + 110, y + 8, 82, 24, sc, ec=sc, r=12, alpha=0.2); T_(PAD + 151, y + 20, p["side"], color=sc, fontsize=10, fontweight="bold", va="center", ha="center")
                T_(370, y + 20, "%+.2f%%" % p["pct"], color=pc, fontsize=12, fontweight="bold", va="center"); T_(500, y + 20, "%+.2f $" % p["usd"], color=pc, fontsize=12, fontweight="bold", va="center")
                T_(640, y + 20, "да" if p["be"] else "нет", color=GRN if p["be"] else DIM, fontsize=11.5, fontweight="bold" if p["be"] else "normal", va="center")
                if p.get("part"): T_(W - PAD - 14, y + 20, "часть закрыта", color=YEL, fontsize=9.5, va="center", ha="right")
                y += 46
            y += 4
        y += 10
        # графики в работе
        ws = d.get("watches", [])
        if ws:
            y = sect("ГРАФИКИ В РАБОТЕ", y, "%d из %d" % (len(ws), d.get("max_watch", 3)))
            for txt, col in ws: T_(PAD, y, txt, color=col, fontsize=11, va="top"); y += 27
            y += 12
        # режим и время
        for s in d.get("info", []): T_(PAD, y, s, color=DIM, fontsize=9.5, va="top"); y += 22
        T_(PAD, y + 6, "обновлено " + d.get("stamp", ""), color="#4d5562", fontsize=8, va="top")
        return y + 40

    H = lay(None)
    fig = plt.figure(figsize=(W / 130.0, H / 130.0), dpi=DPI_OUT); fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off"); ax.set_facecolor(BG)
    lay(ax)
    buf = io.BytesIO(); fig.savefig(buf, format="png", facecolor=BG); plt.close(fig)
    return buf.getvalue()


def _post(method, fields=None, files=None):
    e = _env(); url = "https://api.telegram.org/bot%s/%s" % (e["TG_TOKEN"], method)
    if files:
        bd = uuid.uuid4().hex; body = b""
        for k, v in (fields or {}).items():
            body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (bd, k, v)).encode("utf-8")
        for k, (fn, data, ct) in files.items():
            body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n" % (bd, k, fn, ct)).encode("utf-8") + data + b"\r\n"
        body += ("--%s--\r\n" % bd).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "multipart/form-data; boundary=" + bd})
    else:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(fields or {}).encode())
    return json.load(urllib.request.urlopen(req, timeout=30))


def send_text(text, buttons=None, reply_to=None):
    f = {"chat_id": _env()["TG_CHAT_ID"], "text": text}
    if reply_to: f["reply_to_message_id"] = str(reply_to); f["allow_sending_without_reply"] = "true"
    if buttons: f["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return _post("sendMessage", f)


def send_photo(png, caption, buttons=None, reply_to=None):
    f = {"chat_id": _env()["TG_CHAT_ID"], "caption": caption}
    if reply_to: f["reply_to_message_id"] = str(reply_to); f["allow_sending_without_reply"] = "true"
    if buttons: f["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return _post("sendPhoto", f, {"photo": ("order.png", png, "image/png")})
