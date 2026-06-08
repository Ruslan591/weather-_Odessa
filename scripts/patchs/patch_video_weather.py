import re

FILE = 'scripts/make_video.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''def main():'''
NEW = '''def extract_temp_range(text):
    """Извлекает мин/макс температуру из текста блока."""
    nums = [int(m) for m in re.findall(r'(-?\d{1,2})\u00b0C', text)]
    if not nums: return None, None
    return min(nums), max(nums)

def weather_icon(text, key):
    """Определяет иконку погоды по тексту."""
    t = text.lower()
    if key == 'marine': return '\u2248\u007e'  # ~~ волны
    if '\u0433\u0440\u043e\u0437\u0430' in t or '\u043c\u043e\u043b\u043d\u0438\u044f' in t: return '\u26a1'  # \u26a1 гроза
    if '\u0434\u043e\u0436\u0434\u044c' in t or '\u043e\u0441\u0430\u0434\u043a\u0438' in t: return '\u2614'  # \u2614 дождь
    if '\u043e\u0431\u043b\u0430\u0447\u043d\u043e' in t or '\u043e\u0431\u043b\u0430\u043a\u0430' in t: return '\u2601'  # \u2601 облачно
    if '\u044f\u0441\u043d\u043e' in t or '\u0441\u043e\u043b\u043d\u0435\u0447\u043d\u043e' in t: return '\u2600'  # \u2600 ясно
    return '\u26c5'  # \u26c5 переменная облачность

def main():'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''    # Заголовок блока
    title = block.get("title", "").upper()
    draw.text((W//2, 400), title, font=F(72, True),
              fill=(255, 255, 255), anchor='mm')

    # Номер страницы (если больше одной)
    if total_pages > 1:
        draw.text((W//2, 455), f"{page_num + 1} / {total_pages}",
                  font=F(30), fill=(*acc, 150), anchor='mm')

    # Разделитель
    div_y = 490'''
NEW2 = '''    # Заголовок блока
    title = block.get("title", "").upper()
    draw.text((W//2, 400), title, font=F(72, True),
              fill=(255, 255, 255), anchor='mm')

    # Иконка погоды по тексту + экстремумы
    block_text = block.get("text", "")
    w_icon = weather_icon(block_text, key)
    t_min, t_max = extract_temp_range(block_text)
    if t_min is not None and t_min != t_max:
        temp_str = f"{w_icon}  {t_min}\u00b0..{t_max}\u00b0C"
    elif t_max is not None:
        temp_str = f"{w_icon}  {t_max}\u00b0C"
    else:
        temp_str = w_icon
    draw.text((W//2, 455), temp_str, font=F(38, True),
              fill=(*acc, 220), anchor='mm')

    # Номер страницы (если больше одной)
    if total_pages > 1:
        draw.text((W//2, 505), f"{page_num + 1} / {total_pages}",
                  font=F(28), fill=(*acc, 150), anchor='mm')

    # Разделитель
    div_y = 540'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
