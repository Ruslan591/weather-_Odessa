FILE = 'forecast.css'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()
ADD = '''
/* Основные параметры — горизонтальный скролл */
.fc-main-params {
    display: flex;
    gap: 6px;
    overflow-x: auto;
    scrollbar-width: none;
    padding-bottom: 4px;
    margin-bottom: 6px;
}
.fc-main-params::-webkit-scrollbar { display: none; }
.fc-main-params .fc-param-btn { flex-shrink: 0; }

/* Группы-аккордеоны */
.fc-group-accord {
    border-top: 1px solid #222;
    margin-top: 2px;
}
.fc-group-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 4px 6px;
    cursor: pointer;
    -webkit-tap-highlight-color: transparent;
    user-select: none;
}
.fc-group-label {
    font-size: 9px;
    color: #444;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.fc-group-arrow {
    font-size: 11px;
    color: #444;
    transition: transform 0.25s;
}
.fc-group-accord.open .fc-group-arrow {
    transform: rotate(180deg);
}
.fc-group-body {
    display: grid;
    grid-template-rows: 0fr;
    transition: grid-template-rows 0.28s cubic-bezier(0.4,0,0.2,1);
}
.fc-group-accord.open .fc-group-body {
    grid-template-rows: 1fr;
}
.fc-group-body > * { overflow: hidden; }
.fc-group-accord .fc-param-btn { margin-bottom: 4px; }
'''
assert ADD.strip()[:30] not in src, "Already patched"
src = src + ADD
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")