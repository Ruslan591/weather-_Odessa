FILE = 'scripts/make_blocks.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''RATE = "-5%"'''
NEW = '''RATE = "-5%"
PITCH = "+10Hz"'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''    communicate = edge_tts.Communicate(text, voice=_selected_voice, rate=RATE)'''
NEW2 = '''    communicate = edge_tts.Communicate(text, voice=_selected_voice, rate=RATE, pitch=PITCH)'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
