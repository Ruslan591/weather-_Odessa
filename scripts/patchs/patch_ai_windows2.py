FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''    result = {
        "generated_at": now_iso,
        "last_checked": now_iso,
        "changed": True,
        "data_hash": current_hash,
        "days_count": len(days),
        "text": text,
    }'''

NEW = '''    # Фиксируем закрытое окно
    now_utc_close = datetime.now(timezone.utc)
    win_closed = _current_window(now_utc_close)
    prev_windows = existing.get("windows_closed", [])
    if win_closed:
        prev_windows.append({
            "window": win_closed,
            "closed_at": now_iso
        })
    # Чистим старые записи (старше 2 суток)
    cutoff = now_utc_close.timestamp() - 2 * 86400
    prev_windows = [
        e for e in prev_windows
        if datetime.fromisoformat(e["closed_at"].replace("Z", "+00:00")).timestamp() >= cutoff
    ]

    result = {
        "generated_at": now_iso,
        "last_checked": now_iso,
        "changed": True,
        "data_hash": current_hash,
        "days_count": len(days),
        "text": text,
        "windows_closed": prev_windows,
    }'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
