# -*- coding: utf-8 -*-
"""Патч панели 18091: вкладка-счёт «Claude» (позиции из /opt/trading-bot/positions/pos.py) + маршрут /api/claude.
Идемпотентен (повторный запуск ничего не меняет), перед правкой делает резервные копии *.bak_claude_tab.
Запуск: python patch_claude_tab.py [каталог_панели]"""
import os, shutil, sys
D = sys.argv[1] if len(sys.argv) > 1 else "/opt/trading-bot/classic"
PANEL = os.path.join(D, "classic_panel.py"); HTML = os.path.join(D, "classic_pos_html.py")

API = '''async def api_claude(req):
    """Счёт «Claude»: GET — снимок (счёт 7 $, 5x, позиции, журнал), POST {action: close|stop|trail, id, pct}. Данные: /opt/trading-bot/positions/pos.py."""
    import sys as _s
    if "/opt/trading-bot/positions" not in _s.path:
        _s.path.insert(0, "/opt/trading-bot/positions")
    try:
        import pos as _pos
        loop = asyncio.get_running_loop()
        if req.method == "POST":
            o = await req.json()
            res = await loop.run_in_executor(None, _pos.api_action, o)
        else:
            res = await loop.run_in_executor(None, _pos.snapshot)
    except Exception as e:
        res = {"error": str(e)}
    return web.json_response(res)


'''

JS = r"""function clAct(a,id){let pct=0;if(a==='close'){if(!confirm('Закрыть позицию #'+id+' по текущей цене?'))return}else{const v=prompt(a==='stop'?'Стоп: расстояние от текущей цены, %':'Трейлинг: расстояние от текущей цены, %','0.6');if(!v)return;pct=parseFloat(v.replace(',','.'));if(!(pct>0))return}
api('/api/claude',{action:a,id:id,pct:pct}).then(j=>{if(j.error){alert(j.error);return}S.cl=j;renderRuns()}).catch(e=>alert(e.message))}
function clTs(ms){return new Date(ms).toISOString().slice(5,16).replace('T',' ')}
function clChart(p){const C=p.cand.slice(-96),W=360,H=210,L=4,Rr=58;let lo=Math.min(...C.map(c=>c[3]),p.entry,p.stop,p.px),hi=Math.max(...C.map(c=>c[2]),p.entry,p.stop,p.px);const pad=(hi-lo)*.06||hi*.001;lo-=pad;hi+=pad;const X=i=>L+(i+.5)*(W-L-Rr)/C.length,Y=v=>H-8-(v-lo)/(hi-lo)*(H-16);let s="<svg viewBox='0 0 "+W+" "+H+"' style='width:100%;height:auto;background:#11151c;border-radius:8px'>";
C.forEach((c,i)=>{const col=c[4]>=c[1]?'#2ea043':'#da3633',x=X(i);s+="<line x1='"+x+"' x2='"+x+"' y1='"+Y(c[2])+"' y2='"+Y(c[3])+"' stroke='"+col+"'/><rect x='"+(x-1.4)+"' y='"+Y(Math.max(c[1],c[4]))+"' width='2.8' height='"+Math.max(1,Math.abs(Y(c[1])-Y(c[4])))+"' fill='"+col+"'/>"});
const ln=(v,col,t)=>{if(!(v>=lo&&v<=hi))return "";return "<line x1='"+L+"' x2='"+(W-Rr)+"' y1='"+Y(v)+"' y2='"+Y(v)+"' stroke='"+col+"' stroke-dasharray='4 3'/><text x='"+(W-Rr+3)+"' y='"+(Y(v)+3)+"' fill='"+col+"' font-size='9'>"+t+" "+v.toPrecision(5)+"</text>"};
return s+ln(p.entry,'#cfd6e0','вход')+ln(p.stop,'#f85149','стоп')+ln(p.be_px,'#d29922','БУ')+ln(p.tp,'#3fb950','цель')+ln(p.px,'#58a6ff','цена')+"</svg>"}
function clCard(){const C=S.cl;if(!C||C.error)return "<div class=card>Claude: "+((C&&C.error)||'нет данных')+"</div>";const a=C.account;
let h="<div class=card><div style='font-size:15px;font-weight:600'>Счёт «Claude»</div><div class=sm style='margin:4px 0'>Старт "+a.start+" $ · плечо "+a.lev+"x, изолированная маржа · позиция "+a.stake+" $ (маржа "+a.margin.toFixed(2)+" $) · бумага, цены Binance spot</div><div>Equity <b>"+money(a.equity)+"</b> · свободно "+money(a.free)+" · в марже "+money(a.open_margin)+" · реализовано "+smoney(a.realized)+" · плавающий "+smoney(a.unreal)+" · закрыто сделок "+a.closed+"</div></div>";
if(!C.open.length)h+="<div class=card>Открытых позиций нет.</div>";
C.open.forEach(p=>{const sh=p.side==='short',col=p.unreal_pct>=0?'#3fb950':'#f85149';
h+="<div class=card><div style='font-size:15px;font-weight:600'>#"+p.id+" "+p.sym+" "+(sh?'ШОРТ':'ЛОНГ')+" <span style='color:"+col+"'>"+(p.unreal_pct>=0?'+':'−')+Math.abs(p.unreal_pct).toFixed(2)+"% · "+smoney(p.unreal_usd)+" · "+p.r_now+"R</span></div>"
+"<div class=sm style='margin:4px 0'>открыта "+clTs(p.t_in)+" UTC · вход "+p.entry.toPrecision(6)+" · сейчас "+p.px.toPrecision(6)+"</div>"
+"<div class=sm>Стоп <b>"+p.stop.toPrecision(6)+"</b>"+(p.armed?" (безубыток/трейлинг включён"+(p.manual_trail?", ручной "+p.manual_trail+"%":"")+")":" (начальный "+p.stop0.toPrecision(6)+")")+(p.manual_stop?" · ручной стоп "+p.manual_stop+"%":"")+" · БУ при "+p.be_px.toPrecision(6)+" · цель "+p.tp.toPrecision(6)+" · ликвидация ≈ "+p.liq_px.toPrecision(5)+" · риск "+p.R_pct.toFixed(2)+"%</div>"
+"<div style='margin:8px 0'>"+clChart(p)+"</div>"
+"<div style='display:flex;gap:8px;flex-wrap:wrap'><button class=bad onclick='clAct(&quot;close&quot;,"+p.id+")'>Закрыть</button><button onclick='clAct(&quot;stop&quot;,"+p.id+")'>Стоп, %</button><button onclick='clAct(&quot;trail&quot;,"+p.id+")'>Трейлинг, %</button></div>"
+"<details style='margin-top:8px'><summary class=sm>Тезис</summary><div class=sm>"+(p.thesis||"")+"</div></details></div>"});
if(C.closed.length){h+="<details class=card data-k=clj open><summary style='font-size:15px;font-weight:600'>Журнал закрытых ("+C.closed.length+")</summary><div class=sc><table><tr><th>#</th><th>Пара</th><th>Сторона</th><th>Вход</th><th>Выход</th><th>Причина</th><th>Net %</th><th>R</th><th>$</th></tr>"+C.closed.map(p=>"<tr><td>"+p.id+"</td><td>"+p.sym+"</td><td>"+(p.side==='short'?'шорт':'лонг')+"</td><td>"+clTs(p.t_in)+"</td><td>"+clTs(p.t_out)+"</td><td>"+p.reason+"</td><td>"+(p.net_pct>=0?'+':'')+p.net_pct+"</td><td>"+p.r_mult+"</td><td>"+smoney(p.pnl_usd)+"</td></tr>").join("")+"</table></div></details>"}
return h}
"""

def patch_panel(s):
    if "async def api_claude(" in s:
        return s, False
    a = "async def api_cand(req):"
    assert s.count(a) == 1
    s = s.replace(a, API + a)
    r = '    app2.router.add_route("*", "/api/cand", api_cand)\n'
    assert s.count(r) == 1
    s = s.replace(r, r + '    app2.router.add_route("*", "/api/claude", api_claude)\n')
    return s, True

def patch_html(s):
    if "function clCard(" in s:
        return s, False
    def rep(a, b):
        nonlocal s
        assert s.count(a) == 1, a[:70]
        s = s.replace(a, b)
    rep("exp:['Эксп.','Эксперименты — параллельные проверки идей'],",
        "exp:['Эксп.','Эксперименты — параллельные проверки идей'],cl:['Claude','Счёт «Claude» — позиции, которые открывает и ведёт Claude (бумага, плечо 5x)'],")
    rep("['me','bot','both','cand','vp','exp'].map(k=>{const a=A[k]&&A[k].account;",
        "['me','bot','both','cand','vp','exp','cl'].map(k=>{const a=k==='cl'?(S.cl&&S.cl.account):(A[k]&&A[k].account);")
    rep("S.load=j.load||null;if(!S.screenAsked)",
        "S.load=j.load||null;try{S.cl=await api('/api/claude')}catch(e){S.cl={error:e.message}}if(!S.screenAsked)")
    rep("if(S.track==='exp'){FIN(loadLine()+trackBar()+expCard());return}",
        "if(S.track==='cl'){FIN(loadLine()+trackBar()+clCard());return}if(S.track==='exp'){FIN(loadLine()+trackBar()+expCard());return}")
    rep("function expCard(){", JS + "function expCard(){")
    return s, True

def main():
    for path, fn in ((PANEL, patch_panel), (HTML, patch_html)):
        s = open(path, encoding="utf-8").read()
        s2, ch = fn(s)
        if ch:
            shutil.copy(path, path + ".bak_claude_tab")
            open(path, "w", encoding="utf-8").write(s2)
        print(os.path.basename(path), "patched" if ch else "already patched")

if __name__ == "__main__":
    main()
