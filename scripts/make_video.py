#!/usr/bin/env python3
"""
make_video.py — генерация видео-обзора погоды из forecast_analysis_claude.json
Запуск: python3 scripts/make_video.py
Результат: data/forecast_video.mp4

Зависимости: pip install edge-tts Pillow --break-system-packages
             pkg install ffmpeg
"""

import json, os, re, math, asyncio, subprocess
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import edge_tts

BASE_DIR  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_FILE = os.path.join(BASE_DIR, "data", "forecast_analysis_claude.json")
OUT_DIR   = os.path.join(BASE_DIR, "data")
IMG_FILE  = os.path.join(OUT_DIR, "forecast_bg.png")
MP3_FILE  = os.path.join(OUT_DIR, "forecast_voice.mp3")
MP4_FILE  = os.path.join(OUT_DIR, "forecast_video.mp4")

W, H = 1280, 720

# ── Шрифты ────────────────────────────────────────────────────────────────────
# Ищем кириллический шрифт в нескольких местах
FONT_CANDIDATES = [
    # Android системные
    "/system/fonts/Roboto-Regular.ttf",
    "/system/fonts/NotoSans-Regular.ttf",
    # Termux
    "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/data/data/com.termux/files/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    # Linux сервер
    "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]
FONT_BOLD_CANDIDATES = [
    "/system/fonts/Roboto-Bold.ttf",
    "/system/fonts/NotoSans-Bold.ttf",
    "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

def find_font(candidates):
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

FONT_REG_PATH  = find_font(FONT_CANDIDATES)
FONT_BOLD_PATH = find_font(FONT_BOLD_CANDIDATES) or FONT_REG_PATH

def F(size, bold=False):
    path = FONT_BOLD_PATH if bold else FONT_REG_PATH
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()

# ── Цвета ─────────────────────────────────────────────────────────────────────
BG_TOP    = (8, 15, 35)
BG_BOTTOM = (18, 35, 70)
ACCENT    = (64, 180, 255)
ACCENT2   = (120, 220, 180)
WARNING   = (255, 160, 60)
TEXT_MAIN = (230, 240, 255)
TEXT_DIM  = (140, 160, 200)
DIVIDER   = (40, 70, 120)

# ── Парсинг ───────────────────────────────────────────────────────────────────

def parse_sections(text):
    d = {}; k = None; ls = []
    for line in text.split('\n'):
        if line.startswith('## '):
            if k: d[k] = '\n'.join(ls).strip()
            k = line[3:].strip(); ls = []
        else:
            ls.append(line)
    if k: d[k] = '\n'.join(ls).strip()
    return d

def extract_temp(text):
    m = re.search(r'от\s+(-?\d+)[°\s]*C[^\d]*до\s+(-?\d+)[°\s]*C', text)
    if m: return int(m.group(1)), int(m.group(2))
    m = re.search(r'(-?\d+)[°\s]*C\s+ночью.*?(\d+)[°\s]*C', text, re.S)
    if m: return int(m.group(1)), int(m.group(2))
    m = re.search(r'до\s+(\d+)[°\s]*C', text)
    if m: return None, int(m.group(1))
    return None, None

def detect_weather(text):
    t = text.lower()
    if any(w in t for w in ['гроз', 'шквал', 'ливн']): return 'storm'
    if any(w in t for w in ['осадк', 'дожд']): return 'rain'
    if any(w in t for w in ['пасмурн', 'сплошн']): return 'cloudy'
    if any(w in t for w in ['малооблач', 'ясн', 'антициклон', 'безоблачн']): return 'clear'
    return 'partly'

def wrap(text, font, maxw, draw):
    words = text.split(); lines = []; cur = []
    for w in words:
        t = ' '.join(cur + [w])
        if draw.textbbox((0, 0), t, font=font)[2] > maxw and cur:
            lines.append(' '.join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur: lines.append(' '.join(cur))
    return lines

def clean_for_tts(text):
    text = re.sub(r'##\s+', '', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = text.replace('\u26a0\ufe0f', 'Внимание!')
    text = text.replace('\u26a0', 'Внимание!')
    text = text.replace('\u2019', "'")
    text = re.sub(r'(-?\d+)\s*\u00b0C', r'\1 градусов', text)
    text = text.replace('\u00b0', ' градусов')
    text = text.replace('%', ' процентов')
    text = re.sub(r'\bгПа\b', ' гектопаскалей', text)
    text = re.sub(r'\bм/с\b', ' метров в секунду', text)
    text = re.sub(r'\bДж/кг\b', ' джоулей на килограмм', text)
    text = re.sub(r'\bLI\b', 'индекс неустойчивости', text)
    text = re.sub(r'\bCAPE\b', 'конвективная энергия', text)
    text = re.sub(r'\bCIN\b', 'конвективное торможение', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# ── Рисование ─────────────────────────────────────────────────────────────────

def draw_gradient(draw):
    for y in range(H):
        t = y / H
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

def draw_stars(draw):
    import random; rng = random.Random(42)
    for _ in range(100):
        x = rng.randint(0, W); y = rng.randint(0, H // 2)
        sz = rng.choice([1, 1, 2]); a = rng.randint(70, 180)
        draw.ellipse([x, y, x+sz, y+sz], fill=(a, min(a+20, 255), 255))

def draw_icon(draw, wtype, cx, cy, s=72):
    if wtype == 'clear':
        r = s // 2
        draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(255, 220, 60))
        for a in range(0, 360, 45):
            rad = math.radians(a)
            x1 = cx + int((r+8)*math.cos(rad)); y1 = cy + int((r+8)*math.sin(rad))
            x2 = cx + int((r+22)*math.cos(rad)); y2 = cy + int((r+22)*math.sin(rad))
            draw.line([x1, y1, x2, y2], fill=(255, 220, 60), width=4)
    elif wtype == 'storm':
        cr = s // 2
        draw.ellipse([cx-cr, cy-cr//3-15, cx+cr//2, cy+cr//2-15], fill=(50, 60, 90))
        draw.ellipse([cx-cr//3, cy-cr-15, cx+cr, cy+cr//3-15], fill=(65, 75, 105))
        draw.ellipse([cx-cr//4, cy-cr//2-15, cx+cr//4, cy+cr//4-15], fill=(80, 90, 120))
        draw.polygon([
            (cx+5, cy-5), (cx-10, cy+20), (cx+2, cy+20),
            (cx-12, cy+45), (cx+15, cy+15), (cx+5, cy+15), (cx+5, cy-5)
        ], fill=(255, 230, 50))
    elif wtype == 'rain':
        cr = s // 2
        draw.ellipse([cx-cr, cy-cr//3-10, cx+cr//2, cy+cr//2-10], fill=(90, 110, 150))
        draw.ellipse([cx-cr//3, cy-cr-10, cx+cr, cy+cr//3-10], fill=(105, 125, 165))
        draw.ellipse([cx-cr//4, cy-cr//2-10, cx+cr//4, cy+cr//4-10], fill=(120, 140, 180))
        for dx, dy in [(-22, 18), (0, 28), (22, 18), (-11, 40), (11, 40)]:
            draw.ellipse([cx+dx-3, cy+dy-3, cx+dx+3, cy+dy+10], fill=(90, 170, 255))
    elif wtype == 'cloudy':
        cr = s // 2
        draw.ellipse([cx-cr, cy-cr//3, cx+cr//2, cy+cr//2], fill=(130, 150, 185))
        draw.ellipse([cx-cr//3, cy-cr, cx+cr, cy+cr//3], fill=(150, 170, 205))
        draw.ellipse([cx, cy-cr//3, cx+cr+cr//3, cy+cr//2], fill=(140, 160, 195))
    else:  # partly
        r = s // 3
        draw.ellipse([cx-r-10, cy-r-10, cx+r-10, cy+r-10], fill=(255, 220, 60))
        cr = s // 3
        draw.ellipse([cx-cr+5, cy-cr//2+5, cx+cr+5, cy+cr//2+5], fill=(180, 200, 230))
        draw.ellipse([cx-cr//2+15, cy-cr+5, cx+cr//2+15, cy+cr-10], fill=(200, 215, 240))
        draw.ellipse([cx+5, cy-cr//3+5, cx+cr+15, cy+cr//2+5], fill=(190, 210, 235))

# ── Генерация картинки ────────────────────────────────────────────────────────

def create_image(data):
    text = data.get('text', '')
    ga = data.get('generated_at', '')
    try:
        dt = datetime.fromisoformat(ga.replace('Z', '+00:00'))
        ds = dt.strftime('%d %B %Y').lstrip('0')
        for en, ru in [
            ('January','января'),('February','февраля'),('March','марта'),
            ('April','апреля'),('May','мая'),('June','июня'),
            ('July','июля'),('August','августа'),('September','сентября'),
            ('October','октября'),('November','ноября'),('December','декабря')
        ]:
            ds = ds.replace(en, ru)
    except:
        ds = datetime.now().strftime('%d.%m.%Y')

    S = parse_sections(text)
    today   = S.get('Сегодня', '')
    tomorrow = S.get('Завтра', '')
    warn    = S.get('\u26a0\ufe0f Предупреждения', S.get('Предупреждения', ''))
    trend   = S.get('Тенденция', '')
    next3   = S.get('Последующие 3 дня', '')

    t_min, t_max = extract_temp(today)
    wt = detect_weather(today)

    img = Image.new('RGB', (W, H))
    draw = ImageDraw.Draw(img)
    draw_gradient(draw)
    draw_stars(draw)

    # Левый акцент
    draw.rectangle([6, 42, 9, H-42], fill=ACCENT)

    # Верхняя строка
    draw.text((28, 18), ds, font=F(18), fill=TEXT_DIM)
    draw.text((W-28, 18), 'Синоптический прогноз', font=F(18), fill=TEXT_DIM, anchor='ra')
    draw.rectangle([22, 50, W-22, 52], fill=DIVIDER)

    # Левая колонка: иконка + температура
    LCX = 110
    draw_icon(draw, wt, LCX, 150, s=72)
    temp_str = (f'{t_min}°...{t_max}°' if t_min is not None and t_max is not None
                else (f'до {t_max}°' if t_max else '—'))
    draw.text((LCX, 232), temp_str, font=F(38, True), fill=TEXT_MAIN, anchor='mm')
    wlbl = {'clear':'Ясно','partly':'Перем. облачно','cloudy':'Облачно','rain':'Осадки','storm':'Гроза'}
    draw.text((LCX, 262), wlbl[wt], font=F(13), fill=TEXT_DIM, anchor='mm')

    # Разделитель лев/центр
    draw.rectangle([218, 62, 221, H-42], fill=DIVIDER)

    CX = 235; RX = W - 245; CW = RX - CX - 20

    # СЕГОДНЯ
    draw.text((CX, 64), 'СЕГОДНЯ', font=F(12, True), fill=ACCENT)
    y = 86
    for line in wrap(today, F(17), CW, draw)[:6]:
        draw.text((CX, y), line, font=F(17), fill=TEXT_MAIN); y += 26

    # ЗАВТРА
    draw.rectangle([CX, y+6, CX+CW, y+7], fill=DIVIDER); y += 16
    draw.text((CX, y), 'ЗАВТРА', font=F(12, True), fill=ACCENT2); y += 22
    tm, tM = extract_temp(tomorrow)
    if tM:
        draw.text((CX, y), f'до {tM}°', font=F(26, True), fill=TEXT_MAIN); y += 32
    for line in wrap(tomorrow, F(14), CW, draw)[:4]:
        draw.text((CX, y), line, font=F(14), fill=TEXT_DIM); y += 20

    # Разделитель центр/прав
    draw.rectangle([RX-12, 62, RX-9, H-42], fill=DIVIDER)

    # ДАЛЕЕ
    draw.text((RX, 64), 'ДАЛЕЕ', font=F(12, True), fill=TEXT_DIM)
    ry = 86
    for line in wrap(next3, F(13), 230, draw)[:8]:
        draw.text((RX, ry), line, font=F(13), fill=TEXT_DIM); ry += 20

    # ВНИМАНИЕ
    if warn:
        ry = max(ry + 10, 330)
        wlines = wrap(warn, F(13), 225, draw)[:5]
        bh = len(wlines) * 19 + 32
        draw.rounded_rectangle([RX-12, ry-8, RX+237, ry+bh], radius=6,
                                fill=(55, 22, 5), outline=WARNING, width=1)
        draw.text((RX, ry), 'ВНИМАНИЕ', font=F(13, True), fill=WARNING); ry += 20
        for line in wlines:
            draw.text((RX, ry), line, font=F(11), fill=(255, 200, 130)); ry += 18

    # ТЕНДЕНЦИЯ
    draw.rectangle([22, H-68, W-22, H-66], fill=DIVIDER)
    tlines = wrap(trend, F(13), W-185, draw)
    draw.text((28, H-56), 'ТЕНДЕНЦИЯ:', font=F(13, True), fill=ACCENT)
    if tlines: draw.text((175, H-56), tlines[0], font=F(13), fill=TEXT_DIM)
    if len(tlines) > 1: draw.text((28, H-36), tlines[1], font=F(13), fill=TEXT_DIM)

    # Угловые маркеры
    c = 14
    for px, py, dx, dy in [
        (22,22,1,0),(22,22,0,1),(W-22,22,-1,0),(W-22,22,0,1),
        (22,H-20,1,0),(22,H-20,0,-1),(W-22,H-20,-1,0),(W-22,H-20,0,-1)
    ]:
        draw.line([px, py, px+dx*c, py+dy*c], fill=ACCENT, width=2)

    img.save(IMG_FILE, 'PNG')
    print(f"  [IMG] Сохранено: {IMG_FILE}")

# ── TTS ───────────────────────────────────────────────────────────────────────

async def _tts_async(text):
    comm = edge_tts.Communicate(text, voice="ru-RU-SvetlanaNeural", rate="-5%")
    await comm.save(MP3_FILE)

def generate_tts(text):
    clean = clean_for_tts(text)
    print(f"  [TTS] Генерирую озвучку ({len(clean)} символов)...")
    asyncio.run(_tts_async(clean))
    size_kb = os.path.getsize(MP3_FILE) // 1024
    print(f"  [TTS] Сохранено: {MP3_FILE} ({size_kb} кб)")

# ── FFMPEG ────────────────────────────────────────────────────────────────────

def make_video():
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", IMG_FILE,
        "-i", MP3_FILE,
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        MP4_FILE
    ]
    print("  [FFM] Создаю видео...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        size_mb = os.path.getsize(MP4_FILE) / 1024 / 1024
        print(f"  [FFM] Готово: {MP4_FILE} ({size_mb:.1f} Мб)")
    else:
        print(f"  [FFM] Ошибка ffmpeg:\n{result.stderr[-800:]}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n  Генерация видео-обзора погоды...")
    if not os.path.exists(JSON_FILE):
        print(f"  Файл не найден: {JSON_FILE}"); return
    with open(JSON_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not data.get('text'):
        print("  Нет текста в JSON"); return

    if not FONT_REG_PATH:
        print("  ОШИБКА: кириллический шрифт не найден!")
        print("  Установите: pkg install fonts-dejavu  или  apt install fonts-freefont-ttf")
        return

    print(f"  Шрифт: {FONT_REG_PATH}")
    create_image(data)
    generate_tts(data['text'])
    make_video()
    print("\n  Готово!")

if __name__ == "__main__":
    main()
