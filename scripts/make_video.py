#!/usr/bin/env python3
"""
make_video.py — вертикальное видео 9:16 для TikTok/Reels из блоков blocks_meta.json.
Текст блока делится на страницы, каждая страница = отдельный слайд.
Аудио блока делится пропорционально по страницам через ffmpeg trim.
"""

import json, os, re, math, time, sys, subprocess
from datetime import datetime, timezone, timedelta
from PIL import Image, ImageDraw, ImageFont

def load_snap_hours(date_str):
    snap_file = os.path.join(BASE_DIR, "data", "ensemble_snapshots_pws.json")
    if not os.path.exists(snap_file): return []
    try:
        d = json.load(open(snap_file, encoding="utf-8"))
        if not d: return []
        snap = d[-1]
        return [h for h in snap.get("hours", []) if h["time"][:10] == date_str]
    except: return []

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

FONT_CANDIDATES = [
    "/system/fonts/Roboto-Regular.ttf",
    "/system/fonts/NotoSans-Regular.ttf",
    "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/data/data/com.termux/files/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
FONT_BOLD_CANDIDATES = [
    "/system/fonts/Roboto-Bold.ttf",
    "/system/fonts/NotoSans-Bold.ttf",
    "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

def find_font(candidates):
    for p in candidates:
        if os.path.exists(p): return p
    return None

FONT_REG_PATH  = find_font(FONT_CANDIDATES)
FONT_BOLD_PATH = find_font(FONT_BOLD_CANDIDATES) or FONT_REG_PATH

def F(size, bold=False):
    path = FONT_BOLD_PATH if bold else FONT_REG_PATH
    if path:
        try: return ImageFont.truetype(path, size)
        except: pass
    return ImageFont.load_default()

THEMES = {
    "today":    {"top": (8, 20, 55),  "bot": (15, 45, 90),  "accent": (79, 195, 247),  "glow": (30, 100, 200)},
    "tomorrow": {"top": (8, 30, 18),  "bot": (15, 55, 28),  "accent": (129, 199, 132), "glow": (20, 120, 40)},
    "next3":    {"top": (35, 22, 5),  "bot": (60, 38, 10),  "accent": (255, 183, 77),  "glow": (180, 80, 0)},
    "warnings": {"top": (45, 10, 5),  "bot": (75, 18, 8),   "accent": (255, 112, 67),  "glow": (200, 40, 10)},
    "trend":    {"top": (15, 12, 38), "bot": (28, 20, 65),  "accent": (206, 147, 216), "glow": (100, 40, 180)},
}
DEFAULT_THEME = THEMES["today"]

# ── Иконки блоков — ASCII/Unicode вместо эмодзи ───────────────────────────────
BLOCK_ICONS = {
    "today":    "\u2600",   # ☀ солнце
    "tomorrow": "\u26c5",   # ⛅ солнце с облаком
    "next3":    "\u25a6",   # ▦ сетка (календарь)
    "warnings": "\u26a0",   # ⚠ предупреждение
    "trend":    "\u2197",   # ↗ стрелка вверх
}

FONT_BODY_SIZE = 52   # крупнее для читаемости
LINE_H         = 72   # межстрочный интервал
LINES_PER_PAGE = 15   # строк на страницу (реально влезает 17, с отступами ~15)

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

def clean_text(text):
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def split_into_pages(text, font, maxw, draw):
    """Разбивает текст на страницы по LINES_PER_PAGE строк."""
    raw = clean_text(text)
    paragraphs = [p.strip() for p in raw.split('\n') if p.strip()]
    all_lines = []
    for para in paragraphs:
        all_lines.extend(wrap_text(para, font, maxw, draw))
        all_lines.append('')  # пустая строка между абзацами

    # Убираем лишние пустые строки в конце
    while all_lines and all_lines[-1] == '':
        all_lines.pop()

    pages = []
    i = 0
    while i < len(all_lines):
        page = all_lines[i:i + LINES_PER_PAGE]
        pages.append(page)
        i += LINES_PER_PAGE
    return pages

def draw_gradient(draw, top, bot):
    for y in range(H):
        t = y / H
        r = int(top[0] + (bot[0]-top[0])*t)
        g = int(top[1] + (bot[1]-top[1])*t)
        b = int(top[2] + (bot[2]-top[2])*t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

def draw_stars(draw, seed=42):
    import random; rng = random.Random(seed)
    for _ in range(180):
        x = rng.randint(0, W); y = rng.randint(0, H//2)
        sz = rng.choice([1, 1, 2, 2, 3])
        a  = rng.randint(60, 200)
        draw.ellipse([x, y, x+sz, y+sz], fill=(a, min(a+30, 255), 255))

def draw_glow_circle(img, cx, cy, radius, color, alpha_max=60):
    from PIL import Image as PILImage
    overlay = PILImage.new('RGBA', img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    steps = 8
    for i in range(steps, 0, -1):
        r = radius * i // steps
        a = alpha_max * (steps - i + 1) // steps
        d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(*color, a))
    img.paste(overlay, mask=overlay)

def draw_corner_marks(draw, accent, size=24, margin=40):
    corners = [
        (margin, margin, 1, 0), (margin, margin, 0, 1),
        (W-margin, margin, -1, 0), (W-margin, margin, 0, 1),
        (margin, H-margin, 1, 0), (margin, H-margin, 0, -1),
        (W-margin, H-margin, -1, 0), (W-margin, H-margin, 0, -1),
    ]
    for px, py, dx, dy in corners:
        draw.line([px, py, px+dx*size, py+dy*size], fill=accent, width=3)


def draw_temp_chart(img, hours, acc, card_x, card_y, card_w, card_h):
    from PIL import Image as PILImage
    temps = [(int(h["time"][11:13]), h["temp"]) for h in hours if h.get("temp") is not None]
    if len(temps) < 3: return
    overlay = PILImage.new("RGBA", img.size, (0,0,0,0))
    d = ImageDraw.Draw(overlay)
    pad_l, pad_r, pad_t, pad_b = 20, 20, 20, 35
    gw = card_w - pad_l - pad_r
    gh = card_h - pad_t - pad_b
    t_vals = [t for _,t in temps]
    t_min_v = min(t_vals) - 1; t_max_v = max(t_vals) + 1
    t_range = t_max_v - t_min_v or 1
    def px(hr, tv):
        x = card_x + pad_l + int(hr / 23 * gw)
        y = card_y + pad_t + int((1 - (tv - t_min_v) / t_range) * gh)
        return x, y
    pts = [px(hr, tv) for hr, tv in temps]
    poly = pts + [(pts[-1][0], card_y+card_h-pad_b+5), (pts[0][0], card_y+card_h-pad_b+5)]
    d.polygon(poly, fill=(*acc, 35))
    for i in range(len(pts)-1):
        d.line([pts[i], pts[i+1]], fill=(*acc, 220), width=5)
    for hr in [0, 6, 12, 18, 23]:
        x = card_x + pad_l + int(hr / 23 * gw)
        y_base = card_y + card_h - pad_b
        d.line([(x, y_base), (x, y_base+4)], fill=(*acc, 80), width=1)
        d.text((x, y_base+18), f"{hr:02d}", font=F(22), fill=(*acc, 130), anchor="mm")
    min_hr, min_t = min(temps, key=lambda x: x[1])
    max_hr, max_t = max(temps, key=lambda x: x[1])
    mx, my = px(min_hr, min_t)
    xx, xy = px(max_hr, max_t)
    d.ellipse([mx-7,my-7,mx+7,my+7], fill=(100,180,255,255))
    d.ellipse([xx-7,xy-7,xx+7,xy+7], fill=(255,120,80,255))
    d.text((mx, my+22), f"{round(min_t)}\u00b0", font=F(26,True), fill=(100,200,255,255), anchor="mm")
    d.text((xx, xy-24), f"{round(max_t)}\u00b0", font=F(26,True), fill=(255,140,80,255), anchor="mm")
    img.paste(overlay, mask=overlay)

def weather_icon_path(text, key):
    t = text.lower()
    if key == 'marine': return os.path.join(ICONS_DIR, 'wave.png')
    if key == 'trend':  return os.path.join(ICONS_DIR, 'trend.png')
    if key == 'next3':  return os.path.join(ICONS_DIR, 'calendar.png')
    if 'гроза' in t or 'молния' in t: return os.path.join(ICONS_DIR, 'thunder.png')
    if 'дождь' in t or 'осадки' in t: return os.path.join(ICONS_DIR, 'rain.png')
    if 'облачно' in t or 'облака' in t: return os.path.join(ICONS_DIR, 'cloudy.png')
    if 'ясно' in t or 'солнечно' in t: return os.path.join(ICONS_DIR, 'sunny.png')
    return os.path.join(ICONS_DIR, 'partly_cloudy.png')

def paste_icon(img, icon_path, cx, cy, size=180):
    if not os.path.exists(icon_path): return
    icon = Image.open(icon_path).convert('RGBA')
    icon = icon.resize((size, size), Image.LANCZOS)
    img.paste(icon, (cx - size//2, cy - size//2), icon)

def extract_temp_range(text):
    import re
    short = text[:350]
    nums = [int(m) for m in re.findall(r'(-?\d{1,2})°C', short)]
    nums = [n for n in nums if -20 <= n <= 45]
    if not nums: return None, None
    return min(nums), max(nums)

def draw_info_card(img, block, acc):
    from PIL import Image as PILImage
    key = block.get("key", "today")
    title = block.get("title", "").upper()
    t_min = block.get("t_min"); t_max = block.get("t_max")
    now_utc = datetime.now(timezone.utc)
    if key == "tomorrow":
        date_str = (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")
    elif key == "next3":
        date_str = (now_utc + timedelta(days=2)).strftime("%Y-%m-%d")
    else:
        date_str = now_utc.strftime("%Y-%m-%d")
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    MONTHS = ["\u044f\u043d\u0432","\u0444\u0435\u0432","\u043c\u0430\u0440","\u0430\u043f\u0440","\u043c\u0430\u044f","\u0438\u044e\u043d","\u0438\u044e\u043b","\u0430\u0432\u0433","\u0441\u0435\u043d","\u043e\u043a\u0442","\u043d\u043e\u044f","\u0434\u0435\u043a"]
    date_label = f"{dt.day} {MONTHS[dt.month-1]}"
    draw = ImageDraw.Draw(img)
    card_x, card_y, card_w, card_h = 40, 125, W-80, 480
    overlay = PILImage.new("RGBA", img.size, (0,0,0,0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle([card_x, card_y, card_x+card_w, card_y+card_h],
                          radius=24, fill=(0,0,0,80), outline=(*acc,60), width=2)
    img.paste(overlay, mask=overlay)
    draw = ImageDraw.Draw(img)
    icon_path = weather_icon_path(block.get("text",""), key)
    paste_icon(img, icon_path, card_x+55, card_y+58, size=75)
    draw = ImageDraw.Draw(img)
    draw.text((card_x+115, card_y+35), title, font=F(52,True), fill=(255,255,255), anchor="lm")
    draw.text((card_x+117, card_y+78), date_label, font=F(30), fill=(*acc,180), anchor="lm")
    if t_min is not None and t_max is not None and t_min != t_max:
        temp_str = f"{round(t_min)}\u00b0..{round(t_max)}\u00b0C"
    elif t_max is not None:
        temp_str = f"{round(t_max)}\u00b0C"
    else:
        temp_str = ""
    if temp_str:
        draw.text((W-card_x-20, card_y+55), temp_str, font=F(46,True), fill=(*acc,240), anchor="rm")
    if key in ("today","tomorrow","next3"):
        hours = load_snap_hours(date_str)
        if hours:
            draw_temp_chart(img, hours, acc, card_x+15, card_y+105, card_w-30, 355)
            draw = ImageDraw.Draw(img)
    elif key == "marine":
        sst = re.search(r'(\d+[.,]\d+)\u00b0C', block.get("text",""))
        if sst:
            draw.text((W//2, card_y+300), f"\u0422\u0432\u043e\u0434\u044b {sst.group(1)}\u00b0C",
                      font=F(52,True), fill=(*acc,240), anchor="mm")
        paste_icon(img, weather_icon_path("","marine"), W//2, card_y+180, size=120)
        draw = ImageDraw.Draw(img)
    return card_y + card_h

def render_slide(block, slide_idx, total_slides, page_lines, page_num, total_pages, out_png):
    key   = block.get("key", "today")
    theme = THEMES.get(key, DEFAULT_THEME)
    acc   = theme["accent"]; glow = theme["glow"]
    img  = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)
    draw_gradient(draw, theme["top"], theme["bot"])
    draw_stars(draw, seed=slide_idx * 7 + page_num + 1)
    draw_glow_circle(img, W//2, H//2, 600, glow, alpha_max=45)
    draw = ImageDraw.Draw(img)
    draw_corner_marks(draw, acc)
    draw.text((W//2, 72), "\u041e\u0414\u0415\u0421\u0421\u0410 \u00b7 \u041f\u041e\u0413\u041e\u0414\u0410",
              font=F(32, True), fill=(*acc, 180), anchor='mm')
    seg_w = (W - 120) // total_slides
    for i in range(total_slides):
        sx = 60 + i * (seg_w + 4)
        color_seg = acc if i <= slide_idx else (80, 80, 100)
        draw.rounded_rectangle([sx, 105, sx+seg_w, 110], radius=3, fill=color_seg)
    card_bottom = draw_info_card(img, block, acc)
    draw = ImageDraw.Draw(img)
    div_y = card_bottom + 15
    if total_pages > 1:
        draw.text((W//2, div_y), f"{page_num + 1} / {total_pages}",
                  font=F(28), fill=(*acc, 150), anchor='mm')
        div_y += 35
    draw.rectangle([80, div_y, W-80, div_y+3], fill=(*acc, 120))
    font_body = F(FONT_BODY_SIZE)
    y = div_y + 40
    for line in page_lines:
        if not line: y += LINE_H // 2; continue
        draw.text((65, y), line, font=font_body, fill=(215, 238, 255))
        y += LINE_H
    now_str = datetime.now().strftime("%d.%m.%Y")
    draw.text((W//2, H-80), f"\u0421\u0438\u043d\u043e\u043f\u0442\u0438\u0447\u0435\u0441\u043a\u0438\u0439 \u043f\u0440\u043e\u0433\u043d\u043e\u0437 \u00b7 {now_str}",
              font=F(28), fill=(120, 150, 200), anchor='mm')
    draw.rectangle([W//2-120, H-50, W//2+120, H-47], fill=(*acc, 100))
    img = img.convert('RGB')
    img.save(out_png, 'PNG')

def trim_audio(mp3_path, out_path, start_sec, duration_sec):
    cmd = ["ffmpeg", "-y", "-i", mp3_path, "-ss", str(round(start_sec, 3)),
           "-t", str(round(duration_sec, 3)), "-c:a", "aac", "-b:a", "96k", out_path]
    return subprocess.run(cmd, capture_output=True).returncode == 0

def make_slide_video(png_path, audio_path, out_mp4, duration):
    if audio_path and os.path.exists(audio_path):
        cmd = ["ffmpeg", "-y", "-loop", "1", "-i", png_path, "-i", audio_path,
               "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
               "-c:a", "aac", "-b:a", "96k", "-pix_fmt", "yuv420p",
               "-shortest", "-vf", f"scale={W}:{H}", out_mp4]
    else:
        cmd = ["ffmpeg", "-y", "-loop", "1", "-i", png_path, "-t", str(max(int(duration),5)),
               "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
               "-pix_fmt", "yuv420p", "-vf", f"scale={W}:{H}", "-an", out_mp4]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [FFM] Ошибка:\n{result.stderr[-400:]}")
        return False
    print(f"  [FFM] готов ({os.path.getsize(out_mp4)//1024} кб)")
    return True

def concat_videos(slide_mp4s, out_mp4):
    list_file = os.path.join(TMP_DIR, "concat_list.txt")
    with open(list_file, 'w') as f:
        for p in slide_mp4s:
            f.write(f"file '{p}'\n")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", out_mp4]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [FFM] Ошибка concat:\n{result.stderr[-400:]}")
        return False
    print(f"  [FFM] Итоговое видео: {out_mp4} ({os.path.getsize(out_mp4)/1024/1024:.1f} Мб)")
    return True

def main():
    print(f"\n  Генерация вертикального видео (9:16) для TikTok... [источник: {SOURCE}]")
    if not os.path.exists(META_FILE):
        print(f"  Файл не найден: {META_FILE}"); return
    with open(META_FILE, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    blocks = meta.get("blocks", [])
    if not blocks:
        print("  Нет блоков"); return
    if not FONT_REG_PATH:
        print("  ОШИБКА: шрифт не найден!"); return
    print(f"  Шрифт: {FONT_REG_PATH}\n  Блоков: {len(blocks)}")
    os.makedirs(TMP_DIR, exist_ok=True)
    dummy_img = Image.new('RGB', (W, H))
    dummy_draw = ImageDraw.Draw(dummy_img)
    font_body = F(FONT_BODY_SIZE)
    text_maxw = W - 130
    block_pages = [split_into_pages(b.get("text",""), font_body, text_maxw, dummy_draw) for b in blocks]
    total_slides = len(blocks)
    all_mp4s = []; slide_counter = 0
    for block_idx, block in enumerate(blocks):
        key = block.get("key", f"block_{block_idx}")
        filename = block.get("filename", f"block_{block_idx}.mp3")
        mp3_path = os.path.join(BLOCKS_DIR, filename)
        duration = block.get("duration", 15)
        pages = block_pages[block_idx]
        n_pages = len(pages)
        print(f"\n  [BLOCK] '{block.get('title','')}' -> {n_pages} стр., ~{duration:.0f} сек")
        chars_per_page = [sum(len(l) for l in pg) for pg in pages]
        total_chars = sum(chars_per_page) or 1
        page_meta = block.get("pages", [])
        for page_num, page_lines in enumerate(pages):
            png_path = os.path.join(TMP_DIR, f"slide_{slide_counter:03d}.png")
            mp4_path = os.path.join(TMP_DIR, f"slide_{slide_counter:03d}.mp4")
            render_slide(block, block_idx, total_slides, page_lines, page_num, n_pages, png_path)
            print(f"  [SLIDE] стр.{page_num+1}/{n_pages}", end=" ")
            audio_for_slide = None; page_dur = 10
            if page_num < len(page_meta):
                pm = page_meta[page_num]
                candidate = os.path.join(BLOCKS_DIR, pm["filename"])
                if os.path.exists(candidate):
                    audio_for_slide = candidate
                    page_dur = pm.get("duration", 10)
            else:
                aac_path = os.path.join(TMP_DIR, f"audio_{slide_counter:03d}.aac")
                page_dur = duration * chars_per_page[page_num] / total_chars
                start_sec = duration * sum(chars_per_page[:page_num]) / total_chars
                if os.path.exists(mp3_path):
                    if trim_audio(mp3_path, aac_path, start_sec, page_dur):
                        audio_for_slide = aac_path
            if make_slide_video(png_path, audio_for_slide, mp4_path, page_dur):
                all_mp4s.append(mp4_path)
            slide_counter += 1
    if not all_mp4s:
        print("  Не удалось создать ни одного слайда"); return
    print(f"\n  [FFM] Склеиваю {len(all_mp4s)} слайдов...")
    ok = concat_videos(all_mp4s, MP4_FILE)
    if ok:
        for fname in os.listdir(TMP_DIR):
            if fname.endswith(('.png','.aac')) or (fname.endswith('.mp4') and fname.startswith('slide_')):
                try: os.remove(os.path.join(TMP_DIR, fname))
                except: pass
    print("  Готово!" if ok else "  Завершено с ошибками.")

if __name__ == "__main__":
    main()
