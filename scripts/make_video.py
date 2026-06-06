#!/usr/bin/env python3
"""
make_video.py — вертикальное видео 9:16 для TikTok/Reels из блоков blocks_meta.json.
Каждый блок → отдельный слайд-видео → concat в forecast_video.mp4.
Запуск: python3 scripts/make_video.py
"""

import json, os, re, math, time, subprocess
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCKS_DIR = os.path.join(BASE_DIR, "data", "blocks")
META_FILE  = os.path.join(BLOCKS_DIR, "blocks_meta.json")
TMP_DIR    = os.path.join(BASE_DIR, "data", "blocks", "tmp")
MP4_FILE   = os.path.join(BASE_DIR, "data", "forecast_video.mp4")

# ── Размер: вертикальный 9:16 ─────────────────────────────────────────────────
W, H = 1080, 1920

# ── Шрифты ────────────────────────────────────────────────────────────────────
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

# ── Темы блоков ───────────────────────────────────────────────────────────────
THEMES = {
    "today":    {"top": (8, 20, 55),  "bot": (15, 45, 90),  "accent": (79, 195, 247),  "glow": (30, 100, 200)},
    "tomorrow": {"top": (8, 30, 18),  "bot": (15, 55, 28),  "accent": (129, 199, 132), "glow": (20, 120, 40)},
    "next3":    {"top": (35, 22, 5),  "bot": (60, 38, 10),  "accent": (255, 183, 77),  "glow": (180, 80, 0)},
    "warnings": {"top": (45, 10, 5),  "bot": (75, 18, 8),   "accent": (255, 112, 67),  "glow": (200, 40, 10)},
    "trend":    {"top": (15, 12, 38), "bot": (28, 20, 65),  "accent": (206, 147, 216), "glow": (100, 40, 180)},
}
DEFAULT_THEME = THEMES["today"]

# ── Утилиты ───────────────────────────────────────────────────────────────────

def wrap_text(text, font, maxw, draw):
    """Перенос текста по ширине."""
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
    """Убирает markdown-разметку для отображения на слайде."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = text.replace('\u26a0\ufe0f', '⚠').replace('\u26a0', '⚠')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

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
    """Рисует мягкое свечение — накладываем несколько полупрозрачных кругов."""
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

def draw_icon_big(draw, icon_char, cx, cy, size=160, color=(255,255,255)):
    """Рисует эмодзи/иконку большим текстом по центру."""
    try:
        fnt = F(size)
        draw.text((cx, cy), icon_char, font=fnt, fill=color, anchor='mm')
    except:
        # fallback без anchor
        bb = draw.textbbox((0,0), icon_char, font=F(size))
        tw = bb[2]-bb[0]; th = bb[3]-bb[1]
        draw.text((cx-tw//2, cy-th//2), icon_char, font=F(size), fill=color)

# ── Основной рендер слайда ────────────────────────────────────────────────────

def render_slide(block, idx, total, out_png):
    theme = THEMES.get(block.get("key", ""), DEFAULT_THEME)
    acc   = theme["accent"]
    glow  = theme["glow"]

    img  = Image.new('RGBA', (W, H), (0, 0, 0, 255))
    draw = ImageDraw.Draw(img)

    # Фон
    draw_gradient(draw, theme["top"], theme["bot"])
    draw_stars(draw, seed=idx*7+1)

    # Свечение (мягкое пятно в центре)
    draw_glow_circle(img, W//2, H//2, 600, glow, alpha_max=45)

    draw = ImageDraw.Draw(img)  # пересоздаём после paste

    # Угловые маркеры
    draw_corner_marks(draw, acc)

    # Верхний бейдж: «Одесса · Погода»
    badge_y = 70
    badge_text = "ОДЕССА · ПОГОДА"
    draw.text((W//2, badge_y), badge_text, font=F(32, True), fill=(*acc, 180), anchor='mm')

    # Полоска прогресса слайдов
    seg_w = (W - 120) // total
    seg_y = 110
    for i in range(total):
        sx = 60 + i * (seg_w + 4)
        color_seg = acc if i <= idx else (80, 80, 100)
        draw.rounded_rectangle([sx, seg_y, sx+seg_w, seg_y+5], radius=3, fill=color_seg)

    # Иконка блока (большая)
    icon = block.get("icon", "🌤")
    icon_y = 310
    draw_icon_big(draw, icon, W//2, icon_y, size=160, color=(255, 255, 255))

    # Заголовок блока
    title = block.get("title", "").upper()
    draw.text((W//2, icon_y + 120), title, font=F(68, True), fill=(255,255,255), anchor='mm')

    # Разделитель
    div_y = icon_y + 200
    draw.rectangle([80, div_y, W-80, div_y+3], fill=(*acc, 120))

    # Текст блока
    raw_text = clean_text(block.get("text", ""))
    paragraphs = [p.strip() for p in raw_text.split('\n') if p.strip()]

    font_body = F(40)
    font_small = F(34)
    text_x = 70
    text_maxw = W - 140
    y = div_y + 40
    line_h = 56
    max_y = H - 260  # оставляем место под подпись

    for para in paragraphs:
        if y >= max_y: break
        lines = wrap_text(para, font_body, text_maxw, draw)
        for line in lines:
            if y >= max_y: break
            draw.text((text_x, y), line, font=font_body, fill=(210, 235, 255))
            y += line_h
        y += 16  # межабзацный отступ

    # Если текст не влез — многоточие
    if y >= max_y:
        draw.text((text_x, max_y - line_h), "...", font=font_small, fill=(*acc, 150))

    # Нижняя подпись
    bottom_y = H - 100
    now_str = datetime.now().strftime("%d.%m.%Y")
    draw.text((W//2, bottom_y), f"Синоптический прогноз · {now_str}",
              font=F(30), fill=(120, 150, 200), anchor='mm')
    # Маленькая акцентная линия снизу
    draw.rectangle([W//2 - 120, bottom_y + 38, W//2 + 120, bottom_y + 41], fill=(*acc, 100))

    img = img.convert('RGB')
    img.save(out_png, 'PNG')
    print(f"  [SLIDE] #{idx+1}/{total} '{block.get('title','')}' → {os.path.basename(out_png)}")

# ── FFmpeg: PNG + MP3 → видео-слайд ──────────────────────────────────────────

def make_slide_video(png_path, mp3_path, out_mp4, duration):
    """Создаёт видео из статичного PNG + аудио. duration — запасная длительность если mp3 не найден."""
    if os.path.exists(mp3_path):
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", png_path,
            "-i", mp3_path,
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
        print(f"  [FFM] Ошибка slide:\n{result.stderr[-500:]}")
        return False
    return True

# ── FFmpeg: concat всех слайдов ───────────────────────────────────────────────

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
        print(f"  [FFM] Ошибка concat:\n{result.stderr[-500:]}")
        return False
    size_mb = os.path.getsize(out_mp4) / 1024 / 1024
    print(f"  [FFM] ✅ Итоговое видео: {out_mp4} ({size_mb:.1f} Мб)")
    return True

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n  📹 Генерация вертикального видео (9:16) для TikTok...")

    if not os.path.exists(META_FILE):
        print(f"  Файл не найден: {META_FILE}")
        print("  Запустите сначала: python3 scripts/make_blocks.py")
        return

    with open(META_FILE, 'r', encoding='utf-8') as f:
        meta = json.load(f)

    blocks = meta.get("blocks", [])
    if not blocks:
        print("  Нет блоков в мета-файле")
        return

    if not FONT_REG_PATH:
        print("  ОШИБКА: кириллический шрифт не найден!")
        print("  pkg install fonts-dejavu  или  apt install fonts-freefont-ttf")
        return

    print(f"  Шрифт: {FONT_REG_PATH}")
    print(f"  Блоков: {len(blocks)}")
    os.makedirs(TMP_DIR, exist_ok=True)

    slide_mp4s = []
    total = len(blocks)

    for idx, block in enumerate(blocks):
        key      = block.get("key", f"block_{idx}")
        filename = block.get("filename", f"block_{idx}.mp3")
        mp3_path = os.path.join(BLOCKS_DIR, filename)
        duration = block.get("duration", 15)

        png_path = os.path.join(TMP_DIR, f"slide_{idx:02d}.png")
        mp4_path = os.path.join(TMP_DIR, f"slide_{idx:02d}.mp4")

        # 1. Рендерим картинку
        render_slide(block, idx, total, png_path)

        # 2. Делаем видео-слайд
        print(f"  [FFM] Конвертирую слайд {idx+1}/{total}...")
        ok = make_slide_video(png_path, mp3_path, mp4_path, duration)
        if ok:
            slide_mp4s.append(mp4_path)
        else:
            print(f"  [FFM] Пропускаю слайд {idx+1}")

        # Пауза между слайдами — даём телефону выдохнуть
        if idx < total - 1:
            print(f"  [WAIT] Пауза 3 сек перед следующим слайдом...")
            time.sleep(3)

    if not slide_mp4s:
        print("  Не удалось создать ни одного слайда")
        return

    # 3. Склеиваем
    print(f"\n  [FFM] Склеиваю {len(slide_mp4s)} слайдов...")
    ok = concat_videos(slide_mp4s, MP4_FILE)

    # 4. Чистим временные файлы
    if ok:
        for f in os.listdir(TMP_DIR):
            if f.endswith('.png') or (f.endswith('.mp4') and f.startswith('slide_')):
                try: os.remove(os.path.join(TMP_DIR, f))
                except: pass
        print("  [CLEAN] Временные файлы удалены")

    print("\n  Готово!" if ok else "\n  Завершено с ошибками.")

if __name__ == "__main__":
    main()
