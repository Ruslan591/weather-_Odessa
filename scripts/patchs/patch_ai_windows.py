FILE = 'scripts/generate_ai_analysis.py'
with open(FILE,'r',encoding='utf-8') as f: src=f.read()

OLD = '''GOOD_HOURS_UTC = [3, 9, 12, 15, 21]
COOLDOWN_HOURS = 6
STALE_HOURS = 8  # если анализ старше — генерировать вне окна

def in_good_window(now_utc=None):
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    for h in GOOD_HOURS_UTC:
        target = now_utc.replace(hour=h, minute=0, second=0, microsecond=0)
        if abs((now_utc - target).total_seconds()) <= 45 * 60:
            return True
    return False

def cooldown_ok(existing, force=False):
    if force:
        return True
    last_gen = existing.get("generated_at", "")
    if not last_gen:
        return True
    try:
        last_dt = datetime.fromisoformat(last_gen.replace("Z", "+00:00"))
        elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
        if elapsed < COOLDOWN_HOURS:
            print(f"  [AI] Cooldown: последний анализ {elapsed:.1f}ч назад, пропускаю")
            return False
    except Exception:
        pass
    # Если анализ устарел или сменились сутки — генерировать вне окна
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

NEW = '''# 5 обязательных окон (UTC час, минута) — привязаны к прогонам ECMWF
# 03:00, 09:00, 11:30, 16:45, 23:30 UTC
WINDOWS_UTC = [(3,0), (9,0), (11,30), (16,45), (23,30)]
WINDOW_TOLERANCE_MIN = 45  # окно считается активным ±45 мин от целевого времени

def _windows_closed_today(existing, now_utc):
    """Возвращает set строк вида 'HH:MM' для окон закрытых сегодня."""
    closed = set()
    for entry in existing.get("windows_closed", []):
        try:
            dt = datetime.fromisoformat(entry["closed_at"].replace("Z", "+00:00"))
            if dt.date() == now_utc.date():
                closed.add(entry["window"])
        except Exception:
            pass
    return closed

def _current_window(now_utc):
    """Возвращает строку 'HH:MM' если сейчас активно окно, иначе None."""
    for h, m in WINDOWS_UTC:
        target = now_utc.replace(hour=h, minute=m, second=0, microsecond=0)
        if abs((now_utc - target).total_seconds()) <= WINDOW_TOLERANCE_MIN * 60:
            return f"{h:02d}:{m:02d}"
    return None

def cooldown_ok(existing, force=False):
    if force:
        return True
    now_utc = datetime.now(timezone.utc)
    win = _current_window(now_utc)
    if win is None:
        now_h = now_utc.hour
        now_m = now_utc.minute
        print(f"  [AI] Вне окна моделей (сейчас {now_h:02d}:{now_m:02d} UTC), пропускаю")
        return False
    closed = _windows_closed_today(existing, now_utc)
    if win in closed:
        print(f"  [AI] Окно {win} UTC уже закрыто сегодня, пропускаю")
        return False
    print(f"  [AI] Активно окно {win} UTC — генерирую")
    return True'''

assert OLD in src, "OLD not found"
src = src.replace(OLD, NEW, 1)
with open(FILE,'w',encoding='utf-8') as f: f.write(src)
print("OK")
