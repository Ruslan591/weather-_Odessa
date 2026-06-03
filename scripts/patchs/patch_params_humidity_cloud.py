FILE = 'js/fc-params.js'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

# 1. Добавить два параметра в FC_PARAMS после polar_vortex
OLD = '''    // Морской прогноз
    { key:"wave",'''
NEW = '''    { key:"humidity_profile", label:"Влажность ↑",  color:"#55efc4", unit:"%",   field: h => h.relative_humidity_2m ?? null },
    { key:"cloud_profile",    label:"Облачность ↑", color:"#b2bec3", unit:"%",   field: h => h.cloud_cover ?? null },
    // Морской прогноз
    { key:"wave",'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

# 2. Добавить в группу Синоптика
OLD2 = '    { label: "Синоптика",    keys: ["geo_height","vert_vel","polar_vortex"] },'
NEW2 = '    { label: "Синоптика",    keys: ["geo_height","vert_vel","polar_vortex","humidity_profile","cloud_profile"] },'
assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")