FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''    if current_hash == prev_hash and existing.get("text"):
        # \u0414\u0430\u043d\u043d\u044b\u0435 \u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0438\u0441\u044c \u2014 \u043e\u0431\u043d\u043e\u0432\u043b\u044f\u0435\u043c \u0442\u043e\u043b\u044c\u043a\u043e \u043c\u0435\u0442\u043a\u0443 \u0432\u0440\u0435\u043c\u0435\u043d\u0438
        existing["last_checked"] = now_iso
        existing["changed"] = False
        # \u0424\u0438\u043a\u0441\u0438\u0440\u0443\u0435\u043c \u0437\u0430\u043a\u0440\u044b\u0442\u043e\u0435 \u043e\u043a\u043d\u043e \u0434\u0430\u0436\u0435 \u0435\u0441\u043b\u0438 \u0434\u0430\u043d\u043d\u044b\u0435 \u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0438\u0441\u044c
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
        print(f"  [AI] \u0414\u0430\u043d\u043d\u044b\u0435 \u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0438\u0441\u044c \u2014 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0430 \u043c\u0435\u0442\u043a\u0430 \u0432\u0440\u0435\u043c\u0435\u043d\u0438")
        return'''

NEW = '''    STALE_HOURS = 6

    if current_hash == prev_hash and existing.get("text"):
        try:
            last_gen = datetime.fromisoformat(existing.get("generated_at", "").replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - last_gen).total_seconds() / 3600
        except Exception:
            age_hours = 999

        if age_hours < STALE_HOURS:
            # \u0414\u0430\u043d\u043d\u044b\u0435 \u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0438\u0441\u044c, \u0430\u043d\u0430\u043b\u0438\u0437 \u0441\u0432\u0435\u0436\u0438\u0439 \u2014 \u043e\u043a\u043d\u043e \u043e\u0441\u0442\u0430\u0451\u0442\u0441\u044f \u043e\u0442\u043a\u0440\u044b\u0442\u044b\u043c
            existing["last_checked"] = now_iso
            existing["changed"] = False
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False, indent=2)
            print(f"  [AI] \u0414\u0430\u043d\u043d\u044b\u0435 \u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0438\u0441\u044c ({age_hours:.1f}\u0447 < {STALE_HOURS}\u0447) \u2014 \u043e\u043a\u043d\u043e \u043e\u0442\u043a\u0440\u044b\u0442\u043e, \u043f\u043e\u0432\u0442\u043e\u0440 \u0447\u0435\u0440\u0435\u0437 15 \u043c\u0438\u043d")
            return
        else:
            # \u0414\u0430\u043d\u043d\u044b\u0435 \u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0438\u0441\u044c, \u043d\u043e \u0430\u043d\u0430\u043b\u0438\u0437 \u0443\u0441\u0442\u0430\u0440\u0435\u043b \u2014 \u0440\u0435\u0433\u0435\u043d\u0435\u0440\u0438\u0440\u0443\u0435\u043c \u0441 \u043e\u0431\u043d\u043e\u0432\u043b\u0451\u043d\u043d\u044b\u043c \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u044b\u043c \u043a\u043e\u043d\u0442\u0435\u043a\u0441\u0442\u043e\u043c
            print(f"  [AI] \u0414\u0430\u043d\u043d\u044b\u0435 \u043d\u0435 \u0438\u0437\u043c\u0435\u043d\u0438\u043b\u0438\u0441\u044c, \u043d\u043e \u0430\u043d\u0430\u043b\u0438\u0437 \u0443\u0441\u0442\u0430\u0440\u0435\u043b ({age_hours:.1f}\u0447 >= {STALE_HOURS}\u0447) \u2014 \u0440\u0435\u0433\u0435\u043d\u0435\u0440\u0438\u0440\u0443\u044e")'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
