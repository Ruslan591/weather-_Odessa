FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''        existing["last_checked"] = now_iso
        existing["changed"] = False
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print(f"  [AI] Данные не изменились — обновлена метка времени")
        return'''

NEW = '''        existing["last_checked"] = now_iso
        existing["changed"] = False
        # Фиксируем закрытое окно даже если данные не изменились
        now_utc_close = datetime.now(timezone.utc)
        win_closed = _current_window(now_utc_close)
        prev_windows = existing.get("windows_closed", [])
        if win_closed:
            prev_windows.append({"window": win_closed, "closed_at": now_iso})
        cutoff = now_utc_close.timestamp() - 2 * 86400
        existing["windows_closed"] = [
            e for e in prev_windows
            if datetime.fromisoformat(e["closed_at"].replace("Z", "+00:00")).timestamp() >= cutoff
        ]
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print(f"  [AI] Данные не изменились — обновлена метка времени")
        return'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
