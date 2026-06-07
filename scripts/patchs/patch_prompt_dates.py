FILE = 'scripts/generate_ai_analysis.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# Формат дат: "9 июня–11 июня" → "9–11 июня"
OLD = '''    next_block = f"## Последующие дни, {fmt_date(next_start)}–{fmt_date(next_end)}"'''
NEW = '''    # Если месяц одинаковый — компактный формат "9–11 июня"
    if next_start.month == next_end.month:
        next_block = f"## Последующие дни, {next_start.day}–{fmt_date(next_end)}"
    else:
        next_block = f"## Последующие дни, {fmt_date(next_start)}–{fmt_date(next_end)}"'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

# Тенденция — если даты одинаковые
OLD2 = '''    tend_block = f"## Тенденция, {fmt_date(tend_start)}–{fmt_date(tend_end)}"'''
NEW2 = '''    if tend_start >= tend_end:
        tend_block = f"## Тенденция, после {fmt_date(tend_end)}"
    elif tend_start.month == tend_end.month:
        tend_block = f"## Тенденция, {tend_start.day}–{fmt_date(tend_end)}"
    else:
        tend_block = f"## Тенденция, {fmt_date(tend_start)}–{fmt_date(tend_end)}"'''

assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
