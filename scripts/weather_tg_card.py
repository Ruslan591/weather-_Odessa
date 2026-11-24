# -*- coding: utf-8 -*-
"""Карточки-картинки для канала погоды. Шкалы повторяют indicators.js сайта:
полукруг 180° с градиентом по всей шкале, засечки, подписи по краям, треугольная стрелка.
render_pws(d) -> PNG bytes (частные станции, средний по городу)
render_gmc(d) -> PNG bytes (официальная сводка ГМЦ)
Pillow + DejaVu Sans."""
import io
import math
from PIL import Image, ImageDraw, ImageFont

FD = "/usr/share/fonts/truetype/dejavu/"
S = 2
W, PAD, GAP = 1080, 36, 22
BG, TILE, TILE_B = (18, 18, 20), (30, 30, 32), (46, 46, 50)
TXT, DIM = (236, 236, 238), (150, 150, 156)
TRACK = (53, 53, 56)
TICK = (118, 118, 122)
TICK_MIN = (70, 70, 74)
_fc = {}


def font(sz, bold=False):
    k = (round(sz * 2), bold)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(FD + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), max(1, int(round(sz * S))))
    return _fc[k]


def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def gcol(stops, t):
    t = max(0.0, min(1.0, t))
    for i in range(1, len(stops)):
        o0, c0 = stops[i - 1]
        o1, c1 = stops[i]
        if t <= o1:
            u = 0 if o1 == o0 else (t - o0) / (o1 - o0)
            return tuple(int(c0[j] + (c1[j] - c0[j]) * u) for j in range(3))
    return stops[-1][1]


def st(lst):
    return [(o, hexc(c)) for o, c in lst]


T_ST = st([(0, "#3a8fff"), (.25, "#9dd6ff"), (.5, "#5fe08f"), (.75, "#ffd84d"), (1, "#ff6b3a")])
H_ST = st([(0, "#ffd166"), (.5, "#5fe08f"), (1, "#58aeff")])
P_ST = st([(0, "#3a8fff"), (.33, "#72c8ff"), (.55, "#5fe08f"), (.75, "#c8e05f"), (.92, "#ffb347"), (1, "#ff6b3a")])
W_ST = st([(0, "#7ec8ff"), (.13, "#67d7a7"), (.36, "#ffd166"), (.57, "#ff9f5c"), (1, "#ff6b6b")])
RR_ST = st([(0, "#c8e05f"), (.1, "#5fe08f"), (.3, "#58aeff"), (.6, "#3a8fff"), (1, "#a855f7")])
RT_ST = st([(0, "#c8e05f"), (.05, "#5fe08f"), (.2, "#58aeff"), (.5, "#3a8fff"), (1, "#a855f7")])


def fmt1(x):
    return ("%.1f" % x).replace(".", ",")


def tx(d, xy, s, f, fill, anchor="la"):
    d.text((xy[0] * S, xy[1] * S), s, font=f, fill=fill, anchor=anchor)


def line(d, p0, p1, fill, w):
    d.line((p0[0] * S, p0[1] * S, p1[0] * S, p1[1] * S), fill=fill, width=max(1, int(round(w * S))))


def tile(d, x, y, w, h):
    d.rounded_rectangle((x * S, y * S, (x + w) * S, (y + h) * S), radius=26 * S, fill=TILE, outline=TILE_B, width=S)


def disc(d, x, y, r, fill):
    d.ellipse(((x - r) * S, (y - r) * S, (x + r) * S, (y + r) * S), fill=fill)


# ------------------------------------------------------------------ шкалы (как на сайте)

def semi_gauge(d, cx, cy, k, val, vmin, vmax, stops, labels, minors, unit, value_txt, sub=None, sub_col=None, major_len=9, major_w=2.0):
    """Центр дуги (cx,cy) в пикселях; k = масштаб viewBox сайта (160x110, центр 80,85, R=65)."""
    R = 65 * k
    box = ((cx - R) * S, (cy - R) * S, (cx + R) * S, (cy + R) * S)
    d.arc(box, 180, 360, fill=TRACK, width=int(8 * k * S))
    n = 180
    for i in range(n):
        t0 = i / n
        d.arc(box, 180 + 180 * t0, 180 + 180 * (t0 + 1.0 / n) + 0.7, fill=gcol(stops, t0 + 0.5 / n), width=int(7 * k * S))
    for tt in (0.0, 1.0):  # круглые концы
        a = math.radians(180 + 180 * tt)
        disc(d, cx + R * math.cos(a) / 1.0, cy + R * math.sin(a), 3.5 * k, gcol(stops, tt))
    # засечки
    for t in [i / (len(labels) - 1) for i in range(len(labels))] if labels else []:
        a = math.radians(180 + 180 * t)
        line(d, (cx + R * math.cos(a), cy + R * math.sin(a)), (cx + (R - major_len * k) * math.cos(a), cy + (R - major_len * k) * math.sin(a)), TICK, major_w * k / 2.0)
    for t in minors:
        a = math.radians(180 + 180 * t)
        line(d, (cx + R * math.cos(a), cy + R * math.sin(a)), (cx + (R - 5 * k) * math.cos(a), cy + (R - 5 * k) * math.sin(a)), TICK_MIN, 1.2 * k / 1.6)
    # подписи
    for i, lab in enumerate(labels):
        t = i / (len(labels) - 1.0)
        a = math.radians(180 + 180 * t)
        r = 79 * k if t in (0.0, 1.0) else 78 * k
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        anc = "rm" if t < 0.35 else ("lm" if t > 0.65 else "mm")
        if t in (0.0, 1.0):
            y = cy
        tx(d, (x, y), lab, font(8.4 * k), (130, 130, 136), anc)
    # стрелка
    if val is not None:
        t = (max(vmin, min(vmax, val)) - vmin) / float(vmax - vmin)
        al = math.radians((t - 0.5) * 180)
        ux, uy = math.sin(al), -math.cos(al)
        px, py = math.cos(al), math.sin(al)
        tip = (cx + 57 * k * ux, cy + 57 * k * uy)
        b1 = (cx + 43 * k * ux + 7 * k * px, cy + 43 * k * uy + 7 * k * py)
        b2 = (cx + 43 * k * ux - 7 * k * px, cy + 43 * k * uy - 7 * k * py)
        d.polygon([(tip[0] * S, tip[1] * S), (b1[0] * S, b1[1] * S), (b2[0] * S, b2[1] * S)], fill=(228, 228, 232))
        vcol = gcol(stops, t)
    else:
        vcol = (170, 170, 170)
    tx(d, (cx, cy), value_txt, font(17 * k / 1.0 * 0.95, True), vcol, "ms")
    tx(d, (cx, cy - 20 * k), unit, font(9.5 * k), (140, 140, 146), "ms")
    if sub:
        tx(d, (cx, cy + 11 * k), sub, font(9.5 * k), sub_col or vcol, "ms")


def wind_gauge(d, cx, cy, k, speed, gust, deg):
    """viewBox 160x160, центр (80,70), кольцо r=43."""
    vmax = 25.0
    col = gcol(W_ST, min(speed, vmax) / vmax) if speed is not None else (90, 90, 94)
    for i in range(16):
        a = math.radians(i * 22.5 - 90)
        if i % 2 == 0:
            r1, r2, c, w = 57, 50, TICK, 2.2
        else:
            r1, r2, c, w = 57, 53, TICK_MIN, 1.4
        line(d, (cx + r1 * k * math.cos(a), cy + r1 * k * math.sin(a)), (cx + r2 * k * math.cos(a), cy + r2 * k * math.sin(a)), c, w * k / 1.8)
    for s_, (dx, dy) in (("С", (0, -61)), ("В", (63, 0)), ("Ю", (0, 61)), ("З", (-63, 0))):
        tx(d, (cx + dx * k, cy + dy * k), s_, font(10 * k), (200, 200, 205), "mm")
    r = 43 * k
    d.ellipse(((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S), outline=tuple(int(c * .75 + 30 * .25) for c in col), width=int(3.5 * k * S))
    if deg is not None:
        a = math.radians(deg)
        ux, uy = math.sin(a), -math.cos(a)
        px, py = math.cos(a), math.sin(a)
        tip = (cx + 25 * k * ux, cy + 25 * k * uy)
        b1 = (cx + 44.5 * k * ux + 4 * k * px, cy + 44.5 * k * uy + 4 * k * py)
        b2 = (cx + 44.5 * k * ux - 4 * k * px, cy + 44.5 * k * uy - 4 * k * py)
        d.polygon([(tip[0] * S, tip[1] * S), (b1[0] * S, b1[1] * S), (b2[0] * S, b2[1] * S)], fill=(228, 228, 232))
    tx(d, (cx, cy - 18 * k), "м/с", font(9.5 * k), (140, 140, 146), "ms")
    tx(d, (cx, cy + 3.5 * k), fmt1(speed) if speed is not None else "—", font(19 * k * 0.95, True), col, "ms")
    if gust is not None and gust > 0:
        gcl = gcol(W_ST, min(max(gust, (speed or 0) + 3), vmax) / vmax)
        tx(d, (cx, cy + 18 * k), fmt1(gust), font(12 * k, True), gcl, "ms")
        tx(d, (cx, cy + 30 * k), "порывы", font(8.6 * k), (110, 110, 116), "ms")
    if deg is not None:
        pts = ["С", "ССВ", "СВ", "ВСВ", "В", "ВЮВ", "ЮВ", "ЮЮВ", "Ю", "ЮЮЗ", "ЮЗ", "ЗЮЗ", "З", "ЗСЗ", "СЗ", "ССЗ"]
        tx(d, (cx, cy + 85 * k), "%s · %d°" % (pts[int((deg % 360) / 22.5 + .5) % 16], round(deg)), font(12 * k), (170, 170, 176), "ms")


def trend_line(d, x, y, w, h, tr):
    """Мини-график тенденции давления (как .ind-trend на сайте)."""
    if tr is None:
        paths = [(0, 6), (12, 6), (24, 6), (36, 6), (48, 6)]
        col = (80, 80, 84)
    elif abs(tr) < 0.3:
        paths = [(0, 6), (12, 6), (24, 6), (36, 6), (48, 6)]
        col = (170, 170, 176)
    elif tr > 0:
        paths = [(0, 11), (12, 8), (24, 5), (36, 3), (48, 1)]
        col = (170, 170, 176)
    else:
        paths = [(0, 1), (12, 4), (24, 7), (36, 9), (48, 11)]
        col = (170, 170, 176)
    kx, ky = w / 52.0, h / 14.0
    pts = [(x + px * kx, y + (py + 1) * ky) for px, py in paths]
    for a, b in zip(pts, pts[1:]):
        line(d, a, b, col, 3.2)
    for p in pts[:1] + pts[-1:]:
        disc(d, p[0], p[1], 1.6, col)


# ------------------------------------------------------------------ плитки

TH = 384   # высота плитки


def gauge_tile(d, x, y, w, title, kind, **kw):
    tile(d, x, y, w, TH)
    cx = x + w / 2.0
    tx(d, (cx, y + 38), title, font(25), (150, 150, 156), "mm")
    if kind == "wind":
        wind_gauge(d, cx, y + 58 + 70 * 1.9, 1.9, kw.get("speed"), kw.get("gust"), kw.get("deg"))
        return
    k = 2.3
    cy = y + 72 + 85 * k
    if kind == "temp":
        v = kw.get("v")
        semi_gauge(d, cx, cy, k, v, -20, 40, T_ST, ["-20", "-10", "0", "10", "20", "30", "40"],
                   [(i + .5) / 6 for i in range(6)], "°C", fmt1(v) if v is not None else "—")
    elif kind == "hum":
        v = kw.get("v")
        semi_gauge(d, cx, cy, k, v, 0, 100, H_ST, ["0", "25", "50", "75", "100"], [], "%", "%d" % round(v) if v is not None else "—",
                   major_len=8, major_w=1.8)
    elif kind == "pres":
        v = kw.get("v")
        semi_gauge(d, cx, cy, k, v, 980, 1040, P_ST, ["980", "990", "1000", "1010", "1020", "1030", "1040"],
                   [(i + .5) / 6 for i in range(6)], "гПа", fmt1(v) if v is not None else "—")
        tr = kw.get("trend")
        trend_line(d, cx - 118, y + TH - 74, 118, 32, tr)
        if tr is not None:
            tx(d, (cx - 118 + 118 + 20, y + TH - 58), ("%s%s" % ("+" if tr > 0 else ("−" if tr < 0 else ""), fmt1(abs(tr)))), font(26, True), TXT, "lm")
            tx(d, (cx + 20, y + TH - 28), "гПа за 3 ч", font(20), (130, 130, 136), "lm")
    elif kind == "rrate":
        v = kw.get("v")
        lab = ""
        if v is not None:
            lab = "Нет" if v == 0 else "Следы" if v < .5 else "Слабый" if v < 2 else "Умеренный" if v < 10 else "Сильный" if v < 25 else "Ливень"
        semi_gauge(d, cx, cy, k, v, 0, 50, RR_ST, ["0", "2", "10", "25", "50"], [], "мм/ч", fmt1(v) if v is not None else "—",
                   sub=lab, major_len=8, major_w=1.8)
    elif kind == "rtotal":
        v = kw.get("v")
        semi_gauge(d, cx, cy, k, v, 0, 100, RT_ST, ["0", "5", "20", "50", "100"], [], "мм", fmt1(v) if v is not None else "—",
                   sub=kw.get("sub"), sub_col=(130, 130, 136), major_len=8, major_w=1.8)


def header_pws(d, title, subtitle, badge, temp):
    tx(d, (PAD + 6, 40), title, font(44, True), TXT)
    if subtitle:
        tx(d, (PAD + 6, 100), subtitle, font(23), DIM)
    tc = gcol(T_ST, ((temp if temp is not None else 10) + 20) / 60.0)
    tx(d, (W - PAD - 6, 34), (fmt1(temp) + "°C") if temp is not None else "—", font(78, True), tc, "ra")
    if badge:
        bw = 28 + len(badge) * 14.5
        d.rounded_rectangle(((PAD + 6) * S, 138 * S, (PAD + 6 + bw) * S, 180 * S), radius=21 * S, fill=(28, 52, 38), outline=(62, 130, 90), width=2 * S)
        tx(d, (PAD + 6 + bw / 2, 159), badge, font(22, True), (112, 226, 150), "mm")


def finish(img):
    H = img.size[1] // S
    img = img.resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def footer(g, y, lines):
    if not lines:
        return y
    line(g, (PAD, y + 14), (W - PAD, y + 14), TILE_B, 2)
    y += 40
    for ln in lines:
        tx(g, (PAD + 6, y), ln, font(26), TXT)
        y += 38
    return y


def render_pws(d):
    """d: title, subtitle, badge, temp, hum, wind, gust, wind_dir, pressure, p_trend,
    rain_rate, rain_total, rain_total_sub, lines[]"""
    rain = d.get("rain_rate") is not None or d.get("rain_total") is not None
    lines = d.get("lines") or []
    rows = 3 if rain else 2
    H = 200 + rows * (TH + GAP) + (52 + 38 * len(lines) if lines else 0) + 24
    img = Image.new("RGB", (W * S, H * S), BG)
    g = ImageDraw.Draw(img)
    header_pws(g, d.get("title", "В среднем по городу"), d.get("subtitle"), d.get("badge"), d.get("temp"))
    tw = (W - 2 * PAD - GAP) // 2
    xs = (PAD, PAD + tw + GAP)
    y = 200
    gauge_tile(g, xs[0], y, tw, "Температура", "temp", v=d.get("temp"))
    gauge_tile(g, xs[1], y, tw, "Влажность", "hum", v=d.get("hum"))
    y += TH + GAP
    gauge_tile(g, xs[0], y, tw, "Ветер", "wind", speed=d.get("wind"), gust=d.get("gust"), deg=d.get("wind_dir"))
    gauge_tile(g, xs[1], y, tw, "Давление", "pres", v=d.get("pressure"), trend=d.get("p_trend"))
    y += TH + GAP
    if rain:
        gauge_tile(g, xs[0], y, tw, "Интенсивность", "rrate", v=d.get("rain_rate"))
        gauge_tile(g, xs[1], y, tw, "Осадки", "rtotal", v=d.get("rain_total"), sub=d.get("rain_total_sub"))
        y += TH + GAP
    footer(g, y - GAP + 6, lines)
    return finish(img)


def cloud(d, x, y, sz, drops):
    c = (205, 222, 228)
    disc(d, x + .30 * sz, y + .55 * sz, .22 * sz, c)
    disc(d, x + .52 * sz, y + .38 * sz, .28 * sz, c)
    disc(d, x + .76 * sz, y + .55 * sz, .20 * sz, c)
    d.rounded_rectangle(((x + .28 * sz) * S, (y + .50 * sz) * S, (x + .78 * sz) * S, (y + .75 * sz) * S), radius=int(.12 * sz * S), fill=c)
    if drops:
        for dx, dy in ((.30, .90), (.50, .98), (.70, .90)):
            px, py = x + dx * sz, y + dy * sz
            d.polygon([(px * S, (py - .09 * sz) * S), ((px - .05 * sz) * S, py * S), ((px + .05 * sz) * S, py * S)], fill=(76, 170, 240))
            disc(d, px, py, .05 * sz, (76, 170, 240))


def render_gmc(d):
    """d: obs_local, obs_utc, temp, hum, wind, wind_dir, gust, pressure, p_trend, ww_text, rain (bool), lines[]"""
    lines = d.get("lines") or []
    has_ww = bool(d.get("ww_text"))
    top = 330 + (170 if has_ww else 0)
    H = top + 2 * (TH + GAP) + (52 + 38 * len(lines) if lines else 0) + 24 - GAP
    img = Image.new("RGB", (W * S, H * S), BG)
    g = ImageDraw.Draw(img)
    tx(g, (PAD + 6, 40), "ОДЕССА", font(44, True), TXT)
    tx(g, (PAD + 6, 100), "Гидрометцентр Чёрного и Азовского морей", font(23), DIM)
    tx(g, (PAD + 6, 150), "Наблюдение: %s местное время" % d.get("obs_local", "—"), font(27), (200, 200, 205))
    tx(g, (PAD + 6, 192), "Температура воздуха", font(25), DIM)
    t = d.get("temp")
    tc = gcol(T_ST, ((t if t is not None else 10) + 20) / 60.0)
    tx(g, (PAD + 6, 222), (fmt1(t) + "°C") if t is not None else "—", font(96, True), tc)
    if has_ww:
        txt = d["ww_text"][:1].upper() + d["ww_text"][1:]
        tx(g, (PAD + 6, 410), txt, font(40), TXT, "lm")
        cloud(g, W - PAD - 170, 346, 128, d.get("rain"))
    tw = (W - 2 * PAD - GAP) // 2
    xs = (PAD, PAD + tw + GAP)
    y = top
    gauge_tile(g, xs[0], y, tw, "Температура", "temp", v=t)
    gauge_tile(g, xs[1], y, tw, "Влажность", "hum", v=d.get("hum"))
    y += TH + GAP
    gauge_tile(g, xs[0], y, tw, "Ветер", "wind", speed=d.get("wind"), gust=d.get("gust"), deg=d.get("wind_dir"))
    gauge_tile(g, xs[1], y, tw, "Давление", "pres", v=d.get("pressure"), trend=d.get("p_trend"))
    y += TH
    footer(g, y + 6, lines)
    return finish(img)


if __name__ == "__main__":
    import sys
    pre = sys.argv[1] if len(sys.argv) > 1 else "card"
    open(pre + "_pws.png", "wb").write(render_pws(dict(
        title="В среднем по городу", subtitle="Частные метеостанции", badge="обновлено 13:58", temp=11.5, hum=97, wind=1.4, gust=2.0,
        wind_dir=223, pressure=998.7, p_trend=-3.0, rain_rate=1.0, rain_total=3.8, rain_total_sub="с 11:54",
        lines=["Дождь идёт с 11:54, выпало до 3,8 мм", "Прогноз: осадки закончатся около 21:00"])))
    open(pre + "_gmc.png", "wb").write(render_gmc(dict(
        obs_local="23.11 12:00", temp=12.0, hum=96, wind=3, wind_dir=180, pressure=1001.1, p_trend=-3.0, ww_text="слабый дождь", rain=True,
        lines=["Видимость 10 км", "Осадки за 3 ч: 1,2 мм"])))
