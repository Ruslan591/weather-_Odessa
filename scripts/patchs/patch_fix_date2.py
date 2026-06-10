FILE = 'scripts/make_video.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD3 = '    card_bottom = draw_info_card(img, block, acc)\n    draw = ImageDraw.Draw(img)\n    div_y = card_bottom + 15'
NEW3 = '    card_bottom = draw_info_card(img, block, acc, base_dt)\n    draw = ImageDraw.Draw(img)\n    div_y = card_bottom + 15'

assert OLD3 in src, "OLD3 not found"
src = src.replace(OLD3, NEW3, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
