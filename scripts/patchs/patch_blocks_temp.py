FILE = 'scripts/make_blocks.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''    blocks_meta = []'''
NEW = '''    # \u0427\u0438\u0442\u0430\u0435\u043c t_min/t_max \u0438\u0437 forecast_days.json
    _days_file = os.path.join(os.path.dirname(BLOCKS_DIR), "forecast_days.json")
    _days_by_idx = {}
    if os.path.exists(_days_file):
        try:
            import json as _json2
            _days = _json2.load(open(_days_file, encoding='utf-8'))
            for _i, _d in enumerate(_days):
                _days_by_idx[_i] = (_d.get('T',{}).get('min'), _d.get('T',{}).get('max'))
        except Exception: pass

    # \u0421\u043e\u043e\u0442\u0432\u0435\u0442\u0441\u0442\u0432\u0438\u0435 key -> \u0438\u043d\u0434\u0435\u043a\u0441 \u0434\u043d\u044f
    _key_to_day = {'today':0,'tonight':0,'tomorrow':1,'next3':2,'marine':None,'trend':None,'warnings':None}

    blocks_meta = []'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''            blocks_meta.append({
                "key":      key,
                "filename": filename,
                "path":     f"data/blocks/{filename}",
                "title":    display_title,
                "icon":     icon,
                "text":     section_text,
                "duration": get_mp3_duration(out_path),
                "pages":    page_files,
            })'''
NEW2 = '''            _day_idx = _key_to_day.get(key)
            _t_min, _t_max = _days_by_idx.get(_day_idx, (None, None)) if _day_idx is not None else (None, None)
            blocks_meta.append({
                "key":      key,
                "filename": filename,
                "path":     f"data/blocks/{filename}",
                "title":    display_title,
                "icon":     icon,
                "text":     section_text,
                "duration": get_mp3_duration(out_path),
                "pages":    page_files,
                "t_min":    _t_min,
                "t_max":    _t_max,
            })'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
