FILE = 'scripts/make_video.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''def draw_info_card(img, block, acc):'''
NEW = '''def weather_icon_path(text, key):
    t = text.lower()
    if key == 'marine': return os.path.join(ICONS_DIR, 'wave.png')
    if key == 'trend':  return os.path.join(ICONS_DIR, 'trend.png')
    if key == 'next3':  return os.path.join(ICONS_DIR, 'calendar.png')
    if '\u0433\u0440\u043e\u0437\u0430' in t or '\u043c\u043e\u043b\u043d\u0438\u044f' in t: return os.path.join(ICONS_DIR, 'thunder.png')
    if '\u0434\u043e\u0436\u0434\u044c' in t or '\u043e\u0441\u0430\u0434\u043a\u0438' in t: return os.path.join(ICONS_DIR, 'rain.png')
    if '\u043e\u0431\u043b\u0430\u0447\u043d\u043e' in t or '\u043e\u0431\u043b\u0430\u043a\u0430' in t: return os.path.join(ICONS_DIR, 'cloudy.png')
    if '\u044f\u0441\u043d\u043e' in t or '\u0441\u043e\u043b\u043d\u0435\u0447\u043d\u043e' in t: return os.path.join(ICONS_DIR, 'sunny.png')
    return os.path.join(ICONS_DIR, 'partly_cloudy.png')

def paste_icon(img, icon_path, cx, cy, size=180):
    if not os.path.exists(icon_path): return
    icon = Image.open(icon_path).convert('RGBA')
    icon = icon.resize((size, size), Image.LANCZOS)
    img.paste(icon, (cx - size//2, cy - size//2), icon)

def extract_temp_range(text):
    import re
    short = text[:350]
    nums = [int(m) for m in re.findall(r\'(-?\\d{1,2})\u00b0C\', short)]
    nums = [n for n in nums if -20 <= n <= 45]
    if not nums: return None, None
    return min(nums), max(nums)

def draw_info_card(img, block, acc):'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
