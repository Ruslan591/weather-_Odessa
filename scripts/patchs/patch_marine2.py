FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''def fmt_marine(m, today_str=None):
    """Строки данных моря для промпта."""
    if not m: return ["  Данные недоступны"]
    lines = []
    if today_str:
        try:
            from datetime import datetime as _dt
            dt = _dt.strptime(today_str, "%Y-%m-%d")
            MONTH_RU2 = ['января','февраля','марта','апреля','мая','июня',
                         'июля','августа','сентября','октября','ноября','декабря']
            lines.append(f"  Дата: {dt.day} {MONTH_RU2[dt.month-1]}")
        except Exception:
            lines.append(f"  Дата: {today_str}")
    if m.get("sst") is not None:'''
NEW = '''def fmt_marine(m, today_str=None):
    """Строки данных моря для промпта (один день)."""
    if not m: return ["  Данные недоступны"]
    lines = []
    if m.get("sst") is not None:'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK2")
