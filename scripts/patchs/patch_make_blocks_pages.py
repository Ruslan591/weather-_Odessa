FILE = 'scripts/make_blocks.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''import json, os, re, asyncio, argparse, random
from datetime import datetime, timezone, timedelta
import edge_tts'''

NEW = '''import json, os, re, asyncio, argparse, random
from datetime import datetime, timezone, timedelta
import edge_tts
from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1920
FONT_BODY_SIZE = 52
LINES_PER_PAGE = 15

FONT_CANDIDATES = [
    "/system/fonts/Roboto-Regular.ttf",
    "/system/fonts/NotoSans-Regular.ttf",
    "/data/data/com.termux/files/usr/share/fonts/TTF/DejaVuSans.ttf",
]

def _find_font():
    for p in FONT_CANDIDATES:
        if os.path.exists(p): return p
    return None

def _get_font():
    p = _find_font()
    if p:
        try: return ImageFont.truetype(p, FONT_BODY_SIZE)
        except: pass
    return ImageFont.load_default()

def _wrap_text(text, font, maxw, draw):
    words = text.split()
    lines = []; cur = []
    for w in words:
        t = ' '.join(cur + [w])
        if draw.textbbox((0,0), t, font=font)[2] > maxw and cur:
            lines.append(' '.join(cur)); cur = [w]
        else:
            cur.append(w)
    if cur: lines.append(' '.join(cur))
    return lines

def split_into_pages(text):
    raw = re.sub(r\'\\*+\', \'\', re.sub(r\'\\s+\', \' \', text)).strip()
    paragraphs = [p.strip() for p in raw.split(\'\\n\') if p.strip()]
    img = Image.new(\'RGB\', (W, H))
    draw = ImageDraw.Draw(img)
    font = _get_font()
    maxw = W - 130
    all_lines = []
    for para in paragraphs:
        all_lines.extend(_wrap_text(para, font, maxw, draw))
        all_lines.append(\'\')
    while all_lines and all_lines[-1] == \'\': all_lines.pop()
    pages = []
    i = 0
    while i < len(all_lines):
        pages.append(\' \'.join(l for l in all_lines[i:i+LINES_PER_PAGE] if l))
        i += LINES_PER_PAGE
    return pages'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''        if size_kb > 0:
            blocks_meta.append({
                "key":      key,
                "filename": filename,
                "path":     f"data/blocks/{filename}",
                "title":    display_title,
                "icon":     icon,
                "text":     section_text,
                "duration": get_mp3_duration(out_path),
            })'''

NEW2 = '''        if size_kb > 0:
            # Постраничные mp3
            pages = split_into_pages(section_text)
            page_files = []
            for pi, page_text in enumerate(pages):
                page_tts = DATE_PREFIX.get(key, '') + page_text if pi == 0 else page_text
                page_fn = filename.replace('.mp3', f'_p{pi+1}.mp3')
                page_path = os.path.join(BLOCKS_DIR, page_fn)
                psize = generate_block_tts(page_tts, page_path)
                if psize > 0:
                    page_files.append({
                        "filename": page_fn,
                        "path": f"data/blocks/{page_fn}",
                        "duration": get_mp3_duration(page_path),
                        "text": page_text,
                    })
            blocks_meta.append({
                "key":      key,
                "filename": filename,
                "path":     f"data/blocks/{filename}",
                "title":    display_title,
                "icon":     icon,
                "text":     section_text,
                "duration": get_mp3_duration(out_path),
                "pages":    page_files,
            })'''

assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
