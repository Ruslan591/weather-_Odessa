FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()
OLD = '''            f"  Стратосфера Z: 50={gp.get('Z50')} 30={gp.get('Z30')} 10={gp.get('Z10')}",'''
NEW = '''            f"  Стратосфера Z: 150={gp.get('Z150')} 100={gp.get('Z100')} 50={gp.get('Z50')} 30={gp.get('Z30')} 10={gp.get('Z10')}",'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
OLD2 = '''            f"  ВЕТЕР: 925={wp.get('925',{}).get('s')}км/ч {wdir(wp.get('925',{}).get('d'))}  850={wp.get('850',{}).get('s')} {wdir(wp.get('850',{}).get('d'))}  700={wp.get('700',{}).get('s')} {wdir(wp.get('700',{}).get('d'))}  500={wp.get('500',{}).get('s')} {wdir(wp.get('500',{}).get('d'))}  300={wp.get('300',{}).get('s')} {wdir(wp.get('300',{}).get('d'))}  200={wp.get('200',{}).get('s')} {wdir(wp.get('200',{}).get('d'))}",'''
NEW2 = '''            f"  ВЕТЕР: 925={wp.get('925',{}).get('s')}км/ч {wdir(wp.get('925',{}).get('d'))}  850={wp.get('850',{}).get('s')} {wdir(wp.get('850',{}).get('d'))}  700={wp.get('700',{}).get('s')} {wdir(wp.get('700',{}).get('d'))}  500={wp.get('500',{}).get('s')} {wdir(wp.get('500',{}).get('d'))}  300={wp.get('300',{}).get('s')} {wdir(wp.get('300',{}).get('d'))}  200={wp.get('200',{}).get('s')} {wdir(wp.get('200',{}).get('d'))}  100={wp.get('100',{}).get('s')} {wdir(wp.get('100',{}).get('d'))}  50={wp.get('50',{}).get('s')} {wdir(wp.get('50',{}).get('d'))}",'''
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)
OLD3 = '''        "вертикальное движение (омега), влажность, облачность, CAPE, LI, нулевую изотерму.",'''
NEW3 = '''        "вертикальное движение (омега), влажность, облачность, CAPE, LI, нулевую изотерму.",
        "Также учитывай состояние стратосферы и полярного вихря (геопотенциал и температура",
        "на 150-10 гПа, ветер на 100 и 50 гПа): если видна резкая аномалия (потепление",
        "стратосферы, ослабление/разрушение зонального потока) — упомяни возможное влияние",
        "на погоду в среднесрочной перспективе.",'''
assert OLD3 in src, "OLD3 not found"
src = src.replace(OLD3, NEW3, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK3")
