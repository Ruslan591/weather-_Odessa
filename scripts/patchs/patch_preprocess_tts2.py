FILE = 'scripts/generate_ai_analysis.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# Находим блок gradus через маркеры
START = '    # Градусы\n'
END = '    text = text.replace(\'\u00b0C\', \'\u0433\u0440\u0430\u0434\u0443\u0441\u043e\u0432 \u0426\u0435\u043b\u044c\u0441\u0438\u044f\')\n'
i1 = src.find(START)
i2 = src.find(END) + len(END)
assert i1 > 0 and i2 > i1, f"markers not found i1={i1} i2={i2}"
OLD2 = src[i1:i2]
print("OLD2:", repr(OLD2[:80]))

NEW2 = '''    # Аббревиатуры — до градусов
    import re as _re2
    text = _re2.sub(r'(?i)индекс\s+LI', 'индекс неустойчивости', text)
    text = _re2.sub(r'\bLI\b', 'индекс неустойчивости', text)
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
    text = _re2.sub(r'(-?\d+(?:[.,]\d+)?)\s*\u00b0C', lambda m: f"{m.group(1)} {_grad(m.group(1))}", text)
    text = text.replace('\u00b0C', 'градусов')
'''
src = src[:i1] + NEW2 + src[i2:]

# % со склонением
START3 = '    # % -> процентов\n'
END3 = '    text = text.replace(\'CAPE\', \'индекс CAPE\')\n'
i3 = src.find(START3)
i4 = src.find(END3) + len(END3)
assert i3 > 0 and i4 > i3, f"markers3 not found i3={i3} i4={i4}"

NEW3 = '''    # % со склонением
    def _proc(n):
        try: n = abs(int(n)) % 100
        except: return 'процентов'
        if 11 <= n <= 19: return 'процентов'
        r = n % 10
        if r == 1: return 'процент'
        if 2 <= r <= 4: return 'процента'
        return 'процентов'
    text = _re2.sub(r'(\d+)\s*%', lambda m: f"{m.group(1)} {_proc(m.group(1))}", text)
'''
src = src[:i3] + NEW3 + src[i4:]

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
