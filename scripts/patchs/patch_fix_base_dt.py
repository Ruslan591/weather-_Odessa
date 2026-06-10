FILE = 'scripts/make_video.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()
OLD = '    card_bottom = draw_info_card(img, block, acc, base_dt)'
NEW = '    card_bottom = draw_info_card(img, block, acc)'
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
