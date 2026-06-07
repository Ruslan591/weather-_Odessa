FILE = 'scripts/generate_ai_analysis.py'
with open(FILE, 'r', encoding='utf-8') as f: src = f.read()

OLD = '''GOOD_HOURS_UTC = [9, 12, 15, 21]
COOLDOWN_HOURS = 6'''

NEW = '''GOOD_HOURS_UTC = [9, 12, 15, 21]
COOLDOWN_HOURS = 6
STALE_HOURS = 8  # если анализ старше — генерировать вне окна'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)

OLD2 = '''    if not in_good_window():
        now_h = datetime.now(timezone.utc).hour
        print(f"  [AI] Вне окна моделей (сейчас {now_h:02d}UTC), пропускаю")
        return False
    return True'''

NEW2 = '''    # Если анализ устарел или сменились сутки — генерировать вне окна
    try:
        last_gen = existing.get("generated_at", "")
        last_dt = datetime.fromisoformat(last_gen.replace("Z", "+00:00"))
        now_utc = datetime.now(timezone.utc)
        elapsed = (now_utc - last_dt).total_seconds() / 3600
        day_changed = last_dt.date() < now_utc.date()
        if elapsed >= STALE_HOURS or day_changed:
            reason = "смена суток" if day_changed else f"{elapsed:.1f}ч без обновления"
            print(f"  [AI] Анализ устарел ({reason}) — генерирую вне окна")
            return True
    except Exception:
        pass
    if not in_good_window():
        now_h = datetime.now(timezone.utc).hour
        print(f"  [AI] Вне окна моделей (сейчас {now_h:02d}UTC), пропускаю")
        return False
    return True'''

assert OLD2 in src, "OLD2 not found"
src = src.replace(OLD2, NEW2, 1)

with open(FILE, 'w', encoding='utf-8') as f: f.write(src)
print("OK")
