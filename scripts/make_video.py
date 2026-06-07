#!/usr/bin/env python3
"""
make_video.py — вертикальное видео 9:16 для TikTok/Reels из блоков blocks_meta.json.
Текст блока делится на страницы, каждая страница = отдельный слайд.
Аудио блока делится пропорционально по страницам через ffmpeg trim.
"""

import json, os, re, math, time, subprocess
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCKS_DIR = os.path.join(BASE_DIR, "data", "blocks")
META_FILE  = os.path.join(BLOCKS_DIR, "blocks_meta.json")
TMP_DIR    = os.path.join(BASE_DIR, "data", "blocks", "tmp")
MP4_FILE   = os.path.join(BASE_DIR, "data", "forecast_video.mp4")

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

def render_slide(block, slide_idx, total_slides, page_lines, page_num, total_pages, out_png):
    """Рендерит один слайд (одну страницу блока)."""
    key   = block.get("key", "today")
    theme = THEMES.get(key, DEFAULT_THEME)
    acc   = theme["accent"]
    glow  = theme["glow"]

    img  = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    draw_gradient(draw, theme["top"], theme["bot"])
    draw_stars(draw, seed=slide_idx * 7 + page_num + 1)
    draw_glow_circle(img, W//2, H//2, 600, glow, alpha_max=45)
    draw = ImageDraw.Draw(img)
    draw_corner_marks(draw, acc)

    # Верхний бейдж
    draw.text((W//2, 70), "ОДЕССА · ПОГОДА",
              font=F(32, True), fill=(*acc, 180), anchor='mm')

    # Полоска прогресса (по слайдам блоков, не страницам)
    seg_w = (W - 120) // total_slides
    for i in range(total_slides):
        sx = 60 + i * (seg_w + 4)
        color_seg = acc if i <= slide_idx else (80, 80, 100)
        draw.rounded_rectangle([sx, 110, sx+seg_w, 115], radius=3, fill=color_seg)

    # Иконка блока
    icon_char = BLOCK_ICONS.get(key, "\u2600")
    try:
        draw.text((W//2, 280), icon_char, font=F(140, True),
                  fill=(255, 255, 255), anchor='mm')
    except:
        bb = draw.textbbox((0,0), icon_char, font=F(140, True))
        tw = bb[2]-bb[0]; th = bb[3]-bb[1]
        draw.text((W//2 - tw//2, 280 - th//2), icon_char,
                  font=F(140, True), fill=(255, 255, 255))

    # Заголовок блока
    title = block.get("title", "").upper()
    draw.text((W//2, 400), title, font=F(72, True),
              fill=(255, 255, 255), anchor='mm')

    # Номер страницы (если больше одной)
    if total_pages > 1:
        draw.text((W//2, 455), f"{page_num + 1} / {total_pages}",
                  font=F(30), fill=(*acc, 150), anchor='mm')

    # Разделитель
    div_y = 490
    draw.rectangle([80, div_y, W-80, div_y+3], fill=(*acc, 120))

    # Текст страницы
    font_body = F(FONT_BODY_SIZE)
    text_x  = 65
    text_maxw = W - 130
    y = div_y + 45

    for line in page_lines:
        if not line:
            y += LINE_H // 2
            continue
        draw.text((text_x, y), line, font=font_body, fill=(215, 238, 255))
        y += LINE_H

    # Нижняя подпись
    now_str = datetime.now().strftime("%d.%m.%Y")
    draw.text((W//2, H - 100),
              f"Синоптический прогноз · {now_str}",
              font=F(30), fill=(120, 150, 200), anchor='mm')
    draw.rectangle([W//2 - 120, H-62, W//2 + 120, H-59], fill=(*acc, 100))

    img = img.convert('RGB')
    img.save(out_png, 'PNG')

def get_audio_duration(path):
    """Точная длительность аудио через ffprobe."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True
        )
        return float(result.stdout.strip())
    except Exception:
        # Fallback: по размеру файла
        return os.path.getsize(path) / 16000

def trim_audio(mp3_path, out_path, start_sec, duration_sec):
    """Обрезает кусок аудио через ffmpeg."""
    cmd = [
        "ffmpeg", "-y",
        "-i", mp3_path,
        "-ss", str(round(start_sec, 3)),
        "-t",  str(round(duration_sec, 3)),
        "-c:a", "aac", "-b:a", "96k",
        out_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0

def make_slide_video(png_path, audio_path, out_mp4, duration):
    if audio_path and os.path.exists(audio_path):
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", png_path,
            "-i", audio_path,
            "-c:v", "libx264", "-preset", "veryfast",
            "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "96k",
            "-pix_fmt", "yuv420p",
            "-shortest",
            "-vf", f"scale={W}:{H}",
            out_mp4
        ]
    else:
        dur_sec = max(int(duration), 5)
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", png_path,
            "-t", str(dur_sec),
            "-c:v", "libx264", "-preset", "veryfast",
            "-tune", "stillimage",
            "-pix_fmt", "yuv420p",
            "-vf", f"scale={W}:{H}",
            "-an",
            out_mp4
        ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [FFM] Ошибка:\n{result.stderr[-400:]}")
        return False
    size_kb = os.path.getsize(out_mp4) // 1024
    print(f"  [FFM] готов ({size_kb} кб)")
    return True

def concat_videos(slide_mp4s, out_mp4):
    list_file = os.path.join(TMP_DIR, "concat_list.txt")
    with open(list_file, 'w') as f:
        for p in slide_mp4s:
            f.write(f"file '{p}'\n")
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_file,
        "-c", "copy",
        out_mp4
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  [FFM] Ошибка concat:\n{result.stderr[-400:]}")
        return False
    size_mb = os.path.getsize(out_mp4) / 1024 / 1024
    print(f"  [FFM] \u2705 Итоговое видео: {out_mp4} ({size_mb:.1f} Мб)")
    return True

def main():
    print("\n  \U0001f4f9 Генерация вертикального видео (9:16) для TikTok...")

    if not os.path.exists(META_FILE):
        print(f"  Файл не найден: {META_FILE}")
        return

    with open(META_FILE, 'r', encoding='utf-8') as f:
        meta = json.load(f)

    blocks = meta.get("blocks", [])
    if not blocks:
        print("  Нет блоков в мета-файле")
        return

    if not FONT_REG_PATH:
        print("  ОШИБКА: шрифт не найден!")
        return

    print(f"  Шрифт: {FONT_REG_PATH}")
    print(f"  Блоков: {len(blocks)}")
    os.makedirs(TMP_DIR, exist_ok=True)

    # Считаем страницы для каждого блока
    dummy_img  = Image.new('RGB', (W, H))
    dummy_draw = ImageDraw.Draw(dummy_img)
    font_body  = F(FONT_BODY_SIZE)
    text_maxw  = W - 130

    block_pages = []
    for block in blocks:
        pages = split_into_pages(
            block.get("text", ""), font_body, text_maxw, dummy_draw)
        block_pages.append(pages)

    total_slides = len(blocks)
    all_mp4s = []
    slide_counter = 0

    for block_idx, block in enumerate(blocks):
        key      = block.get("key", f"block_{block_idx}")
        filename = block.get("filename", f"block_{block_idx}.mp3")
        mp3_path = os.path.join(BLOCKS_DIR, filename)
        duration = block.get("duration", 15)
        pages    = block_pages[block_idx]
        n_pages  = len(pages)

        print(f"\n  [BLOCK] '{block.get('title','')}' → {n_pages} стр., ~{duration:.0f} сек")

        # Делим аудио пропорционально символам на странице
        chars_per_page = [sum(len(l) for l in pg) for pg in pages]
        total_chars = sum(chars_per_page) or 1

        # Точная длительность основного mp3 через ffprobe
        if os.path.exists(mp3_path):
            real_duration = get_audio_duration(mp3_path)
        else:
            real_duration = duration

        for page_num, page_lines in enumerate(pages):
            png_path = os.path.join(TMP_DIR, f"slide_{slide_counter:03d}.png")
            mp4_path = os.path.join(TMP_DIR, f"slide_{slide_counter:03d}.mp4")

            render_slide(block, block_idx, total_slides,
                         page_lines, page_num, n_pages, png_path)
            print(f"  [SLIDE] стр.{page_num+1}/{n_pages}", end=" ")

            # Нарезаем основной mp3 пропорционально символам — без пауз между страницами
            audio_for_slide = None
            page_dur = real_duration * chars_per_page[page_num] / total_chars
            start_sec = real_duration * sum(chars_per_page[:page_num]) / total_chars
            if os.path.exists(mp3_path) and n_pages > 1:
                aac_path = os.path.join(TMP_DIR, f"audio_{slide_counter:03d}.aac")
                ok = trim_audio(mp3_path, aac_path, start_sec, page_dur)
                if ok:
                    audio_for_slide = aac_path
            elif os.path.exists(mp3_path):
                aac_path = os.path.join(TMP_DIR, f"audio_{slide_counter:03d}.aac")
                ok = trim_audio(mp3_path, aac_path, 0, real_duration)
                if ok:
                    audio_for_slide = aac_path
                page_dur = real_duration

            ok = make_slide_video(png_path, audio_for_slide, mp4_path, page_dur)
            if ok:
                all_mp4s.append(mp4_path)

            slide_counter += 1

    if not all_mp4s:
        print("  Не удалось создать ни одного слайда")
        return

    print(f"\n  [FFM] Склеиваю {len(all_mp4s)} слайдов...")
    ok = concat_videos(all_mp4s, MP4_FILE)

    if ok:
        for fname in os.listdir(TMP_DIR):
            if fname.endswith(('.png', '.aac')) or \
               (fname.endswith('.mp4') and fname.startswith('slide_')):
                try: os.remove(os.path.join(TMP_DIR, fname))
                except: pass
        print("  [CLEAN] Временные файлы удалены")

    print("\n  Готово!" if ok else "\n  Завершено с ошибками.")

if __name__ == "__main__":
    main()
