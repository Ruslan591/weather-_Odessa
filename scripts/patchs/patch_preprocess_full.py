FILE = 'scripts/generate_ai_analysis.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# Находим и заменяем весь preprocess_tts через маркеры
START = 'def preprocess_tts(text):\n'
END = '    return text\n'
i1 = src.find(START)
i2 = src.find(END, i1) + len(END)
assert i1 > 0 and i2 > i1, f"not found i1={i1} i2={i2}"

NEW = '''def preprocess_tts(text):
    import re
    # Аббревиатуры
    text = re.sub(r'(?i)индекс\s+LI', 'индекс неустойчивости', text)
    text = re.sub(r'\bLI\b', 'индекс неустойчивости', text)
    text = text.replace('CAPE', 'индекс конвективной доступной энергии')
    text = text.replace('CIN', 'конвективное торможение')
    # Единицы давления
    text = text.replace('гПа', 'гектопаскалей')
    # Градусы со склонением
    def _grad(n):
        try: n = abs(int(float(str(n).replace(',','.')))) % 100
        except: return 'градусов'
        if 11 <= n <= 19: return 'градусов'
        r = n % 10
        if r == 1: return 'градус'
        if 2 <= r <= 4: return 'градуса'
        return 'градусов'
    text = re.sub(r'(-?\d+(?:[.,]\d+)?)\s*\u00b0C', lambda m: f"{m.group(1)} {_grad(m.group(1))}", text)
    text = text.replace('\u00b0C', 'градусов')
    # м/с
    text = re.sub(r'(\d+(?:[.,]\d+)?)\s*м/с', r'\1 метров в секунду', text)
    # мм осадков
    text = re.sub(r'(\d+(?:[.,]\d+)?)\s*мм', r'\1 миллиметра', text)
    # Дж/кг
    text = text.replace('Дж/кг', 'джоулей на килограмм')
    # Десятичные дроби
    def decimal_to_words(m):
        int_part = m.group(1)
        dec_part = m.group(2)
        if len(dec_part) == 1:
            words = {'1':'одна','2':'две','3':'три','4':'четыре',
                     '5':'пять','6':'шесть','7':'семь','8':'восемь','9':'девять','0':'ноль'}
            form = 'десятая' if dec_part == '1' else 'десятых'
            return f"{int_part} целых {words.get(dec_part, dec_part)} {form}"
        return f"{int_part} целых {dec_part} сотых"
    text = re.sub(r'(\d+)\.(\d{1,2})', decimal_to_words, text)
    text = re.sub(r'(\d+),(\d{1,2})', decimal_to_words, text)
    # % со склонением
    def _proc(n):
        try: n = abs(int(n)) % 100
        except: return 'процентов'
        if 11 <= n <= 19: return 'процентов'
        r = n % 10
        if r == 1: return 'процент'
        if 2 <= r <= 4: return 'процента'
        return 'процентов'
    text = re.sub(r'(\d+)\s*%', lambda m: f"{m.group(1)} {_proc(m.group(1))}", text)
    # Убрать решётки markdown
    text = re.sub(r'#+\s*', '', text)
    # Убрать ** *
    text = re.sub(r'\*+', '', text)
    return text
'''
src = src[:i1] + NEW + src[i2:]
with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
