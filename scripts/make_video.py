#!/usr/bin/env python3
"""
make_video.py — вертикальное видео 9:16 для TikTok/Reels из блоков blocks_meta.json.
Текст блока не режется на страницы: он рендерится в высокую ленту и плавно
прокручивается снизу вверх (караоке-стиль) синхронно с длительностью озвучки блока.
Хедер (бейдж, прогресс, карточка с иконкой/датой/диапазоном температур) статичен.
"""

import json, os, re, math, sys, subprocess
import numpy as np
from datetime import datetime, timezone, timedelta
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

# ── Шрифт: Carlito (аналог Calibri), проверенная поддержка кириллицы ─────────
FONT_CANDIDATES_DIR = [
    "/usr/share/fonts/truetype/crosextra/",                                    # Ubuntu/Debian (CI)
    "/data/data/com.termux/files/usr/share/fonts/truetype/crosextra/",         # Termux (запасной путь)
]

def _find_font_dir():
    for d in FONT_CANDIDATES_DIR:
        if os.path.exists(os.path.join(d, "Carlito-Regular.ttf")):
            return d
    return None

FONT_DIR = _find_font_dir()

def F(size, weight="regular"):
    if not FONT_DIR:
        return ImageFont.load_default()
    fname = "Carlito-Bold.ttf" if weight in ("bold", "semibold") else "Carlito-Regular.ttf"
    return ImageFont.truetype(os.path.join(FONT_DIR, fname), size)

def _verify_font_renders_cyrillic():
    """Защита от повтора инцидента с Poppins: убеждаемся, что шрифт реально
    рисует разные глифы для разных кириллических букв, а не одну и ту же
    заглушку (тофу) для всех символов."""
    if not FONT_DIR:
        print("  ПРЕДУПРЕЖДЕНИЕ: шрифт Carlito не найден, использую PIL default (кириллица не отрендерится!)")
        return
    font = ImageFont.truetype(os.path.join(FONT_DIR, "Carlito-Bold.ttf"), 60)
    chars = "АБВГДЖЗИЙКЛМНОПРСТУФХЦЧШЩЭЮЯ"
    shapes = set(np.array(font.getmask(ch)).tobytes() for ch in chars)
    if len(shapes) < len(chars) * 0.8:
        raise RuntimeError("Шрифт не поддерживает кириллицу (обнаружены тофу-глифы)!")

THEMES = {
    "today":        {"top": (10, 22, 48), "bot": (18, 40, 78),  "accent": (86, 176, 255),  "glow": (50, 120, 220)},
    "tomorrow":     {"top": (8, 32, 30),  "bot": (14, 56, 50),  "accent": (110, 224, 180), "glow": (30, 140, 100)},
    "next3":        {"top": (34, 24, 8),  "bot": (58, 42, 12),  "accent": (255, 179, 71),  "glow": (200, 110, 20)},
    "warnings":     {"top": (42, 12, 10), "bot": (72, 20, 16),  "accent": (255, 99, 81),   "glow": (200, 40, 20)},
    "trend":        {"top": (24, 14, 44), "bot": (40, 22, 72),  "accent": (196, 140, 255), "glow": (110, 50, 190)},
    "marine":       {"top": (6, 26, 42),  "bot": (10, 46, 70),  "accent": (76, 210, 235),  "glow": (20, 130, 170)},
    "verification": {"top": (16, 20, 30), "bot": (26, 32, 48),  "accent": (150, 190, 255), "glow": (70, 90, 160)},
}
DEFAULT_THEME = THEMES["today"]

# ── Геометрия окна прокрутки текста ──────────────────────────────────────────
TEXT_TOP, TEXT_BOTTOM = 700, 1790
TEXT_X0, TEXT_X1 = 96, W - 96
CARD_X, CARD_Y, CARD_W, CARD_H = 44, 150, W - 88, 250

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

def block_date_str(key):
    now_utc = datetime.now(timezone.utc)
    if key == "tomorrow":
        dt = now_utc + timedelta(days=1)
    elif key == "next3":
        dt = now_utc + timedelta(days=2)
    else:
        dt = now_utc
    return dt.strftime("%d.%m"), dt.strftime("%Y-%m-%d")

def build_chrome(block, total_blocks, block_idx, out_path):
    """Статичная часть кадра: фон, свечения, прогресс, бейдж, карточка.
    Окно под текст (TEXT_TOP..TEXT_BOTTOM) вырезается прозрачным в самом конце."""
    key = block.get("key", "today")
    theme = THEMES.get(key, DEFAULT_THEME)
    acc, glow = theme["accent"], theme["glow"]
    text = block.get("text", "")
    title = block.get("title", "")

    img = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    draw_gradient(draw, theme["top"], theme["bot"])
    draw_soft_blob(img, int(W*0.82), 260, 420, glow, alpha_max=55)
    draw_soft_blob(img, int(W*0.1), int(H*0.75), 520, glow, alpha_max=35)
    draw = ImageDraw.Draw(img)

    # прогресс-сегменты (по числу блоков в видео) + бейдж локации
    total = max(1, total_blocks)
    margin, gap, seg_h = 48, 8, 6
    seg_w = (W - margin*2 - gap*(total-1)) / total
    for i in range(total):
        x = margin + i * (seg_w + gap)
        color = (*acc, 235) if i <= block_idx else (255, 255, 255, 55)
        draw.rounded_rectangle([x, 64, x+seg_w, 64+seg_h], radius=seg_h//2, fill=color)
    draw.text((W//2, 108), "ОДЕССА", font=F(26, "semibold"), fill=(*acc, 200), anchor="mm")

    # карточка
    rounded_glass_card(img, CARD_X, CARD_Y, CARD_W, CARD_H, radius=36, accent=acc)
    draw = ImageDraw.Draw(img)
    icon_cx, icon_cy, icon_r = CARD_X+95, CARD_Y+95, 62
    draw_soft_blob(img, icon_cx, icon_cy, icon_r+30, acc, alpha_max=90)
    draw = ImageDraw.Draw(img)
    draw.ellipse([icon_cx-icon_r, icon_cy-icon_r, icon_cx+icon_r, icon_cy+icon_r], fill=(255, 255, 255, 235))
    paste_icon(img, weather_icon_path(text, key), icon_cx, icon_cy, size=78)
    draw = ImageDraw.Draw(img)

    date_label, _ = block_date_str(key)
    draw.text((CARD_X+185, CARD_Y+62), title, font=F(50, "bold"), fill=(255, 255, 255, 255), anchor="lm")
    draw.text((CARD_X+187, CARD_Y+108), date_label, font=F(28, "medium"), fill=(*acc, 220), anchor="lm")

    t_min, t_max = extract_temp_range(text)
    if t_min is not None and t_max is not None and t_min != t_max:
        temp_str = f"{round(t_min)}°–{round(t_max)}°"
    elif t_max is not None:
        temp_str = f"{round(t_max)}°"
    else:
        temp_str = ""
    if key == "marine":
        sst = re.search(r'(\d+[.,]\d+)°C', text)
        temp_str = f"{sst.group(1)}°C" if sst else ""
    if temp_str:
        draw.text((CARD_X+CARD_W-30, CARD_Y+85), temp_str, font=F(52, "bold"), fill=(*acc, 255), anchor="rm")

    # разделитель — затухание ЦВЕТОМ (не альфой!), чтобы не пробивать окно прозрачности
    div_y = CARD_Y + CARD_H + 34
    bg_row = gradient_color_at(div_y/H, theme["top"], theme["bot"])
    for i in range(W - 88):
        factor = math.sin(math.pi * i / (W - 88))
        r = int(bg_row[0] + (acc[0]-bg_row[0])*factor)
        g = int(bg_row[1] + (acc[1]-bg_row[1])*factor)
        b = int(bg_row[2] + (acc[2]-bg_row[2])*factor)
        draw.point((44+i, div_y), fill=(r, g, b, 255))

    # футер
    now_str = datetime.now().strftime("%d.%m.%Y")
    draw.text((W//2, H-64), f"Синоптический прогноз  ·  {now_str}",
              font=F(26, "medium"), fill=(255, 255, 255, 130), anchor="mm")

    # ── вырезаем окно под текст ──
    # Сначала принудительно полная непрозрачность ВЕЗДЕ (защита от случайных
    # частично-прозрачных пикселей декоративных элементов), затем — реальная дыра.
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
    while lines and lines[-1] == '': lines.pop()

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
            y += LINE_H//2; continue
        d.text((TEXT_X0, y), line, font=font, fill=(228, 238, 248))
        y += LINE_H
    strip.save(out_path, "PNG")
    return strip_h

def ffprobe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except (ValueError, TypeError):
        return None

def render_block_video(block, theme, chrome_png, textstrip_png, strip_h, audio_path, out_mp4):
    window_h = TEXT_BOTTOM - TEXT_TOP
    max_scroll = max(0, strip_h - window_h)

    has_audio = audio_path and os.path.exists(audio_path)
    dur = ffprobe_duration(audio_path) if has_audio else None
    if not dur or dur <= 0:
        dur = max(6.0, strip_h / 140)  # запасной вариант без аудио
        has_audio = False

    # адаптивные тайминги: на коротких блоках (warnings и т.п.) не тратим
    # почти всё время на неподвижную задержку
    start_delay = 15.0 if dur > 22 else max(1.0, dur * 0.3)
    end_hold = 1.5 if dur > 6 else max(0.3, dur * 0.15)
    fade_dur = min(1.2, max(0.4, dur * 0.15))
    scroll_time = max(0.3, dur - start_delay - end_hold)

    bg_color = gradient_color_at((TEXT_TOP+TEXT_BOTTOM)/2/H, theme["top"], theme["bot"])
    hexcolor = '0x%02x%02x%02x' % bg_color
    fade_start = max(0, dur - fade_dur)

    y_expr = f"{TEXT_TOP}-min(max(t-{start_delay},0)/{scroll_time}*{max_scroll},{max_scroll})"

    filter_complex = (
        f"[1:v]fade=t=out:st={fade_start}:d={fade_dur}:color={hexcolor}[txtfade];"
        f"[0:v][txtfade]overlay=x=0:y='{y_expr}':shortest=0[bg1];"
        f"[bg1][2:v]overlay=x=0:y=0:shortest=1[v]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=size={W}x{H}:color={hexcolor}",
        "-loop", "1", "-i", textstrip_png,
        "-loop", "1", "-i", chrome_png,
    ]
    if has_audio:
        cmd += ["-i", audio_path, "-filter_complex", filter_complex,
                "-map", "[v]", "-map", "3:a", "-c:a", "aac"]
    else:
        cmd += ["-filter_complex", filter_complex, "-map", "[v]", "-an"]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
            "-t", str(dur), out_mp4]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [FFM] Ошибка:\n{result.stderr[-800:]}")
        return False
    print(f"  [FFM] готов, {dur:.1f} сек ({os.path.getsize(out_mp4)//1024} кб)")
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
    print(f"\n  Генерация вертикального видео (9:16, прокрутка текста) [источник: {SOURCE}]")
    if not os.path.exists(META_FILE):
        print(f"  Файл не найден: {META_FILE}"); return
    with open(META_FILE, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    blocks = meta.get("blocks", [])
    if not blocks:
        print("  Нет блоков"); return

    _verify_font_renders_cyrillic()
    print(f"  Шрифт: {FONT_DIR}\n  Блоков: {len(blocks)}")
    os.makedirs(TMP_DIR, exist_ok=True)

    all_mp4s = []
    for idx, block in enumerate(blocks):
        key = block.get("key", f"block_{idx}")
        theme = THEMES.get(key, DEFAULT_THEME)
        filename = block.get("filename", f"block_{idx}.mp3")
        mp3_path = os.path.join(BLOCKS_DIR, filename)
        print(f"\n  [BLOCK] '{block.get('title','')}' ({key})")

        chrome_png = os.path.join(TMP_DIR, f"chrome_{idx:02d}.png")
        strip_png  = os.path.join(TMP_DIR, f"strip_{idx:02d}.png")
        mp4_path   = os.path.join(TMP_DIR, f"block_{idx:02d}.mp4")

        build_chrome(block, len(blocks), idx, chrome_png)
        strip_h = build_textstrip(block.get("text", ""), theme, strip_png)

        if render_block_video(block, theme, chrome_png, strip_png, strip_h, mp3_path, mp4_path):
            all_mp4s.append(mp4_path)

    if not all_mp4s:
        print("  Не удалось создать ни одного блока"); return
    print(f"\n  [FFM] Склеиваю {len(all_mp4s)} блоков...")
    ok = concat_videos(all_mp4s, MP4_FILE)
    if ok:
        for fname in os.listdir(TMP_DIR):
            if fname.endswith(('.png',)) or (fname.endswith('.mp4') and fname.startswith('block_')):
                try: os.remove(os.path.join(TMP_DIR, fname))
                except: pass
    print("  Готово!" if ok else "  Завершено с ошибками.")

if __name__ == "__main__":
    main()
