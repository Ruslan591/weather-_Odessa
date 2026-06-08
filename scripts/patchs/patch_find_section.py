FILE = 'scripts/make_blocks.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''def find_section(sections, prefix):
    for key, val in sections.items():
        if key.startswith(prefix):
            return val
    return ''''''
NEW = '''def find_section(sections, *prefixes):
    for prefix in prefixes:
        for key, val in sections.items():
            if key.startswith(prefix):
                return val
    return ''''''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''        section_text = find_section(sections, section_title)'''
NEW2 = '''        ALT = {
            'today':   ('Сегодня', 'Утром и', 'Утром', 'Днём'),
            'tonight': ('Этой ночью', 'Ночью', 'Сегодня ночью'),
        }
        if key in ALT:
            section_text = find_section(sections, *ALT[key])
        else:
            section_text = find_section(sections, section_title)'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
