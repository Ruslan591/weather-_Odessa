#!/usr/bin/env python3
import json
import time
import os
from pathlib import Path
from aiohttp import web

RUNS_FILE = '/opt/trading-bot/classic/runs.json'

def load_runs():
    try:
        with open(RUNS_FILE) as f:
            return json.load(f)
    except:
        return []

def calc_stats(trades):
    if not trades:
        return {'total': 0, 'win': 0, 'loss': 0, 'profit': 0, 'max_dd': 0, 'pct': 0}
    
    profits = [t.get('net', 0) for t in trades]
    total = len(trades)
    win = sum(1 for p in profits if p > 0)
    loss = sum(1 for p in profits if p < 0)
    profit = sum(profits)
    pct = (win / total * 100) if total else 0
    
    # Простой расчёт макс просадки
    cumsum = 0
    max_cum = 0
    max_dd = 0
    for p in profits:
        cumsum += p
        if cumsum > max_cum:
            max_cum = cumsum
        dd = max_cum - cumsum
        if dd > max_dd:
            max_dd = dd
    
    return {'total': total, 'win': win, 'loss': loss, 'profit': profit, 'max_dd': max_dd, 'pct': pct}

async def index(request):
    runs = load_runs()
    
    html = '''<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Прогоны | Классика</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { 
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #0f1419;
    color: #e0e0e0;
    padding: 20px;
}
.container { max-width: 1400px; margin: 0 auto; }
header { 
    margin-bottom: 40px;
    border-bottom: 2px solid #1a1f2e;
    padding-bottom: 20px;
}
h1 { 
    font-size: 32px;
    font-weight: 600;
    margin-bottom: 5px;
}
.subtitle { color: #888; font-size: 14px; }

.filters {
    display: flex;
    gap: 15px;
    margin-bottom: 30px;
    flex-wrap: wrap;
}
.filter-group {
    display: flex;
    gap: 8px;
}
.filter-group label {
    font-size: 12px;
    text-transform: uppercase;
    color: #888;
    display: flex;
    align-items: center;
}
.filter-group select {
    padding: 8px 12px;
    background: #1a1f2e;
    border: 1px solid #2a3142;
    color: #e0e0e0;
    border-radius: 6px;
    font-size: 14px;
    cursor: pointer;
}
.filter-group select:hover {
    border-color: #3a4152;
}

.runs-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 20px;
    margin-bottom: 40px;
}
.run-card {
    background: #1a1f2e;
    border: 1px solid #2a3142;
    border-radius: 12px;
    padding: 20px;
    cursor: pointer;
    transition: all 0.2s;
}
.run-card:hover {
    border-color: #3a4152;
    background: #202730;
    transform: translateY(-2px);
}
.run-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 15px;
}
.run-name {
    font-weight: 600;
    font-size: 15px;
    margin-bottom: 5px;
}
.run-pair {
    font-size: 13px;
    color: #888;
}
.run-id {
    background: #0f1419;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 12px;
    color: #888;
}
.stats-row {
    display: flex;
    justify-content: space-between;
    margin-bottom: 10px;
    font-size: 13px;
}
.stat-label { color: #888; }
.stat-value { 
    font-weight: 600;
    font-family: 'Courier New', monospace;
}
.stat-profit { color: #4ade80; }
.stat-loss { color: #ef4444; }
.stat-neutral { color: #888; }

.modal {
    display: none;
    position: fixed;
    z-index: 1000;
    left: 0;
    top: 0;
    width: 100%;
    height: 100%;
    background: rgba(0,0,0,0.7);
    overflow: auto;
}
.modal-content {
    background: #0f1419;
    margin: 20px auto;
    padding: 30px;
    border: 1px solid #2a3142;
    width: 90%;
    max-width: 900px;
    border-radius: 12px;
    max-height: 80vh;
    overflow-y: auto;
}
.close {
    color: #888;
    float: right;
    font-size: 28px;
    font-weight: bold;
    cursor: pointer;
}
.close:hover { color: #e0e0e0; }

.trades-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    margin-top: 20px;
}
.trades-table th {
    background: #1a1f2e;
    padding: 12px;
    text-align: left;
    font-weight: 600;
    color: #888;
    border-bottom: 1px solid #2a3142;
}
.trades-table td {
    padding: 12px;
    border-bottom: 1px solid #2a3142;
}
.trades-table tr:hover {
    background: #1a1f2e;
}
.trade-win { color: #4ade80; }
.trade-loss { color: #ef4444; }

.summary {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 15px;
    margin-bottom: 30px;
}
.summary-card {
    background: #1a1f2e;
    padding: 15px;
    border-radius: 8px;
    border: 1px solid #2a3142;
}
.summary-label {
    font-size: 12px;
    color: #888;
    text-transform: uppercase;
    margin-bottom: 5px;
}
.summary-value {
    font-size: 20px;
    font-weight: 600;
    font-family: 'Courier New', monospace;
}

.empty { color: #888; text-align: center; padding: 20px; }
</style>
</head>
<body>
<div class="container">
<header>
    <h1>📊 Прогоны</h1>
    <div class="subtitle">Статистика торговли по нарисованным каналам</div>
</header>

<div class="filters">
    <div class="filter-group">
        <label>Пара:</label>
        <select id="filterSym">
            <option value="">Все</option>
'''
    
    symbols = sorted(set(r['sym'] for r in runs))
    for sym in symbols:
        html += f'<option value="{sym}">{sym}</option>\n'
    
    html += '''        </select>
    </div>
    <div class="filter-group">
        <label>ТФ:</label>
        <select id="filterTf">
            <option value="">Все</option>
'''
    
    tfs = sorted(set(r['cfg'].get('tf', '') for r in runs if r['cfg'].get('tf')))
    for tf in tfs:
        html += f'<option value="{tf}">{tf}</option>\n'
    
    html += '''        </select>
    </div>
</div>

<div class="runs-grid" id="runsGrid"></div>

<div id="modal" class="modal">
    <div class="modal-content">
        <span class="close">&times;</span>
        <div id="modalBody"></div>
    </div>
</div>

</div>

<script>
const runs = ''' + json.dumps(runs) + ''';

function formatTime(ms) {
    if (!ms) return '-';
    const d = new Date(ms);
    return d.toLocaleString('ru-RU', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit'});
}

function formatNum(n) {
    return (typeof n === 'number') ? n.toFixed(2) : n;
}

function showRuns(sym = '', tf = '') {
    const grid = document.getElementById('runsGrid');
    grid.innerHTML = '';
    
    let filtered = runs.filter(r => 
        (!sym || r.sym === sym) &&
        (!tf || r.cfg.tf === tf)
    );
    
    if (!filtered.length) {
        grid.innerHTML = '<div class="empty">Нет прогонов</div>';
        return;
    }
    
    filtered.forEach(r => {
        const trades = r.trades || [];
        const stats = calcStats(trades);
        
        const profitClass = stats.profit > 0 ? 'stat-profit' : stats.profit < 0 ? 'stat-loss' : 'stat-neutral';
        
        const card = document.createElement('div');
        card.className = 'run-card';
        card.onclick = () => showModal(r);
        
        card.innerHTML = `
            <div class="run-header">
                <div>
                    <div class="run-name">${r.name}</div>
                    <div class="run-pair">${r.sym} · ${r.cfg.tf}</div>
                </div>
                <div class="run-id">id ${r.id}</div>
            </div>
            <div class="stats-row">
                <span class="stat-label">Сделок:</span>
                <span class="stat-value">${stats.total}</span>
            </div>
            <div class="stats-row">
                <span class="stat-label">Побед:</span>
                <span class="stat-value">${stats.win} (${stats.pct.toFixed(0)}%)</span>
            </div>
            <div class="stats-row">
                <span class="stat-label">Прибыль:</span>
                <span class="stat-value ${profitClass}">${stats.profit > 0 ? '+' : ''}${formatNum(stats.profit)}%</span>
            </div>
            <div class="stats-row">
                <span class="stat-label">Макс просадка:</span>
                <span class="stat-value stat-loss">${formatNum(stats.max_dd)}%</span>
            </div>
        `;
        grid.appendChild(card);
    });
}

function showModal(r) {
    const trades = r.trades || [];
    const stats = calcStats(trades);
    
    let html = `
        <h2>${r.name}</h2>
        <div style="color: #888; margin-bottom: 20px;">
            ${r.sym} · ${r.cfg.tf} · id ${r.id}
        </div>
        
        <div class="summary">
            <div class="summary-card">
                <div class="summary-label">Всего сделок</div>
                <div class="summary-value">${stats.total}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Побед / Убытков</div>
                <div class="summary-value">${stats.win} / ${stats.loss}</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Процент побед</div>
                <div class="summary-value">${stats.pct.toFixed(1)}%</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Общий результат</div>
                <div class="summary-value" style="color: ${stats.profit > 0 ? '#4ade80' : stats.profit < 0 ? '#ef4444' : '#888'}">
                    ${stats.profit > 0 ? '+' : ''}${formatNum(stats.profit)}%
                </div>
            </div>
            <div class="summary-card">
                <div class="summary-label">Макс просадка</div>
                <div class="summary-value" style="color: #ef4444;">${formatNum(stats.max_dd)}%</div>
            </div>
        </div>
    `;
    
    if (trades.length) {
        html += `
            <table class="trades-table">
                <thead><tr>
                    <th>Время входа</th>
                    <th>Тип</th>
                    <th>Вход</th>
                    <th>Выход</th>
                    <th>Результат</th>
                </tr></thead>
                <tbody>
        `;
        trades.forEach(t => {
            const net = t.net || 0;
            const cls = net > 0 ? 'trade-win' : net < 0 ? 'trade-loss' : '';
            html += `<tr>
                <td>${formatTime(t.t_in)}</td>
                <td>${t.side || '?'}</td>
                <td>${formatNum(t.p_in || 0)}</td>
                <td>${formatNum(t.p_out || 0)}</td>
                <td class="${cls}">${net > 0 ? '+' : ''}${formatNum(net)}%</td>
            </tr>`;
        });
        html += '</tbody></table>';
    } else {
        html += '<div class="empty" style="margin-top: 30px;">Сделок нет</div>';
    }
    
    document.getElementById('modalBody').innerHTML = html;
    document.getElementById('modal').style.display = 'block';
}

function calcStats(trades) {
    if (!trades.length) return {total:0, win:0, loss:0, profit:0, max_dd:0, pct:0};
    const profits = trades.map(t => t.net || 0);
    const total = trades.length;
    const win = profits.filter(p => p > 0).length;
    const loss = profits.filter(p => p < 0).length;
    const profit = profits.reduce((a,b) => a+b, 0);
    const pct = (win / total * 100) || 0;
    let cumsum = 0, maxcum = 0, max_dd = 0;
    profits.forEach(p => {
        cumsum += p;
        if (cumsum > maxcum) maxcum = cumsum;
        const dd = maxcum - cumsum;
        if (dd > max_dd) max_dd = dd;
    });
    return {total, win, loss, profit, max_dd, pct};
}

document.getElementById('filterSym').addEventListener('change', (e) => {
    const tf = document.getElementById('filterTf').value;
    showRuns(e.target.value, tf);
});
document.getElementById('filterTf').addEventListener('change', (e) => {
    const sym = document.getElementById('filterSym').value;
    showRuns(sym, e.target.value);
});

document.querySelector('.close').onclick = () => {
    document.getElementById('modal').style.display = 'none';
};
document.getElementById('modal').onclick = (e) => {
    if (e.target === document.getElementById('modal')) {
        document.getElementById('modal').style.display = 'none';
    }
};

showRuns();
</script>
</body>
</html>
'''
    return web.Response(text=html, content_type='text/html; charset=utf-8')

async def main():
    app = web.Application()
    app.router.add_get('/', index)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 18092)
    await site.start()
    print('✓ Runs dashboard на http://localhost:18092')
    await web.run_app(app, host='0.0.0.0', port=18092, print=lambda *a: None)

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())
