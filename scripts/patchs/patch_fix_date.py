FILE = 'scripts/make_video.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''def draw_info_card(img, block, acc):
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
        date_str = now_utc.strftime("%Y-%m-%d")'''

NEW = '''def draw_info_card(img, block, acc, base_dt=None):
    from PIL import Image as PILImage
    key = block.get("key", "today")
    title = block.get("title", "").upper()
    t_min = block.get("t_min"); t_max = block.get("t_max")
    now_utc = base_dt if base_dt else datetime.now(timezone.utc)
    if key == "tomorrow":
        date_str = (now_utc + timedelta(days=1)).strftime("%Y-%m-%d")
    elif key == "next3":
        date_str = (now_utc + timedelta(days=2)).strftime("%Y-%m-%d")
    else:
        date_str = now_utc.strftime("%Y-%m-%d")'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''    with open(META_FILE, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    blocks = meta.get("blocks", [])'''

NEW2 = '''    with open(META_FILE, 'r', encoding='utf-8') as f:
        meta = json.load(f)
    blocks = meta.get("blocks", [])
    generated_at = meta.get("generated_at")
    base_dt = None
    if generated_at:
        try:
            base_dt = datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except: pass'''

assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

OLD3 = '''            card_bottom = draw_info_card(img, block, acc)'''
NEW3 = '''            card_bottom = draw_info_card(img, block, acc, base_dt)'''

assert OLD3 in src, "OLD3 not found"
src = src.replace(OLD3, NEW3, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
