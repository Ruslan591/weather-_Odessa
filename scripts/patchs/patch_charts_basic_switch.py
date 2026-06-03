FILE = 'js/fc-charts-basic.js'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''    if(_fcParam === "polar_vortex") return renderPolarVortex(hours, times);
    const _cfgCheck = FC_PARAMS.find(p => p.key === _fcParam);'''
NEW = '''    if(_fcParam === "polar_vortex")    return renderPolarVortex(hours, times);
    if(_fcParam === "humidity_profile") return renderHumidityProfile(hours, times);
    if(_fcParam === "cloud_profile")    return renderCloudProfile(hours, times);
    const _cfgCheck = FC_PARAMS.find(p => p.key === _fcParam);'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")