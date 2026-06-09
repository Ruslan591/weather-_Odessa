FILE = 'scripts/make_video.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''    # \u042d\u043a\u0441\u0442\u0440\u0435\u043c\u0443\u043c\u044b \u0442\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u044b
    t_min, t_max = extract_temp_range(block.get("text", ""))
    if t_min is not None and t_min != t_max:
        temp_str = f"{t_min}\u00b0..{t_max}\u00b0C"
    elif t_max is not None:
        temp_str = f"{t_max}\u00b0C"
    else:
        temp_str = ""
    if temp_str:
        draw.text((W//2, 455), temp_str, font=F(42, True),
                  fill=(*acc, 220), anchor=\'mm\')'''
NEW = '''    # \u042d\u043a\u0441\u0442\u0440\u0435\u043c\u0443\u043c\u044b \u0442\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u044b \u0438\u0437 \u043c\u0435\u0442\u0430
    t_min = block.get("t_min")
    t_max = block.get("t_max")
    if t_min is not None and t_max is not None and t_min != t_max:
        temp_str = f"{round(t_min)}\u00b0..{round(t_max)}\u00b0C"
    elif t_max is not None:
        temp_str = f"{round(t_max)}\u00b0C"
    else:
        temp_str = ""
    if temp_str:
        draw.text((W//2, 455), temp_str, font=F(42, True),
                  fill=(*acc, 220), anchor=\'mm\')'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
