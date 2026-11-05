# -*- coding: utf-8 -*-
"""Патч панели 18091: переключатель счетов во вкладке «Claude» (Классика / AFD / Регрессия / AFD+регрессия).
classic_panel.py: api_claude при ?acct=afd|regr|combo пересылает запрос на микро-API счёта (127.0.0.1:18101/18102/18103, acct_api.py).
classic_pos_html.py: api() добавляет ?acct= к запросам /api/claude, clCard() получает панель выбора. Идемпотентно; бэкап в backup_acct_<время>.
Запуск: python patch_claude_acct.py [каталог_панели]"""
import os, shutil, sys, time, py_compile
D = sys.argv[1] if len(sys.argv) > 1 else "/opt/trading-bot/classic"
PAN = os.path.join(D, "classic_panel.py"); HTML = os.path.join(D, "classic_pos_html.py")
def rd(p): return open(p, encoding="utf-8").read()
def sub(s, old, new):
    assert s.count(old) == 1, "anchor count %d: %r" % (s.count(old), old[:60]); return s.replace(old, new)

PY_PROXY = '''    acct = req.query.get("acct", "")  # acct_proxy: счета AFD / Регрессия / Комбо живут в отдельных процессах (acct_api.py)
    _ports = {"afd": 18101, "regr": 18102, "combo": 18103}
    if acct in _ports:
        try:
            import aiohttp
            _u = "http://127.0.0.1:%d/api/claude" % _ports[acct]; _to = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=_to) as _cs:
                if req.method == "POST":
                    async with _cs.post(_u, json=await req.json()) as _r: res = await _r.json()
                else:
                    async with _cs.get(_u) as _r: res = await _r.json()
        except Exception as e:
            res = {"error": "acct " + acct + ": " + str(e)}
        return web.json_response(res)
    import sys as _s'''

JS_BAR = '''const CLA_LIST=[['','Классика'],['afd','AFD'],['regr','Регрессия'],['combo','AFD + регрессия']];
function clAcctBar(){return '<div class=card><div class=sm>Источник каналов счёта (параллельные бумажные счета, одинаковые правила):</div><div class=t>'+CLA_LIST.map(function(a){return '<button data-k="'+a[0]+'" class="'+((S.cla||'')===a[0]?'on':'')+'" onclick="clSetAcct(this.dataset.k)">'+a[1]+'</button>'}).join('')+'</div></div>'}
async function clSetAcct(k){S.cla=k;S.clpv=null;S.clcl=null;S.clpsel=null;try{S.cl=await api('/api/claude')}catch(e){S.cl={error:e.message}}renderRuns()}
function clCard(){return clAcctBar()+clCard0()}
function clCard0(){const C=S.cl;'''

def main():
    pan, html = rd(PAN), rd(HTML)
    if "acct_proxy" in pan and "CLA_LIST" in html: print("ALREADY_PATCHED"); return
    pan = sub(pan, "    import sys as _s", PY_PROXY)
    html = sub(html, "async function api(path,body){", "async function api(path,body){if(typeof path==='string'&&path.indexOf('/api/claude')===0&&S.cla)path+='?acct='+S.cla;")
    html = sub(html, "function clCard(){const C=S.cl;", JS_BAR)
    b = os.path.join(D, "backup_acct_" + time.strftime("%Y%m%d_%H%M%S")); os.makedirs(b)
    shutil.copy(PAN, b); shutil.copy(HTML, b)
    for p, s in ((PAN, pan), (HTML, html)):
        tmp = p + ".new"; open(tmp, "w", encoding="utf-8").write(s); py_compile.compile(tmp, doraise=True); os.replace(tmp, p)
    print("PATCHED backup=" + b)
main()
