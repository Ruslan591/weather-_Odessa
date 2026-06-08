FILE = 'scripts/generate_ai_analysis.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = "    text = re.sub(r'(\\d+)\\.(\\d{1,2})\x08', decimal_to_words, text)"
NEW = "    text = re.sub(r'(\\d+)\\.(\\d{1,2})', decimal_to_words, text)"
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK step1")

# Перечитываем для следующих замен
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD2 = "    # Градусы\n    text = re.sub(r'(\\d+)\\s*°C', r' градуса Цельсия', text)\n    text = re.sub(r'(-\\d+)\\s*°C', r' градуса Цельсия', text)\n    text = text.replace('°C', 'градусов Цельсия')"
NEW2 = """    # Аббревиатуры — до градусов
    text = re.sub(r'(?i)индекс\\s+LI', 'индекс неустойчивости', text)
    text = re.sub(r'\\bLI\\b', 'индекс неустойчивости', text)
    text = text.replace('CAPE', 'индекс конвективной доступной энергии')
    text = text.replace('CIN', 'конвективное торможение')
    # Градусы со склонением
    def _grad(n):
        try: n = abs(int(float(str(n).replace(',','.')))) % 100
        except: return 'градусов'
        if 11 <= n <= 19: return 'градусов'
        r = n % 10
        if r == 1: return 'градус'
        if 2 <= r <= 4: return 'градуса'
        return 'градусов'
    text = re.sub(r'(-?\\d+(?:[.,]\\d+)?)\\s*\u00b0C', lambda m: f"{m.group(1)} {_grad(m.group(1))}", text)
    text = text.replace('\u00b0C', 'градусов')"""
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

OLD3 = "    # % -> процентов\n    text = re.sub(r'(\\d+)\\s*%', r' процентов', text)\n    # CAPE убрать аббревиатуру (уже должно быть в тексте словами, просто на случай)\n    text = text.replace('CAPE', 'индекс CAPE')"
NEW3 = """    # % со склонением
    def _proc(n):
        try: n = abs(int(n)) % 100
        except: return 'процентов'
        if 11 <= n <= 19: return 'процентов'
        r = n % 10
        if r == 1: return 'процент'
        if 2 <= r <= 4: return 'процента'
        return 'процентов'
    text = re.sub(r'(\\d+)\\s*%', lambda m: f"{m.group(1)} {_proc(m.group(1))}", text)"""
assert OLD3 in src, "OLD3 not found"
src = src.replace(OLD3, NEW3, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK step2+3")
