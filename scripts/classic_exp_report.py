# -*- coding: utf-8 -*-
"""Отчёт по экспериментальным прогонам classic (track exp): А — пробой по тренду канала (chan_dir=False), Б — лесенка БУ (be_l_at/be_l_lock).
Запуск на VPS: python3 classic_exp_report.py   (читает localhost:8091/api/runs). Считаются только сделки с t_in >= exp_since (честная проверка вперёд)."""
import json, urllib.request, collections
d = json.load(urllib.request.urlopen('http://localhost:8091/api/runs', timeout=120))
runs = d['runs']
bot = {}
for r in runs:
    if r.get('track') == 'bot' and r.get('mode') == 'propose':
        bot[(r['sym'], r['cfg']['tf'])] = r
def key(t): return (t['t_in'], t['side'])
def st(L):
    L = [t for t in L if not t['open']]
    n = len(L)
    if not n: return 'n=0'
    w = sum(1 for t in L if t['net'] > 0)
    return 'n=%d WR=%d%% avg=%+.3f sum=%+.1f' % (n, 100 * w // n, sum(t['net'] for t in L) / n, sum(t['net'] for t in L))
for tag, title in (('A', 'А: пробой по тренду (chan_dir=False) vs база'), ('B', 'Б: лесенка БУ vs база (те же сигналы)')):
    print('==', title)
    ea, ba, per = [], [], collections.defaultdict(lambda: ([], []))
    diffs = []; lad = 0
    for r in runs:
        c = r['cfg']
        if c.get('exp') != tag: continue
        s0 = c['exp_since']; b = bot.get((r['sym'], c['tf']))
        et = [t for t in (r.get('trades') or []) if t['t_in'] >= s0]
        bt = [t for t in ((b or {}).get('trades') or []) if t['t_in'] >= s0]
        ea += et; ba += bt
        per[c['tf']][0].extend(et); per[c['tf']][1].extend(bt)
        if tag == 'B':
            bm = {key(t): t for t in bt}
            for t in et:
                if t['reason'] == '\u043b\u0435\u0441\u0435\u043d\u043a\u0430': lad += 1
                o = bm.get(key(t))
                if o and not t['open'] and not o['open']: diffs.append(t['net'] - o['net'])
    print('эксперимент:', st(ea)); print('база       :', st(ba))
    for tf, (e_, b_) in sorted(per.items()): print('  ', tf, '| эксп', st(e_), '| база', st(b_))
    if tag == 'A':
        bk = {(r['sym'], r['cfg']['tf']): {key(t) for t in (r.get('trades') or [])} for r in bot.values()}
        extra = []
        for r in runs:
            c = r['cfg']
            if c.get('exp') == 'A':
                have = bk.get((r['sym'], c['tf']), set())
                extra += [t for t in r.get('trades') or [] if t['t_in'] >= c['exp_since'] and key(t) not in have]
        print('только у эксперимента (пробой по тренду):', st(extra))
    else:
        print('выходов по лесенке:', lad, '| парных сделок:', len(diffs), '| сумма разницы net: %+.2f' % sum(diffs))
