#!/usr/bin/env python3
"""
make_video.py — вертикальное видео 9:16 для TikTok/Reels из блоков blocks_meta.json.
Хедер с карточкой статичен, текст блока плавно прокручивается снизу вверх
(караоке-стиль), синхронизирован с длительностью озвучки блока целиком —
без разбивки на страницы и без разрывов по предложениям.
"""

import json, os, re, math, glob, sys, subprocess
from datetime import datetime
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
FADE_DUR    = 1.2    # сек — плавное затухание текста в самом конце

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

def extract_temp_range(text):
    short = text[:350]
    nums = [int(m) for m in re.findall(r'(-?\d{1,2})°C', short)]
    nums = [n for n in nums if -20 <= n <= 45]
    if not nums: return None, None
    return min(nums), max(nums)

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

def build_chrome(block, theme, out_path):
    """Статичная часть кадра: фон + карточка + хедер, с прозрачным окном под
    прокручивающийся текст. Все декоративные элементы рисуются с alpha=255,
    а после отрисовки альфа принудительно нормализуется — это защита от
    случайных полупрозрачных «дыр» (см. историю багов с разделителем)."""
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

    draw.rounded_rectangle([48, 64, W-48, 70], radius=3, fill=(*acc, 235))
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
        temp_str = f"{round(t_min)}°–{round(t_max)}°"
    elif t_max is not None:
        temp_str = f"{round(t_max)}°"
    if temp_str:
        draw.text((card_x+card_w-30, card_y+85), temp_str, font=F(58, "bold"), fill=(*acc, 255), anchor="rm")

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

def render_block_video(chrome_png, textstrip_png, strip_h, audio_path, theme, out_mp4, min_duration=6.0):
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
    fade_start = max(0, dur - FADE_DUR)

    filter_complex = (
        f"[1:v]fade=t=out:st={fade_start}:d={FADE_DUR}:color={hexcolor}[txtfade];"
        f"[0:v][txtfade]overlay=x=0:y='{y_expr}':shortest=0[bg1];"
        f"[bg1][2:v]overlay=x=0:y=0:shortest=1[v]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=size={W}x{H}:color={hexcolor}",
        "-loop", "1", "-i", textstrip_png,
        "-loop", "1", "-i", chrome_png,
    ]
    if audio_path and os.path.exists(audio_path):
        cmd += ["-i", audio_path, "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "3:a", "-c:a", "aac"]
    else:
        cmd += ["-filter_complex", filter_complex, "-map", "[v]", "-an"]
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

        build_chrome(block, theme, chrome_png)
        strip_h = build_textstrip(block.get("text", ""), theme, strip_png)
        audio_path = mp3_path if os.path.exists(mp3_path) else None
        if render_block_video(chrome_png, strip_png, strip_h, audio_path, theme, block_mp4):
            all_mp4s.append(block_mp4)

    if not all_mp4s:
        print("  Не удалось создать ни одного блока"); return
    print(f"\n  [FFM] Склеиваю {len(all_mp4s)} блоков...")
    ok = concat_videos(all_mp4s, MP4_FILE)
    if ok:
        for fname in os.listdir(TMP_DIR):
            if fname.startswith(('chrome_', 'strip_', 'block_')) or fname == 'concat_list.txt':
                try: os.remove(os.path.join(TMP_DIR, fname))
                except: pass
    print("  Готово!" if ok else "  Завершено с ошибками.")

if __name__ == "__main__":
    main()
