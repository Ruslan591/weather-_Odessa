FILE = 'scripts/make_video.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCKS_DIR = os.path.join(BASE_DIR, "data", "blocks")'''
NEW = '''BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCKS_DIR = os.path.join(BASE_DIR, "data", "blocks")
ICONS_DIR  = os.path.join(BASE_DIR, "data", "icons")'''
assert OLD in src, "OLD1 not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''def main():'''
NEW2 = '''def weather_icon_path(text, key):
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

def main():'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

OLD3 = '# \u0418\u043a\u043e\u043d\u043a\u0430 \u0431\u043b\u043e\u043a\u0430\n    icon_char = BLOCK_ICONS.get(key, "\\u2600")\n    try:\n        draw.text((W//2, 280), icon_char, font=F(140, True),\n                  fill=(255, 255, 255), anchor=\'mm\')\n    except:\n        bb = draw.textbbox((0,0), icon_char, font=F(140, True))\n        tw = bb[2]-bb[0]; th = bb[3]-bb[1]\n        draw.text((W//2 - tw//2, 280 - th//2), icon_char,\n                  font=F(140, True), fill=(255, 255, 255))'
NEW3 = '# \u0418\u043a\u043e\u043d\u043a\u0430 \u0431\u043b\u043e\u043a\u0430 (PNG)\n    paste_icon(img, weather_icon_path(block.get("text",""), key), W//2, 280, size=180)\n    draw = ImageDraw.Draw(img)'
assert OLD3 in src, "OLD3 not found"
src = src.replace(OLD3, NEW3, 1)

OLD4 = '# \u0418\u043a\u043e\u043d\u043a\u0430 \u043f\u043e\u0433\u043e\u0434\u044b \u043f\u043e \u0442\u0435\u043a\u0441\u0442\u0443 + \u044d\u043a\u0441\u0442\u0440\u0435\u043c\u0443\u043c\u044b\n    block_text = block.get("text", "")\n    w_icon = weather_icon(block_text, key)\n    t_min, t_max = extract_temp_range(block_text)\n    if t_min is not None and t_min != t_max:\n        temp_str = f"{w_icon}  {t_min}\u00b0..{t_max}\u00b0C"\n    elif t_max is not None:\n        temp_str = f"{w_icon}  {t_max}\u00b0C"\n    else:\n        temp_str = w_icon\n    draw.text((W//2, 455), temp_str, font=F(38, True),\n              fill=(*acc, 220), anchor=\'mm\')'
NEW4 = '# \u042d\u043a\u0441\u0442\u0440\u0435\u043c\u0443\u043c\u044b \u0442\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u044b\n    t_min, t_max = extract_temp_range(block.get("text", ""))\n    if t_min is not None and t_min != t_max:\n        temp_str = f"{t_min}\u00b0..{t_max}\u00b0C"\n    elif t_max is not None:\n        temp_str = f"{t_max}\u00b0C"\n    else:\n        temp_str = ""\n    if temp_str:\n        draw.text((W//2, 455), temp_str, font=F(42, True),\n                  fill=(*acc, 220), anchor=\'mm\')'
assert OLD4 in src, "OLD4 not found"
src = src.replace(OLD4, NEW4, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
