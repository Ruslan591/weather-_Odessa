FILE = 'scripts/generate_ai_analysis.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = """            tenth = {'1':'одна','2':'две','3':'три','4':'четыре',
                     '5':'пять','6':'шесть','7':'семь','8':'восемь','9':'девять','0':'ноль'}
            return f"{int_part} целых {tenth.get(dec_part, dec_part)} десятых" """

NEW = """            tenth = {'1':'одна','2':'две','3':'три','4':'четыре',
                     '5':'пять','6':'шесть','7':'семь','8':'восемь','9':'девять','0':'ноль'}
            form = 'десятая' if dec_part == '1' else ('десятых' if dec_part in ('5','6','7','8','9','0') else 'десятых')
            return f"{int_part} целых {tenth.get(dec_part, dec_part)} {form}" """

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
