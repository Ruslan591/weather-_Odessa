#!/usr/bin/env python3
"""
make_video.py — вертикальное видео 9:16 для TikTok/Reels из блоков blocks_meta.json.
Хедер с карточкой статичен, текст блока плавно прокручивается снизу вверх
(караоке-стиль), синхронизирован с длительностью озвучки блока целиком —
без разбивки на страницы и без разрывов по предложениям.
"""

import json, os, re, math, glob, sys, subprocess
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── Источник блоков: "claude" (по умолчанию) или "gemini" ────────────────────
SOURCE = sys.argv[1] if len(sys.argv) > 1 else "claude"
if SOURCE not in ("claude", "gemini"):
    print(f"  Неизвестный источник '{SOURCE}', используем 'claude'"); SOURCE = "claude"

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCKS_DIR = os.path.join(BASE_DIR, "data", "blocks" if SOURCE == "claude" else "blocks_gemini")
ICONS_DIR  = os.path.join(BASE_DIR, "data", "icons")
META_FILE  = os.path.join(BLOCKS_DIR, "blocks_meta.json")
TMP_DIR    = os.path.join(BLOCKS_DIR, "tmp")
MP4_FILE   = os.path.join(BASE_DIR, "data",
                           "forecast_video.mp4" if SOURCE == "claude" else "forecast_video_gemini.mp4")
ENSEMBLE_PWS_FILE = os.path.join(BASE_DIR, "data", "ensemble_snapshots_pws.json")
BG_MUSIC_FILE = os.path.join(BASE_DIR, "data", "audio", "bg_ambient.mp3")
BG_MUSIC_VOLUME = 0.10  # тихая подложка под озвучку, не должна конкурировать с речью
LOCAL_OFFSET_H = 3  # Одесса летом = UTC+3 (сверено с реальным сайтом: 06:00 UTC+3 = минимум суток)

W, H = 1080, 1920

# ── Шрифт: Carlito (метрически совместим с Calibri), проверенная кириллица ──
def _find_font_dir():
    candidates = [
        "/usr/share/fonts/truetype/crosextra",
        "/usr/share/fonts/crosextra-carlito",
    ]
    for c in candidates:
        if os.path.exists(os.path.join(c, "Carlito-Regular.ttf")):
            return c
    found = glob.glob("/usr/share/fonts/**/Carlito-Regular.ttf", recursive=True)
    if found:
        return os.path.dirname(found[0])
    return None

FONT_DIR = _find_font_dir()
if not FONT_DIR:
    print("  ОШИБКА: шрифт Carlito не найден (нужен пакет fonts-crosextra-carlito)")
    sys.exit(1)

def F(size, weight="regular"):
    fname = "Carlito-Bold.ttf" if weight in ("bold", "semibold") else "Carlito-Regular.ttf"
    return ImageFont.truetype(os.path.join(FONT_DIR, fname), size)

def _verify_font_renders_cyrillic():
    """Защита от повторения истории с Poppins: убеждаемся, что шрифт реально
    рисует разные глифы для разных кириллических букв, а не однотипный тофу-бокс."""
    import numpy as np
    font = ImageFont.truetype(os.path.join(FONT_DIR, "Carlito-Bold.ttf"), 60)
    chars = "АБВГДЖЗИЙКЛМНОПРСТУФХЦЧШЩЭЮЯ"
    shapes = set(np.array(font.getmask(ch)).tobytes() for ch in chars)
    if len(shapes) < len(chars) * 0.8:
        raise RuntimeError("Шрифт не поддерживает кириллицу (тофу-глифы)! Проверь FONT_DIR.")
_verify_font_renders_cyrillic()

THEMES = {
    "today":        {"top": (10, 22, 48),  "bot": (18, 40, 78),  "accent": (86, 176, 255),  "glow": (50, 120, 220)},
    "tomorrow":     {"top": (8, 32, 30),   "bot": (14, 56, 50),  "accent": (110, 224, 180), "glow": (30, 140, 100)},
    "next3":        {"top": (34, 24, 8),   "bot": (58, 42, 12),  "accent": (255, 179, 71),  "glow": (200, 110, 20)},
    "warnings":     {"top": (42, 12, 10),  "bot": (72, 20, 16),  "accent": (255, 99, 81),   "glow": (200, 40, 20)},
    "trend":        {"top": (24, 14, 44),  "bot": (40, 22, 72),  "accent": (196, 140, 255), "glow": (110, 50, 190)},
    "marine":       {"top": (6, 26, 42),   "bot": (10, 46, 70),  "accent": (76, 210, 235),  "glow": (20, 130, 170)},
    "verification": {"top": (16, 20, 30),  "bot": (26, 32, 48),  "accent": (150, 190, 255), "glow": (70, 90, 160)},
}
DEFAULT_THEME = THEMES["today"]

# ── Окно прокрутки текста (фиксированные координаты кадра) ──────────────────
TEXT_TOP, TEXT_BOTTOM = 700, 1790
TEXT_X0, TEXT_X1 = 96, W - 96

START_DELAY = 15.0   # сек — статичная пауза перед началом прокрутки
END_HOLD    = 1.5    # сек — последняя часть текста остаётся видимой
FADE_IN_DUR  = 1.2   # сек — плавное появление текста в начале
FADE_OUT_DUR = 1.2   # сек — плавное затухание текста в самом конце

def clean_text(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def wrap_text(text, font, maxw, draw):
    words = text.split()
    lines = []; cur = []
    for w in words:
        t = ' '.join(cur + [w])
        if draw.textbbox((0, 0), t, font=font)[2] > maxw and cur:
            lines.append(' '.join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur: lines.append(' '.join(cur))
    return lines

_TEMP_RE = re.compile(
    r'(-?\d{1,2}(?:[.,]\d)?)\s*(?:[-–—]\s*(-?\d{1,2}(?:[.,]\d)?))?\s*°C'
)

def extract_temp_range(text):
    """Ищет упоминания температуры вида "16°C" и диапазоны вида "15-16°C"
    или "23–25°C". Дефис/тире между двумя числами — это разделитель диапазона,
    а не знак минуса (что раньше приводило к ложным отрицательным значениям)."""
    nums = []
    for m in _TEMP_RE.finditer(text):
        for g in (m.group(1), m.group(2)):
            if g:
                v = float(g.replace(',', '.'))
                if -20 <= v <= 45:
                    nums.append(v)
    if not nums: return None, None
    return min(nums), max(nums)

def ease_in_out_cubic(x):
    """Плавный разгон в начале и плавное торможение в конце (0..1 → 0..1)."""
    x = max(0.0, min(1.0, x))
    return 4*x**3 if x < 0.5 else 1 - pow(-2*x + 2, 3) / 2

_ensemble_cache = None

def _load_ensemble_hours():
    global _ensemble_cache
    if _ensemble_cache is not None:
        return _ensemble_cache
    try:
        with open(ENSEMBLE_PWS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        snap = data[-1]
        by_time_utc = {h['time']: h.get('temp') for h in snap['hours'] if h.get('temp') is not None}
        _ensemble_cache = by_time_utc
    except Exception as e:
        print(f"  [CHART] ensemble_snapshots_pws.json не загружен: {e}")
        _ensemble_cache = {}
    return _ensemble_cache

def get_temp_curve(key):
    """Почасовая кривая температуры (локальное время) для графика под карточкой.
    Возвращает список [(local_hour_label, temp), ...] или None, если для этого
    блока график не нужен (недостаточно данных / блок не про почасовую температуру)."""
    by_time_utc = _load_ensemble_hours()
    if not by_time_utc:
        return None

    now_utc = datetime.utcnow()
    now_local = now_utc + timedelta(hours=LOCAL_OFFSET_H)

    def utc_key(dt_local):
        dt_utc = dt_local - timedelta(hours=LOCAL_OFFSET_H)
        return dt_utc.strftime("%Y-%m-%dT%H:00")

    if key == "today":
        start = now_local.replace(minute=0, second=0, microsecond=0)
        end_hour = min(23, start.hour + 15)
        hours = [start.replace(hour=h) for h in range(start.hour, end_hour+1)]
    elif key == "tonight":
        start = now_local.replace(minute=0, second=0, microsecond=0)
        hours = [start + timedelta(hours=i) for i in range(0, 13)]
    elif key == "tomorrow":
        tmr = (now_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        hours = [tmr.replace(hour=h) for h in range(0, 24, 2)]
    else:
        # next3 / marine / trend / verification / warnings — почасовой график
        # температуры для них пока не строим (нужна другая визуализация:
        # по-дневные min/max, волны, текстовая тенденция — это отдельная задача)
        return None

    pts = []
    for dt in hours:
        k = utc_key(dt)
        if k in by_time_utc:
            pts.append((dt.strftime("%H:%M"), by_time_utc[k]))
    if len(pts) < 3:
        return None
    return pts

def weather_icon_path(text, key):
    t = text.lower()
    if key == 'marine': return os.path.join(ICONS_DIR, 'wave.png')
    if key == 'trend':  return os.path.join(ICONS_DIR, 'trend.png')
    if key == 'next3':  return os.path.join(ICONS_DIR, 'calendar.png')
    if key == 'verification': return os.path.join(ICONS_DIR, 'trend.png')
    if 'гроза' in t or 'молния' in t: return os.path.join(ICONS_DIR, 'thunder.png')
    if 'дождь' in t or 'осадки' in t: return os.path.join(ICONS_DIR, 'rain.png')
    if 'облачно' in t or 'облака' in t: return os.path.join(ICONS_DIR, 'cloudy.png')
    if 'ясно' in t or 'солнечно' in t: return os.path.join(ICONS_DIR, 'sunny.png')
    return os.path.join(ICONS_DIR, 'partly_cloudy.png')

def paste_icon(img, icon_path, cx, cy, size=180):
    if not os.path.exists(icon_path): return
    icon = Image.open(icon_path).convert('RGBA').resize((size, size), Image.LANCZOS)
    img.paste(icon, (cx - size//2, cy - size//2), icon)

def gradient_color_at(y_frac, top, bot):
    t = max(0, min(1, y_frac)) ** 0.92
    return tuple(int(top[i] + (bot[i]-top[i])*t) for i in range(3))

def draw_gradient(draw, top, bot):
    for y in range(H):
        draw.line([(0, y), (W, y)], fill=gradient_color_at(y/H, top, bot))

def draw_soft_blob(img, cx, cy, radius, color, alpha_max=70):
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.ellipse([cx-radius, cy-radius, cx+radius, cy+radius], fill=(*color, alpha_max))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius * 0.55))
    img.alpha_composite(overlay)

def rounded_glass_card(img, x, y, w, h, radius, accent, fill_alpha=52, border_alpha=70):
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    d.rounded_rectangle([x, y, x+w, y+h], radius=radius, fill=(255, 255, 255, fill_alpha))
    d.rounded_rectangle([x, y, x+w, y+h], radius=radius, outline=(*accent, border_alpha), width=2)
    img.alpha_composite(overlay)

DECORATIVE_INTRO_KEYS = {"next3", "warnings", "trend", "marine", "verification"}

def draw_intro_decoration(img, theme, key, x0, x1, y0, y1, reveal_frac):
    """Декоративная интро-анимация для блоков без почасового графика
    температуры. Чисто визуальный акцент под тему блока — никаких цифр
    рейтинга/точности/bias моделей (даже в verification это просто образ
    "проверено", без конкретных значений)."""
    acc = theme["accent"]
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    if key == "next3":
        n = 3
        gap = 36
        chip_w = (x1 - x0 - (n-1)*gap) / n
        chip_h = y1 - y0
        for i in range(n):
            local = max(0.0, min(1.0, reveal_frac*n - i))
            if local <= 0:
                continue
            ease = ease_in_out_cubic(local)
            cx0 = x0 + i*(chip_w+gap)
            offset_y = (1-ease) * 36
            alpha = int(255*ease)
            top = y0 + offset_y
            d.rounded_rectangle([cx0, top, cx0+chip_w, top+chip_h], radius=22,
                                 fill=(255, 255, 255, int(38*ease)),
                                 outline=(*acc, alpha), width=2)
            d.text((cx0+chip_w/2, top+chip_h*0.42), f"ДЕНЬ {i+1}",
                    font=F(26, "bold"), fill=(*acc, alpha), anchor="mm")
            dots_y = top + chip_h*0.68
            for k in range(3):
                dk = max(0.0, min(1.0, local*3 - k))
                if dk <= 0:
                    continue
                dot_x = cx0 + chip_w/2 + (k-1)*22
                r = 6
                d.ellipse([dot_x-r, dots_y-r, dot_x+r, dots_y+r],
                          fill=(*acc, int(255*dk)))

    elif key == "warnings":
        cx, cy = (x0+x1)/2, (y0+y1)/2
        max_r = min(x1-x0, y1-y0) * 0.42
        for ring_i in range(2):
            phase = (reveal_frac*1.8 - ring_i*0.5) % 1.0
            r = phase * max_r
            alpha = int(180 * (1-phase))
            if alpha <= 2 or r < 4:
                continue
            d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(*acc, alpha), width=6)
        pulse = 0.5 + 0.5*math.sin(reveal_frac*math.pi*8)
        core_r = 16 + 5*pulse
        d.ellipse([cx-core_r, cy-core_r, cx+core_r, cy+core_r], fill=(*acc, 230))

    elif key == "trend":
        pts_n = 6
        xs = [x0 + (x1-x0)*i/(pts_n-1) for i in range(pts_n)]
        rel = [0.72, 0.52, 0.62, 0.34, 0.44, 0.16]
        ys = [y1 - r*(y1-y0) for r in rel]
        exact = reveal_frac * (pts_n-1)
        full_i = int(math.floor(exact))
        frac_l = exact - full_i
        dxs, dys = xs[:full_i+1], ys[:full_i+1]
        if full_i < pts_n-1:
            ax, ay = xs[full_i], ys[full_i]
            bx, by = xs[full_i+1], ys[full_i+1]
            dxs.append(ax+(bx-ax)*frac_l)
            dys.append(ay+(by-ay)*frac_l)
        if len(dxs) >= 2:
            d.line(list(zip(dxs, dys)), fill=(*acc, 255), width=8, joint="curve")
            if reveal_frac > 0.04:
                tx, ty = dxs[-1], dys[-1]
                px, py = dxs[-2], dys[-2]
                ang = math.atan2(ty-py, tx-px)
                al = 22
                a1, a2 = ang+math.radians(150), ang-math.radians(150)
                p1 = (tx+al*math.cos(a1), ty+al*math.sin(a1))
                p2 = (tx+al*math.cos(a2), ty+al*math.sin(a2))
                d.polygon([(tx, ty), p1, p2], fill=(*acc, 255))

    elif key == "marine":
        for amp_frac, freq, alpha, speed, y_bias in (
            (0.30, 2.0, 150, 2.6, 0.5), (0.18, 3.0, 95, 4.0, 0.68)
        ):
            amp = (y1-y0) * amp_frac / 2
            mid_y = y0 + (y1-y0)*y_bias
            phase = reveal_frac * speed * 2*math.pi
            n_pts = 60
            pts = []
            for i in range(n_pts+1):
                xf = i/n_pts
                xx = x0 + (x1-x0)*xf
                yy = mid_y + amp * math.sin(xf*freq*2*math.pi + phase)
                pts.append((xx, yy))
            d.line(pts, fill=(*acc, alpha), width=6, joint="curve")

    elif key == "verification":
        d.rounded_rectangle([x0, y0, x1, y1], radius=20, outline=(*acc, 90), width=2)
        if reveal_frac < 0.7:
            scan_y = y0 + (y1-y0) * min(reveal_frac/0.7, 1.0)
            d.line([(x0, scan_y), (x1, scan_y)], fill=(*acc, 235), width=5)
        else:
            prog = max(0.0, min(1.0, (reveal_frac-0.7)/0.3))
            ccx, ccy = (x0+x1)/2, (y0+y1)/2
            size = min(x1-x0, y1-y0) * 0.34
            p1 = (ccx-size*0.5, ccy)
            p2 = (ccx-size*0.12, ccy+size*0.4)
            p3 = (ccx+size*0.55, ccy-size*0.45)
            seg1 = 0.4
            if prog <= seg1:
                t = prog/seg1
                mx, my = p1[0]+(p2[0]-p1[0])*t, p1[1]+(p2[1]-p1[1])*t
                d.line([p1, (mx, my)], fill=(*acc, 255), width=14, joint="curve")
            else:
                d.line([p1, p2], fill=(*acc, 255), width=14, joint="curve")
                t = (prog-seg1)/(1-seg1)
                mx, my = p2[0]+(p3[0]-p2[0])*t, p2[1]+(p3[1]-p2[1])*t
                d.line([p2, (mx, my)], fill=(*acc, 255), width=14, joint="curve")

    img.alpha_composite(overlay)

def build_chrome(block, theme, out_path, reveal_frac=1.0):
    """Статичная часть кадра: фон + карточка + хедер, с прозрачным окном под
    прокручивающийся текст. Все декоративные элементы рисуются с alpha=255,
    а после отрисовки альфа принудительно нормализуется — это защита от
    случайных полупрозрачных «дыр» (см. историю багов с разделителем).
    reveal_frac (0..1) управляет прогрессивной прорисовкой графика температуры
    и счётчиком мин/макс в шапке — используется только для нескольких первых
    кадров интро; для финального статичного кадра передаётся 1.0."""
    key = block.get("key", "today")
    title = block.get("title", "")
    text = block.get("text", "")
    acc, glow = theme["accent"], theme["glow"]

    img = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    draw_gradient(draw, theme["top"], theme["bot"])
    draw_soft_blob(img, int(W*0.82), 260, 420, glow, alpha_max=55)
    draw_soft_blob(img, int(W*0.1), int(H*0.75), 520, glow, alpha_max=35)
    draw = ImageDraw.Draw(img)

    bar_x0, bar_x1, bar_y0, bar_y1 = 48, W-48, 64, 70
    bar_bg = gradient_color_at((bar_y0+bar_y1)/2/H, theme["top"], theme["bot"])
    bar_w = bar_x1 - bar_x0
    for i in range(bar_w):
        factor = math.sin(math.pi*i/bar_w)
        r = int(bar_bg[0] + (acc[0]-bar_bg[0])*factor)
        g = int(bar_bg[1] + (acc[1]-bar_bg[1])*factor)
        b = int(bar_bg[2] + (acc[2]-bar_bg[2])*factor)
        draw.line([(bar_x0+i, bar_y0), (bar_x0+i, bar_y1)], fill=(r, g, b, 255))
    draw.text((W//2, 108), "ОДЕССА", font=F(26, "semibold"), fill=(*acc, 200), anchor="mm")

    card_x, card_y, card_w, card_h = 44, 150, W-88, 250
    rounded_glass_card(img, card_x, card_y, card_w, card_h, radius=36, accent=acc)
    draw = ImageDraw.Draw(img)

    icon_cx, icon_cy, icon_r = card_x+95, card_y+95, 62
    draw_soft_blob(img, icon_cx, icon_cy, icon_r+30, acc, alpha_max=90)
    draw = ImageDraw.Draw(img)
    draw.ellipse([icon_cx-icon_r, icon_cy-icon_r, icon_cx+icon_r, icon_cy+icon_r], fill=(255, 255, 255, 235))
    paste_icon(img, weather_icon_path(text, key), icon_cx, icon_cy, size=78)
    draw = ImageDraw.Draw(img)

    draw.text((card_x+185, card_y+62), title, font=F(50, "bold"), fill=(255, 255, 255, 255), anchor="lm")
    draw.text((card_x+187, card_y+108), datetime.now().strftime("%d.%m"), font=F(28, "medium"), fill=(*acc, 220), anchor="lm")

    t_min, t_max = extract_temp_range(text)
    temp_str = ""
    if t_min is not None and t_max is not None and t_min != t_max:
        shown_min = t_min * min(reveal_frac*1.3, 1.0) if reveal_frac < 1.0 else t_min
        shown_max = t_max * min(reveal_frac*1.3, 1.0) if reveal_frac < 1.0 else t_max
        temp_str = f"{round(shown_min)}°–{round(shown_max)}°"
    elif t_max is not None:
        shown_max = t_max * min(reveal_frac*1.3, 1.0) if reveal_frac < 1.0 else t_max
        temp_str = f"{round(shown_max)}°"
    if temp_str:
        draw.text((card_x+card_w-30, card_y+85), temp_str, font=F(74, "bold"), fill=(*acc, 255), anchor="rm")

    if key == "marine":
        sst = re.search(r'(\d+[.,]\d+)°C', text)
        if sst:
            draw.text((card_x+card_w/2, card_y+card_h-40), f"Вода {sst.group(1)}°C",
                      font=F(34, "bold"), fill=(*acc, 255), anchor="mm")

    div_y = card_y+card_h+34
    bg_row = gradient_color_at(div_y/H, theme["top"], theme["bot"])
    for i in range(W-88):
        factor = math.sin(math.pi*i/(W-88))
        r = int(bg_row[0] + (acc[0]-bg_row[0])*factor)
        g = int(bg_row[1] + (acc[1]-bg_row[1])*factor)
        b = int(bg_row[2] + (acc[2]-bg_row[2])*factor)
        draw.point((44+i, div_y), fill=(r, g, b, 255))

    # ── график температуры / декоративная интро-анимация в зазоре между
    # карточкой и окном текста ──
    chart_x0, chart_x1 = TEXT_X0, TEXT_X1
    chart_y0, chart_y1 = div_y + 55, TEXT_TOP - 55
    curve = get_temp_curve(key)
    if curve:
        label_pad = 40
        c_temps = [p[1] for p in curve]
        n_pts = len(c_temps)
        xs_full = [chart_x0 + (chart_x1-chart_x0) * i/(n_pts-1) for i in range(n_pts)]
        c_min, c_max = min(c_temps), max(c_temps)
        span = max(c_max - c_min, 3)
        def y_of(t):
            frac = (t - c_min) / span
            return chart_y1 - label_pad - frac * (chart_y1 - chart_y0 - 2*label_pad)
        ys_full = [y_of(t) for t in c_temps]

        exact_pos = reveal_frac * (n_pts - 1)
        full_idx = int(math.floor(exact_pos))
        frac_last = exact_pos - full_idx
        xs = xs_full[:full_idx+1]
        ys = ys_full[:full_idx+1]
        if full_idx < n_pts - 1:
            x0, y0 = xs_full[full_idx], ys_full[full_idx]
            x1, y1 = xs_full[full_idx+1], ys_full[full_idx+1]
            xs.append(x0 + (x1-x0)*frac_last)
            ys.append(y0 + (y1-y0)*frac_last)

        if len(xs) >= 2:
            fill_overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
            fd = ImageDraw.Draw(fill_overlay)
            poly = list(zip(xs, ys)) + [(xs[-1], chart_y1), (chart_x0, chart_y1)]
            fd.polygon(poly, fill=(*acc, 70))
            fill_overlay = fill_overlay.filter(ImageFilter.GaussianBlur(2))
            img.alpha_composite(fill_overlay)
            draw = ImageDraw.Draw(img)

            glow_overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
            gd = ImageDraw.Draw(glow_overlay)
            gd.line(list(zip(xs, ys)), fill=(*acc, 255), width=14, joint="curve")
            glow_overlay = glow_overlay.filter(ImageFilter.GaussianBlur(6))
            img.alpha_composite(glow_overlay)
            draw = ImageDraw.Draw(img)

            draw.line(list(zip(xs, ys)), fill=(*acc, 255), width=8, joint="curve")
            core = tuple(min(255, c+70) for c in acc)
            draw.line(list(zip(xs, ys)), fill=(*core, 200), width=3, joint="curve")

        imin, imax = c_temps.index(min(c_temps)), c_temps.index(max(c_temps))
        for idx, label_above in ((imax, True), (imin, False)):
            if idx <= exact_pos:
                px, py = xs_full[idx], ys_full[idx]
                draw.ellipse([px-9, py-9, px+9, py+9], fill=(255, 255, 255, 255))
                draw.ellipse([px-9, py-9, px+9, py+9], outline=(*acc, 255), width=3)
                ty = py - 30 if label_above else py + 30
                draw.text((px, ty), f"{round(c_temps[idx])}°", font=F(32, "bold"),
                          fill=(255, 255, 255, 255), anchor="mm")
    elif key in DECORATIVE_INTRO_KEYS:
        draw_intro_decoration(img, theme, key, chart_x0, chart_x1, chart_y0, chart_y1, reveal_frac)
        draw = ImageDraw.Draw(img)

    now_str = datetime.now().strftime("%d.%m.%Y")
    draw.text((W//2, H-64), f"Синоптический прогноз  ·  {now_str}",
              font=F(26, "medium"), fill=(255, 255, 255, 130), anchor="mm")

    # ── нормализация альфы: полная непрозрачность везде, кроме окна текста ──
    import numpy as np
    arr = np.array(img)
    arr[:, :, 3] = 255
    arr[TEXT_TOP:TEXT_BOTTOM, :, 3] = 0
    img = Image.fromarray(arr, 'RGBA')
    img.save(out_path, 'PNG')

def build_textstrip(text, theme, out_path):
    """Длинная лента текста на сплошном фоне, соответствующем цвету окна."""
    font = F(58, "regular")
    dummy = Image.new("RGB", (10, 10))
    dd = ImageDraw.Draw(dummy)
    maxw = TEXT_X1 - TEXT_X0
    clean = clean_text(text)
    paragraphs = [p.strip() for p in clean.replace('\n\n', '\n').split('\n') if p.strip()]
    lines = []
    for p in paragraphs:
        lines.extend(wrap_text(p, font, maxw, dd))
        lines.append('')
    while lines and lines[-1] == '':
        lines.pop()

    LINE_H = 92
    PAD_TOP = 40
    PAD_BOTTOM = 400
    strip_h = PAD_TOP + len(lines)*LINE_H + PAD_BOTTOM

    bg_color = gradient_color_at((TEXT_TOP+TEXT_BOTTOM)/2/H, theme["top"], theme["bot"])
    strip = Image.new("RGB", (W, strip_h), bg_color)
    d = ImageDraw.Draw(strip)
    y = PAD_TOP
    for line in lines:
        if not line:
            y += LINE_H//2
            continue
        d.text((TEXT_X0, y), line, font=font, fill=(228, 238, 248))
        y += LINE_H
    strip.save(out_path, "PNG")
    return strip_h

def render_block_video(chrome_png, textstrip_png, strip_h, audio_path, theme, out_mp4,
                        intro_pattern=None, intro_fps=25, intro_dur=0.0, min_duration=6.0):
    window_h = TEXT_BOTTOM - TEXT_TOP
    max_scroll = max(0, strip_h - window_h)

    if audio_path and os.path.exists(audio_path):
        dur_str = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            capture_output=True, text=True).stdout.strip()
        dur = float(dur_str) if dur_str else min_duration
    else:
        dur = min_duration
    dur = max(dur, min_duration)

    scroll_time = max(0.1, dur - START_DELAY - END_HOLD)
    bg_color = gradient_color_at((TEXT_TOP+TEXT_BOTTOM)/2/H, theme["top"], theme["bot"])
    hexcolor = '0x%02x%02x%02x' % bg_color
    y_expr = f"{TEXT_TOP}-min(max(t-{START_DELAY},0)/{scroll_time}*{max_scroll},{max_scroll})"
    fade_start = max(0, dur - FADE_OUT_DUR)

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=size={W}x{H}:color={hexcolor}",
        "-loop", "1", "-i", textstrip_png,
        "-loop", "1", "-i", chrome_png,
    ]

    use_intro = bool(intro_pattern)
    if use_intro:
        cmd += ["-framerate", str(intro_fps), "-i", intro_pattern]
        base_filter = (
            f"[1:v]fade=t=in:st=0:d={FADE_IN_DUR}:color={hexcolor},"
            f"fade=t=out:st={fade_start}:d={FADE_OUT_DUR}:color={hexcolor}[txtfade];"
            f"[0:v][txtfade]overlay=x=0:y='{y_expr}':shortest=0[bg1];"
            f"[bg1][2:v]overlay=x=0:y=0:shortest=1[bg2];"
            f"[bg2][3:v]overlay=x=0:y=0:enable='lt(t,{intro_dur})'[v]"
        )
        next_input_idx = 4
    else:
        base_filter = (
            f"[1:v]fade=t=in:st=0:d={FADE_IN_DUR}:color={hexcolor},"
            f"fade=t=out:st={fade_start}:d={FADE_OUT_DUR}:color={hexcolor}[txtfade];"
            f"[0:v][txtfade]overlay=x=0:y='{y_expr}':shortest=0[bg1];"
            f"[bg1][2:v]overlay=x=0:y=0:shortest=1[v]"
        )
        next_input_idx = 3

    has_voice = bool(audio_path and os.path.exists(audio_path))
    has_bg_music = os.path.exists(BG_MUSIC_FILE)

    if has_voice:
        cmd += ["-i", audio_path]
        voice_idx = next_input_idx
        next_input_idx += 1
    if has_bg_music:
        # -stream_loop -1 зацикливает 20-секундный эмбиент-трек на всю
        # длительность блока; трек сгенерирован как чистые синусоиды без
        # огибающей/фейдов, поэтому переход между повторами не даёт щелчка.
        cmd += ["-stream_loop", "-1", "-i", BG_MUSIC_FILE]
        bg_idx = next_input_idx
        next_input_idx += 1

    audio_filter = ""
    audio_map = None
    if has_voice and has_bg_music:
        audio_filter = (
            f";[{voice_idx}:a]volume=1.0[voice];"
            f"[{bg_idx}:a]volume={BG_MUSIC_VOLUME}[bgm];"
            f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=2[aout]"
        )
        audio_map = "[aout]"
    elif has_voice:
        audio_filter = ""
        audio_map = f"{voice_idx}:a"
    elif has_bg_music:
        audio_filter = f";[{bg_idx}:a]volume={BG_MUSIC_VOLUME * 1.6}[aout]"
        audio_map = "[aout]"

    if audio_map:
        cmd += ["-filter_complex", base_filter + audio_filter,
                "-map", "[v]", "-map", audio_map, "-c:a", "aac"]
    else:
        cmd += ["-filter_complex", base_filter, "-map", "[v]", "-an"]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
            "-shortest", "-t", str(dur), out_mp4]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [FFM] Ошибка:\n{result.stderr[-600:]}")
        return False
    print(f"  [FFM] готов ({os.path.getsize(out_mp4)//1024} кб, {dur:.1f} сек)")
    return True

def concat_videos(mp4s, out_mp4):
    list_file = os.path.join(TMP_DIR, "concat_list.txt")
    with open(list_file, 'w') as f:
        for p in mp4s:
            f.write(f"file '{p}'\n")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", out_mp4]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [FFM] Ошибка concat:\n{result.stderr[-400:]}")
        return False
    print(f"  [FFM] Итоговое видео: {out_mp4} ({os.path.getsize(out_mp4)/1024/1024:.1f} Мб)")
    return True

def main():
    print(f"\n  Генерация вертикального видео (9:16), стиль — прокрутка текста. [источник: {SOURCE}]")
    if not os.path.exists(META_FILE):
        print(f"  Файл не найден: {META_FILE}"); return
    with open(META_FILE, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    blocks = meta.get("blocks", [])
    if not blocks:
        print("  Нет блоков"); return
    print(f"  Шрифт: {FONT_DIR}\n  Блоков: {len(blocks)}")
    os.makedirs(TMP_DIR, exist_ok=True)

    INTRO_FPS = 25
    INTRO_DUR = 1.6
    n_intro = int(INTRO_FPS * INTRO_DUR)

    all_mp4s = []
    for idx, block in enumerate(blocks):
        key = block.get("key", f"block_{idx}")
        theme = THEMES.get(key, DEFAULT_THEME)
        title = block.get("title", "")
        filename = block.get("filename", f"block_{idx}.mp3")
        mp3_path = os.path.join(BLOCKS_DIR, filename)
        print(f"\n  [BLOCK] '{title}' (key={key})")

        chrome_png = os.path.join(TMP_DIR, f"chrome_{idx:02d}.png")
        strip_png  = os.path.join(TMP_DIR, f"strip_{idx:02d}.png")
        block_mp4  = os.path.join(TMP_DIR, f"block_{idx:02d}.mp4")

        build_chrome(block, theme, chrome_png, reveal_frac=1.0)
        strip_h = build_textstrip(block.get("text", ""), theme, strip_png)
        audio_path = mp3_path if os.path.exists(mp3_path) else None

        # интро-анимация (прорисовка графика + счётчик) — только если для
        # этого блока вообще есть график (get_temp_curve вернул данные)
        intro_pattern = None
        if get_temp_curve(key) or key in DECORATIVE_INTRO_KEYS:
            intro_dir = os.path.join(TMP_DIR, f"intro_{idx:02d}")
            os.makedirs(intro_dir, exist_ok=True)
            for i in range(n_intro):
                linear = (i+1)/n_intro
                reveal = ease_in_out_cubic(linear)
                build_chrome(block, theme, os.path.join(intro_dir, f"f{i:04d}.png"), reveal_frac=reveal)
            intro_pattern = os.path.join(intro_dir, "f%04d.png")

        if render_block_video(chrome_png, strip_png, strip_h, audio_path, theme, block_mp4,
                               intro_pattern=intro_pattern, intro_fps=INTRO_FPS, intro_dur=INTRO_DUR):
            all_mp4s.append(block_mp4)

    if not all_mp4s:
        print("  Не удалось создать ни одного блока"); return
    print(f"\n  [FFM] Склеиваю {len(all_mp4s)} блоков...")
    ok = concat_videos(all_mp4s, MP4_FILE)
    if ok:
        for fname in os.listdir(TMP_DIR):
            full = os.path.join(TMP_DIR, fname)
            if fname.startswith(('chrome_', 'strip_', 'block_')) or fname == 'concat_list.txt':
                try: os.remove(full)
                except: pass
            elif fname.startswith('intro_') and os.path.isdir(full):
                try:
                    for sub in os.listdir(full):
                        os.remove(os.path.join(full, sub))
                    os.rmdir(full)
                except: pass
    print("  Готово!" if ok else "  Завершено с ошибками.")

if __name__ == "__main__":
    main()
