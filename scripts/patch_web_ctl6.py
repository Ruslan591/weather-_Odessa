# -*- coding: utf-8 -*-
"""Страница онлайн, версия 10 (поверх patch_web_ctl5.py): подтверждение отмены слежения и отказы действий на главной странице показываются своим нижним окном в стиле страницы
(pSheet / pToast, как окна на графике), а не системным confirm/alert браузера. Использование: python3 patch_web_ctl6.py index.html. Деплой: scripts/deploy_web_ctl6.sh. docs/topics/live_web.md"""
import os, sys

NEWFN = r'''function pSheet(title,detail,btns){let o=document.getElementById('psheet');if(o)o.remove();
  o=document.createElement('div');o.id='psheet';o.style.cssText='position:fixed;left:0;right:0;top:0;bottom:0;z-index:60;background:rgba(0,0,0,.5);display:flex;align-items:flex-end';
  const e=document.createElement('div');e.style.cssText='flex:1;margin:8px 8px calc(env(safe-area-inset-bottom,0px) + 8px);background:#1b2231;border:1px solid #3a4560;border-radius:12px;padding:12px';
  const t=h('div',null,title);t.style.cssText='font-weight:700;margin-bottom:4px';const d=h('div','mut small',detail);d.style.marginBottom='10px';
  const r=document.createElement('div');r.style.cssText='display:flex;gap:8px';
  for(const [l,f,c] of btns){const b=h('button','cb'+(c?' '+c:''),l);b.style.cssText='flex:1;padding:11px 0;font-size:14px';b.onclick=()=>{o.remove();f&&f()};r.append(b)}
  e.append(t,d,r);o.append(e);o.onclick=ev=>{if(ev.target===o){o.remove();btns[0][1]&&btns[0][1]()}};document.body.append(o)}
function pToast(t,ok){let e=document.getElementById('ptoast');if(!e){e=document.createElement('div');e.id='ptoast';e.style.cssText='position:fixed;left:12px;right:12px;top:calc(env(safe-area-inset-top,0px) + 60px);z-index:70;padding:9px 12px;border-radius:10px;background:#1b2231;border:1px solid #3a4560;font-size:13px';document.body.append(e)}
  e.textContent=t;e.style.borderColor=ok===false?'#f6465d':'#2ebd85';e.hidden=false;clearTimeout(pToast.t);pToast.t=setTimeout(()=>e.hidden=true,3500)}
'''
OLD_CH = r'''cb.onchange=()=>{if(!cb.checked)return;if(!confirm('Отменить слежение '+usd(w.sym).replace('USDT','')+'? В Telegram оно тоже закончится.')){cb.checked=false;return}
    const r=Math.random().toString(36).slice(2,8);pendW=r;send({q:'act',a:'watch_cancel',id:w.id,rid:r});toast('Отмена принята: слежение закроется в ближайшем цикле бота',true)};'''
NEW_CH = r'''cb.onchange=()=>{if(!cb.checked)return;
    pSheet('Отменить слежение '+usd(w.sym).replace('USDT','')+'?','В Telegram оно тоже закончится.',[['Не отменять',()=>{cb.checked=false}],['Отменить слежение',()=>{const r=Math.random().toString(36).slice(2,8);pendW=r;send({q:'act',a:'watch_cancel',id:w.id,rid:r});pToast('Отмена принята: слежение закроется в ближайшем цикле бота',true)},'red']])};'''
EDITS = [
 ("fn", "function cancelRow(w){", NEWFN + "function cancelRow(w){", "function pSheet("),
 ("chg", OLD_CH, NEW_CH, "pSheet('Отменить слежение '"),
 ("ack", "if(!m.ok)alert('Отказ: '+(m.err||'ошибка'));return}", "if(!m.ok)pToast('Отказ: '+(m.err||'ошибка'),false);return}", "pToast('Отказ: '"),
]
def patch(path):
    s = open(path, encoding="utf-8").read(); bad = 0; out = s
    for name, old, new, marker in EDITS:
        if marker in out: print("ALREADY", name); continue
        if out.count(old) != 1: print("ANCHOR_FAIL", name, out.count(old)); bad += 1; continue
        out = out.replace(old, new, 1); print("APPLIED", name)
    if bad: return bad
    if out != s: open(path, "w", encoding="utf-8").write(out)
    return 0
if __name__ == "__main__":
    sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
