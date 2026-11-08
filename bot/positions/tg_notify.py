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
    fig = plt.figure(figsize=(7.2, 6.3), dpi=130)
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
    xp = X(o["placed_t"]); labs = []
    if watch:      # слежение: без входа/стопа/цели, отметка касания и текущая цена
        lc = float(ks[-1][4]); labs.append([lc, lc, "#e6edf3", "цена"]); ax.plot([xp, xr], [lc, lc], color="#e6edf3", lw=1.0, ls=":", zorder=5)
        if o.get("touch_px") is not None:
            ax.plot([xp], [float(o["touch_px"])], marker="v" if o.get("side") == "short" else "^", color="#e3b341", ms=8, zorder=7); lows.append(float(o["touch_px"])); highs.append(float(o["touch_px"]))
        lows.append(lc); highs.append(lc)
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


RULE_RU = {"tg_market": "по рынку (из слежения)", "tg_limit": "лимит у линии (из слежения)", "watch": "слежение за касанием", "chan_top": "отбой от верхней границы канала", "chan_bottom": "отбой от нижней границы канала", "retest_up": "ретест после пробоя вверх", "retest_down": "ретест после пробоя вниз", "breakout_up": "пробой вверх", "breakout_down": "пробой вниз"}


def caption_order(o, acct="Регрессия"):
    en, st, tp = float(o["price"]), float(o["stop"]), float(o["tp"]); s = 1 if o["side"] == "long" else -1
    risk = abs(en - st) / en * 100; rew = abs(tp - en) / en * 100
    ctype = {"channel_up": "восходящий", "channel_down": "нисходящий"}.get(str(o.get("ctype")), "flat")
    ct = str(o.get("ctype") or "")
    counter = (s > 0 and "down" in ct) or (s < 0 and "up" in ct)
    txt = "%s · %s %s лимит %s\nстоп %s (−%.2f%%) · цель %s (+%.2f%%) · R:R %.1f\nканал: %s · сетап: %s" % (
        acct, o["sym"], "LONG" if s > 0 else "SHORT", fmt_px(en), fmt_px(st), risk, fmt_px(tp), rew, rew / risk if risk else 0, ctype, RULE_RU.get(o.get("rule"), o.get("rule", "")))
    if counter: txt += "\n⚠️ Направление сделки против направления канала (ретест/пробой)."
    return txt


def render_watch(w, kl):
    """График слежения: свечи, текущие границы канала, отметка касания, цена, объём."""
    L = w.get("last") or {}; last_t = int(L.get("t") or w["t_alert"])
    o = {"sym": w["sym"], "side": w["side"], "rule": "watch", "placed_t": int(w["t_alert"]), "expire_t": last_t + 2 * BAR_MS, "ctype": w.get("ctype"), "chan": w.get("chan"), "touch_px": w.get("touch_px"), "mark": "касание"}
    return render_order(o, kl, title="%s  %s  слежение за касанием линии" % (w["sym"], str(w["side"]).upper()), watch=True)


def caption_watch(w, kind):
    """kind: alert | update."""
    L = w.get("last") or {}; down = w["side"] == "short"; line = "верхнюю" if down else "нижнюю"; ct = "нисходящего" if down else "восходящего"; a = float(w.get("atr") or L.get("atr") or 0)
    pos_ = ""
    if L.get("R") is not None and L["R"] != L["S"]: pos_ = " · в канале на %d%% высоты" % round((float(L["c"]) - L["S"]) / (L["R"] - L["S"]) * 100)
    if kind == "alert":
        lp = float(w["line_px"]); tp_ = float(w["touch_px"]); d = (tp_ - lp) / a if (down and a) else ((lp - tp_) / a if a else 0)
        how = "пересекла" if d > 0.05 else "коснулась"
        return "⚡ %s: цена %s %s линию %s канала\nсвеча %s: экстремум %s, линия %s (%+.2f ATR)%s\nКанал %s. Следить или отклонить?" % (
            w["sym"], how, line, ct, datetime.fromtimestamp(int(w["t_alert"]) / 1000, _tz()).strftime("%H:%M"), fmt_px(tp_), fmt_px(lp), d, pos_, "нисходящий" if down else "восходящий")
    return "👁 %s: свеча %s закрыта, close %s%s\nДо линии: %.2f ATR · слежу %d-ю свечу (без ответа не более 3 подряд)" % (
        w["sym"], datetime.fromtimestamp(int(L.get("t") or 0) / 1000, _tz()).strftime("%H:%M"), fmt_px(L.get("c") or 0), pos_,
        ((float(L["R"]) - float(L["c"])) / a if down else (float(L["c"]) - float(L["S"])) / a) if a and L.get("R") is not None else 0, w.get("updates", 0))


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


def send_text(text, buttons=None):
    f = {"chat_id": _env()["TG_CHAT_ID"], "text": text}
    if buttons: f["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return _post("sendMessage", f)


def send_photo(png, caption, buttons=None):
    f = {"chat_id": _env()["TG_CHAT_ID"], "caption": caption}
    if buttons: f["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    return _post("sendPhoto", f, {"photo": ("order.png", png, "image/png")})
