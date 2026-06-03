FILE = 'js/fc-charts-atmo.js'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# 1. renderHumidityProfile — обновить LEVELS (добавить 925 и 300)
OLD = '''    const LEVELS=[
        {key:"relative_humidity_2m",    label:"2м",   color:"#74b9ff"},
        {key:"relative_humidity_850hPa",label:"850",  color:"#55efc4"},
        {key:"relative_humidity_700hPa",label:"700",  color:"#a29bfe"},
        {key:"relative_humidity_500hPa",label:"500",  color:"#fdcb6e"},
    ];
    const W=320,H=165,pad={t:24,r:10,b:28,l:38};'''
NEW = '''    const LEVELS=[
        {key:"relative_humidity_2m",    label:"2м",   color:"#74b9ff"},
        {key:"relative_humidity_925hPa",label:"925",  color:"#55efc4"},
        {key:"relative_humidity_850hPa",label:"850",  color:"#00cec9"},
        {key:"relative_humidity_700hPa",label:"700",  color:"#a29bfe"},
        {key:"relative_humidity_500hPa",label:"500",  color:"#fdcb6e"},
        {key:"relative_humidity_300hPa",label:"300",  color:"#ff8f00"},
    ];
    const W=320,H=165,pad={t:24,r:10,b:28,l:38};'''
assert OLD in src, "OLD humidity LEVELS not found"
src = src.replace(OLD, NEW, 1)

# 2. renderCloudProfile — обновить LAYERS (заменить на уровни давления)
OLD2 = '''    const LAYERS=[
        {key:"cloud_cover_low",  label:"Низкий",  sublabel:"<2км",   color:"#74b9ff"},
        {key:"cloud_cover_mid",  label:"Средний", sublabel:"2-6км",  color:"#a29bfe"},
        {key:"cloud_cover_high", label:"Высокий", sublabel:">6км",   color:"#fdcb6e"},
        {key:"cloud_cover",      label:"Общая",   sublabel:"total",  color:"#dfe6e9"},
    ];'''
NEW2 = '''    const LAYERS=[
        {key:"cloud_cover_925hPa", label:"925",   sublabel:"~800м",  color:"#74b9ff"},
        {key:"cloud_cover_850hPa", label:"850",   sublabel:"~1.5км", color:"#55efc4"},
        {key:"cloud_cover_700hPa", label:"700",   sublabel:"~3км",   color:"#00cec9"},
        {key:"cloud_cover_500hPa", label:"500",   sublabel:"~5.6км", color:"#a29bfe"},
        {key:"cloud_cover_300hPa", label:"300",   sublabel:"~9км",   color:"#fdcb6e"},
        {key:"cloud_cover",        label:"Общая", sublabel:"total",  color:"#dfe6e9"},
    ];'''
assert OLD2 in src, "OLD2 cloud LAYERS not found"
src = src.replace(OLD2, NEW2, 1)

# 3. Высота SVG для облачности — было H=190, теперь 6 рядов нужно чуть больше
OLD3 = '''    const W=320,H=190,pad={t:24,r:10,b:28,l:44};
    const iW=W-pad.l-pad.r,iH=H-pad.t-pad.b;
    const nL=LAYERS.length, trackH=iH/nL;'''
NEW3 = '''    const W=320,H=210,pad={t:24,r:10,b:28,l:44};
    const iW=W-pad.l-pad.r,iH=H-pad.t-pad.b;
    const nL=LAYERS.length, trackH=iH/nL;'''
assert OLD3 in src, "OLD3 height not found"
src = src.replace(OLD3, NEW3, 1)

# 4. analyzeCloudProfile — обновить ключи в вызове (использует LAYERS[0..3])
# В statsBox рендере LAYERS.map — ключи автоматически подтянутся из нового LAYERS
# Нужно исправить только _ccAvg вызовы в analyzeCloudProfile call
OLD4 = "        const avgLow=_ccAvg('cloud_cover_low'),avgMid=_ccAvg('cloud_cover_mid');\n        const avgHigh=_ccAvg('cloud_cover_high'),avgTotal=_ccAvg('cloud_cover');"
NEW4 = "        const avgLow=_ccAvg('cloud_cover_925hPa'),avgMid=_ccAvg('cloud_cover_700hPa');\n        const avgHigh=_ccAvg('cloud_cover_300hPa'),avgTotal=_ccAvg('cloud_cover');"
assert OLD4 in src, "OLD4 ccAvg not found"
src = src.replace(OLD4, NEW4, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("fc-charts-atmo.js OK")