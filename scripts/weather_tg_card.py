# -*- coding: utf-8 -*-
"""Карточка-картинка для постов канала (стиль сайта: тёмные плитки, цветные дуги).
render_card(d) -> bytes PNG. Только Pillow. Шрифт DejaVu Sans (есть на VPS)."""
import io
import math
from PIL import Image, ImageDraw, ImageFont

FD = "/usr/share/fonts/truetype/dejavu/"
S = 2                      # суперсэмплинг
W, PAD, GAP = 1080, 40, 24
BG, TILE, TILE_B = (24, 24, 26), (32, 32, 35), (48, 48, 52)
TXT, DIM = (236, 236, 238), (150, 150, 156)
_fc = {}


def font(sz, bold=False):
    k = (sz, bold)
    if k not in _fc:
        _fc[k] = ImageFont.truetype(FD + ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), int(sz * S))
    return _fc[k]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def ramp(stops, t):
    t = max(0.0, min(1.0, t))
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t <= t1:
            return lerp(c0, c1, (t - t0) / (t1 - t0) if t1 > t0 else 0)
    return stops[-1][1]


TEMP_R = [(0, (66, 133, 244)), (.3, (80, 200, 230)), (.5, (110, 220, 120)), (.7, (250, 200, 60)), (1, (255, 90, 40))]
HUM_R = [(0, (250, 200, 80)), (.5, (100, 220, 150)), (1, (70, 150, 250))]
PRES_R = [(0, (66, 133, 244)), (.45, (110, 220, 120)), (.7, (250, 200, 60)), (1, (255, 90, 40))]
RAIN_R = [(0, (170, 230, 80)), (.4, (60, 170, 250)), (1, (150, 80, 250))]


def tx(d, xy, s, f, fill, anchor="la"):
    d.text((xy[0] * S, xy[1] * S), s, font=f, fill=fill, anchor=anchor)


def tile(d, x, y, w, h):
    d.rounded_rectangle((x * S, y * S, (x + w) * S, (y + h) * S), radius=28 * S, fill=TILE, outline=TILE_B, width=S)


def arc_gauge(d, cx, cy, r, val, vmin, vmax, ramp_stops, label, value, unit, sub=None, ticks=()):
    """Дуга 210°..330° (верхняя полуокружность с запасом), цвет по шкале."""
    a0, a1 = 160, 380
    th = 20
    box = ((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S)
    d.arc(box, a0, a1, fill=(52, 52, 56), width=th * S)
    n = 90
    frac = 0 if val is None else max(0, min(1, (val - vmin) / float(vmax - vmin)))
    for i in range(n):
        t0, t1 = i / n, (i + 1) / n
        c = ramp(ramp_stops, t0)
        if t0 <= frac or val is None:
            pass
        if val is not None and t0 < frac:
            d.arc(box, a0 + (a1 - a0) * t0, a0 + (a1 - a0) * min(t1 + 0.004, frac if t1 > frac else 1), fill=c, width=th * S)
    # засечки
    for tv in ticks:
        t = (tv - vmin) / float(vmax - vmin)
        a = math.radians(a0 + (a1 - a0) * t)
        r1, r2 = r - th / 2 - 6, r - th / 2 - 16
        d.line(((cx + r1 * math.cos(a)) * S, (cy + r1 * math.sin(a)) * S,
                (cx + r2 * math.cos(a)) * S, (cy + r2 * math.sin(a)) * S), fill=(110, 110, 116), width=2 * S)
    col = ramp(ramp_stops, frac) if val is not None else DIM
    tx(d, (cx, cy - r - 34), label, font(26), DIM, "mm")
    tx(d, (cx, cy - 22), value, font(54, True), col, "mm")
    tx(d, (cx, cy + 22), unit, font(22), DIM, "mm")
    if sub:
        tx(d, (cx, cy + 56), sub[0], font(22), sub[1] if len(sub) > 1 else DIM, "mm")


def wind_gauge(d, cx, cy, r, speed, gust, deg):
    d.ellipse(((cx - r) * S, (cy - r) * S, (cx + r) * S, (cy + r) * S), outline=(86, 160, 170), width=7 * S)
    for k in range(16):
        a = math.radians(k * 22.5 - 90)
        major = k % 4 == 0
        r1, r2 = r + (8 if major else 6), r + (20 if major else 13)
        d.line(((cx + r1 * math.cos(a)) * S, (cy + r1 * math.sin(a)) * S,
                (cx + r2 * math.cos(a)) * S, (cy + r2 * math.sin(a)) * S),
               fill=(120, 120, 126) if major else (80, 80, 86), width=(3 if major else 2) * S)
    for s_, (dx, dy) in (("С", (0, -1)), ("В", (1, 0)), ("Ю", (0, 1)), ("З", (-1, 0))):
        tx(d, (cx + dx * (r + 40), cy + dy * (r + 40)), s_, font(22), DIM, "mm")
    tx(d, (cx, cy - r - 66), "Ветер", font(26), DIM, "mm")
    col = ramp([(0, (110, 220, 150)), (.4, (250, 200, 60)), (1, (255, 90, 40))], (speed or 0) / 15.0)
    tx(d, (cx, cy - 34), "м/с", font(20), DIM, "mm")
    tx(d, (cx, cy + 2), ("%.1f" % speed).replace(".", ",") if speed is not None else "—", font(48, True), col, "mm")
    if gust is not None and gust > (speed or 0) + 0.4:
        gc = (255, 120, 60) if gust >= 8 else (150, 210, 160)
        tx(d, (cx, cy + 38), ("порыв %.1f" % gust).replace(".", ","), font(19, True), gc, "mm")
    if deg is not None:
        a = math.radians(deg - 90)
        rt = r + 2
        tip = (cx + (rt - 2) * math.cos(a), cy + (rt - 2) * math.sin(a))
        bl = [(cx + (rt - 36) * math.cos(a + da), cy + (rt - 36) * math.sin(a + da)) for da in (0.30, -0.30)]
        d.polygon([(tip[0] * S, tip[1] * S)] + [(p[0] * S, p[1] * S) for p in bl], fill=(240, 240, 244))
        pts = ["С", "ССВ", "СВ", "ВСВ", "В", "ВЮВ", "ЮВ", "ЮЮВ", "Ю", "ЮЮЗ", "ЮЗ", "ЗЮЗ", "З", "ЗСЗ", "СЗ", "ССЗ"]
        tx(d, (cx, cy + r + 66), "%s · %d°" % (pts[int((deg % 360) / 22.5 + .5) % 16], round(deg)), font(24), TXT, "mm")


def pressure_sub(trend):
    if trend is None:
        return None
    if abs(trend) < 0.1:
        return ("за 3 ч без изменений", DIM)
    arrow = "▲" if trend > 0 else "▼"
    return ("%s %s%.1f гПа за 3 ч" % (arrow, "+" if trend > 0 else "−", abs(trend)),
            (110, 220, 150) if trend > 0 else (250, 150, 90))


def render_card(d):
    """d: title, subtitle, time, temp, hum, wind, gust, wind_dir, pressure, p_trend,
    rain_rate (мм/ч или None), rain_total (мм или None), rain_label, lines[] (подвал), badge"""
    show_rain = d.get("rain_rate") is not None or d.get("rain_total") is not None
    lines = d.get("lines") or []
    H = 40 + 130 + 24 + 2 * 380 + GAP + (380 + GAP if show_rain else 0) + (40 + 38 * len(lines) if lines else 0) + 40
    img = Image.new("RGB", (W * S, H * S), BG)
    g = ImageDraw.Draw(img)
    # шапка
    tx(g, (PAD, 44), d.get("title", "Одесса"), font(46, True), TXT)
    tx(g, (PAD, 104), d.get("subtitle", ""), font(24), DIM)
    t = d.get("temp")
    tcol = ramp(TEMP_R, ((t if t is not None else 10) + 20) / 60.0)
    tx(g, (W - PAD, 38), ("%.1f°C" % t).replace(".", ",") if t is not None else "—", font(84, True), tcol, "ra")
    if d.get("badge"):
        bw = 24 + len(d["badge"]) * 14
        g.rounded_rectangle((PAD * S, 140 * S, (PAD + bw) * S, 180 * S), radius=20 * S, fill=(30, 60, 42), outline=(60, 130, 90), width=2 * S)
        tx(g, (PAD + bw / 2, 160), d["badge"], font(22, True), (110, 225, 150), "mm")
    y = 200
    tw = (W - 2 * PAD - GAP) // 2
    th = 380
    xs = (PAD, PAD + tw + GAP)
    # ряд 1: температура / влажность
    for x in xs:
        tile(g, x, y, tw, th)
    cx0, cx1 = xs[0] + tw / 2, xs[1] + tw / 2
    arc_gauge(g, cx0, y + 220, 125, t, -20, 40, TEMP_R, "Температура", ("%.1f" % t).replace(".", ",") if t is not None else "—", "°C",
              ticks=(-10, 0, 10, 20, 30))
    h = d.get("hum")
    arc_gauge(g, cx1, y + 220, 125, h, 0, 100, HUM_R, "Влажность", "%d" % round(h) if h is not None else "—", "%", ticks=(25, 50, 75))
    y += th + GAP
    for x in xs:
        tile(g, x, y, tw, th)
    wind_gauge(g, cx0, y + 195, 90, d.get("wind"), d.get("gust"), d.get("wind_dir"))
    p = d.get("pressure")
    arc_gauge(g, cx1, y + 220, 125, p, 980, 1040, PRES_R, "Давление", ("%.1f" % p).replace(".", ",") if p is not None else "—", "гПа",
              sub=pressure_sub(d.get("p_trend")), ticks=(990, 1000, 1010, 1020, 1030))
    y += th + GAP
    if show_rain:
        for x in xs:
            tile(g, x, y, tw, th)
        rr = d.get("rain_rate")
        arc_gauge(g, cx0, y + 220, 125, rr, 0, 10, RAIN_R, "Интенсивность", ("%.1f" % rr).replace(".", ",") if rr is not None else "—", "мм/ч",
                  sub=(d.get("rain_label"), (170, 230, 80)) if d.get("rain_label") else None, ticks=(2, 5))
        rt = d.get("rain_total")
        arc_gauge(g, cx1, y + 220, 125, rt, 0, 50, RAIN_R, d.get("rain_total_label", "Осадки"), ("%.1f" % rt).replace(".", ",") if rt is not None else "—", "мм",
                  ticks=(5, 20))
        y += th + GAP
    if lines:
        g.line((PAD * S, (y + 4) * S, (W - PAD) * S, (y + 4) * S), fill=TILE_B, width=2 * S)
        y += 28
        for ln in lines:
            tx(g, (PAD, y), ln, font(26), TXT)
            y += 38
    img = img.resize((W, H), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


if __name__ == "__main__":
    import sys
    demo = dict(title="Одесса", subtitle="Частные метеостанции · 13:58", badge="обновлено 13:58", temp=11.5, hum=97, wind=1.4, gust=2.0,
                wind_dir=223, pressure=998.7, p_trend=-3.0, rain_rate=1.0, rain_label="Слабый", rain_total=3.8, rain_total_label="Осадки с 11:54",
                lines=["Дождь идёт с 11:54, выпало до 3,8 мм", "Прогноз: осадки закончатся около 21:00"])
    open(sys.argv[1] if len(sys.argv) > 1 else "card.png", "wb").write(render_card(demo))
