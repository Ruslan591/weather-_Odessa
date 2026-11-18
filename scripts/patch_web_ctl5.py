# -*- coding: utf-8 -*-
"""Страница онлайн / Telegram, версия 9 (поверх patch_web_ctl4.py): (1) «Следить» и «Отменить» в одной строке карточки слежения (подписи короткие);
(2) первый график слежения приходит СРАЗУ после нажатия «Следить» (кнопка в Telegram или галочка на странице), а не после закрытия следующей свечи 5m;
подпись первого поста «слежу с этого момента» вместо «слежу 0-ю свечу». Дальше по свечам как раньше (пролонгация). Экспресс не затронут (там слежение идёт с алерта).
Использование: python3 patch_web_ctl5.py FILE [FILE...]. Печатает APPLIED / ALREADY / ANCHOR_FAIL. Деплой: scripts/deploy_web_ctl5.sh. docs/topics/live_web.md"""
import os, sys

CTL_ROW = r'''function ctlRow(w){const r=document.createElement('div');r.style.cssText='display:flex;align-items:center;gap:28px;flex-wrap:wrap;margin-top:8px';
  for(const e of [keepRow(w),cancelRow(w)]){e.style.margin='0';e.style.padding='4px 0';r.append(e)}return r}
'''

EDITS = {
"index.html": [
 ("keeptxt", "w.keep?'Следить: бот ведёт без вопросов и не уходит в сон':(S.ctl?'Следить':'Следить (управление только на порту 18111)')", "'Следить'", "h('span',w.keep?'g':'mut','Следить')"),
 ("canceltxt", "S.ctl?'Отменить':'Отменить (управление только на порту 18111)'", "'Отменить'", "h('span','r','Отменить')"),
 ("fn", "function cancelRow(w){", CTL_ROW + "function cancelRow(w){", "function ctlRow("),
 ("use", "c.append(keepRow(w));c.append(cancelRow(w));we.append(c)", "c.append(ctlRow(w));we.append(c)", "c.append(ctlRow(w))"),
],
"tg_gate.py": [
 ("first", '"ok": True, "what": "follow"}); jobs.append(', '"ok": True, "what": "follow"}); (None if m.get("express") else emit({"type": "watch_update", "wid": x["id"], "first": 1})); jobs.append(', '"watch_update", "wid": x["id"], "first": 1}'),
],
"tg_bot.py": [
 ("ack", '"👁 Слежу. Следующий график пришлю после закрытия свечи."', '"👁 Слежу. Первый график ниже, дальше после закрытия каждой свечи."', "Первый график ниже"),
 ("keep", 'edit_watch(wid, "👁 Слежу (галочка на странице). Следующий график пришлю после закрытия свечи.", watch_buttons(wid, "update"))', 'edit_watch(wid, "👁 Слежу (галочка на странице). Первый график ниже.", []); send_watch(wid, "update")', "Первый график ниже.\", []"),
],
"tg_notify.py": [
 ("cap1", '· слежу %d-ю свечу"', '· слежу %s"', '· слежу %s"'),
 ("cap2", 'STATE_RU.get(w.get("state"), "—"), d, w.get("updates", 0))', 'STATE_RU.get(w.get("state"), "—"), d, ("%d-ю свечу" % w["updates"]) if w.get("updates") else "с этого момента")', '"с этого момента")'),
],
}


def patch(path):
    base = os.path.basename(path)
    if base not in EDITS: print("SKIP", base); return 0
    s = open(path, encoding="utf-8").read(); bad = 0; out = s
    for name, old, new, marker in EDITS[base]:
        if marker in out: print("ALREADY", base, name); continue
        if out.count(old) != 1: print("ANCHOR_FAIL", base, name, out.count(old)); bad += 1; continue
        out = out.replace(old, new, 1); print("APPLIED", base, name)
    if bad: return bad
    if out != s: open(path, "w", encoding="utf-8").write(out)
    return 0


if __name__ == "__main__":
    sys.exit(1 if sum(patch(p) for p in sys.argv[1:]) else 0)
