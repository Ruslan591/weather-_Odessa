FILE = 'forecast.html'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()
OLD = '''    <div class="fc-param-row" id="fcParamRow"></div>
    <div class="fc-day-row" id="fcDayRow"></div>
    <div id="fcChartWrap" style="background:#161616;border-radius:10px;overflow:hidden;padding:4px 0 0;"></div>
    <div id="fcStats" class="fc-stats" style="display:none;margin-top:4px;"></div>
    <div id="fcAlertsBlock" style="margin-top:8px;"></div>'''
NEW = '''    <div class="fc-day-row" id="fcDayRow"></div>
    <div id="fcChartWrap" style="background:#161616;border-radius:10px;overflow:hidden;padding:4px 0 0;"></div>
    <div id="fcStats" class="fc-stats" style="display:none;margin-top:4px;"></div>
    <div id="fcAlertsBlock" style="margin-top:8px;"></div>
    <div class="fc-param-row" id="fcParamRow" style="margin-top:10px;"></div>'''
assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")