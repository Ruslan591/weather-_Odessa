#!/usr/bin/env python3
"""
ai_schedule.py — CLI для настройки расписания генерации AI-анализа.
Редактирует data/ai_schedule.json.
"""

import json, os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEDULE_FILE = os.path.join(BASE_DIR, "data", "ai_schedule.json")

ALL_MODELS = ["ECMWF IFS", "ICON EU", "UKMO", "Arpège", "GFS", "GRAPES"]
DAY_NAMES = ["Вс","Пн","Вт","Ср","Чт","Пт","Сб"]

DEFAULT = {
    "time_points": [],
    "model_triggers": [],
    "tolerance_min": 20
}

# Модели, которые можно выбрать в меню (можно ввести и своё имя). Порядок Gemini = порядок приоритета, остальные запасные.
GEMINI_KNOWN = ["gemini-4-hydrogen", "gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash"]
CLAUDE_KNOWN = ["claude-sonnet-4-5", "claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
GEMINI_DEFAULT = ["gemini-3.8-flash", "gemini-3.5-flash", "gemini-2.5-flash"]   # как в generate_ai_analysis.py без выбора
CLAUDE_DEFAULT = "claude-sonnet-4-5"
DIRTY = False   # были изменения, не отправленные на GitHub

def load():
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            d.setdefault("time_points", [])
            d.setdefault("model_triggers", [])
            d.setdefault("tolerance_min", 20)
            d.setdefault("models", {})
            return d
        except Exception as e:
            print(f"Ошибка чтения: {e}")
    return dict(DEFAULT)

def save(d):
    global DIRTY
    os.makedirs(os.path.dirname(SCHEDULE_FILE), exist_ok=True)
    if not d.get("models"):
        d.pop("models", None)   # пустой выбор моделей не пишем: работают значения по умолчанию
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    d.setdefault("models", {})
    DIRTY = True
    print("Сохранено локально. Чтобы изменения заработали на сервере, отправьте их на GitHub (пункт 7 или при выходе).")

PROVIDERS = ["claude", "gemini"]

def fmt_days(days):
    if len(days) == 7: return "ежедневно"
    return ",".join(DAY_NAMES[d] for d in sorted(days))

def fmt_provider(p):
    if p is None: return "все"
    if isinstance(p, list): return "+".join(p)
    return p

def show(d):
    print("\n── Текущее расписание ──")
    if not d["time_points"]:
        print("  Точки времени: нет")
    else:
        for i, tp in enumerate(d["time_points"]):
            prov = fmt_provider(tp.get("provider"))
            print(f"  [{i}] {tp['hour']:02d}:{tp['minute']:02d} UTC — {fmt_days(tp.get('days', list(range(7))))} [{prov}]")
    print(f"  Допуск: ±{d['tolerance_min']} мин")
    m = d.get("models") or {}
    print("  Модель Gemini: " + (" → ".join(m["gemini"]) if m.get("gemini") else "по умолчанию (" + " → ".join(GEMINI_DEFAULT) + ")"))
    print("  Модель Claude: " + (m.get("claude") or "по умолчанию (" + CLAUDE_DEFAULT + ")"))
    if not d["model_triggers"]:
        print("  Триггеры по моделям: нет")
    else:
        for t in d["model_triggers"]:
            if isinstance(t, str):
                print(f"  - {t} [все]")
            else:
                print(f"  - {t.get('model')} [{fmt_provider(t.get('provider'))}]")
    print()

def input_days():
    print("  Дни недели (0=Вс..6=Сб), через запятую, Enter=ежедневно:")
    s = input("  > ").strip()
    if not s:
        return list(range(7))
    try:
        return sorted(set(int(x) for x in s.split(",") if x.strip().isdigit() and 0 <= int(x) <= 6))
    except Exception:
        return list(range(7))

def input_provider():
    print("  Провайдер: 1=claude, 2=gemini, 3=оба (Enter=оба):")
    s = input("  > ").strip()
    if s == "1": return "claude"
    if s == "2": return "gemini"
    return None  # оба — поле не добавляем

def add_time_point(d):
    try:
        t = input("  Время HH:MM (UTC): ").strip()
        hh, mm = t.split(":")
        hh, mm = int(hh), int(mm)
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError
    except Exception:
        print("  Неверный формат.")
        return
    days = input_days()
    provider = input_provider()
    tp = {"hour": hh, "minute": mm, "days": days}
    if provider is not None:
        tp["provider"] = provider
    d["time_points"].append(tp)
    save(d)

def remove_time_point(d):
    show(d)
    if not d["time_points"]:
        return
    try:
        idx = int(input("  Номер точки для удаления: "))
        d["time_points"].pop(idx)
        save(d)
    except Exception:
        print("  Неверный номер.")

def _trigger_models(d):
    """Возвращает список имён моделей в триггерах (строки и dict)."""
    return [t if isinstance(t, str) else t.get("model") for t in d["model_triggers"]]

def toggle_model_trigger(d):
    print("\n  Модели:")
    active = _trigger_models(d)
    for i, m in enumerate(ALL_MODELS):
        mark = "✓" if m in active else " "
        print(f"  [{mark}] {i}: {m}")
    print("  Введите номера для переключения, через запятую (Enter=отмена):")
    s = input("  > ").strip()
    if not s:
        return
    try:
        idxs = [int(x) for x in s.split(",") if x.strip().isdigit()]
    except Exception:
        return
    for i in idxs:
        if 0 <= i < len(ALL_MODELS):
            m = ALL_MODELS[i]
            existing_names = _trigger_models(d)
            if m in existing_names:
                d["model_triggers"] = [t for t in d["model_triggers"]
                                        if (t if isinstance(t, str) else t.get("model")) != m]
            else:
                provider = input_provider()
                if provider is None:
                    d["model_triggers"].append(m)
                else:
                    d["model_triggers"].append({"model": m, "provider": provider})
    save(d)

def set_tolerance(d):
    try:
        v = int(input("  Допуск в минутах: "))
        if v < 1: raise ValueError
        d["tolerance_min"] = v
        save(d)
    except Exception:
        print("  Неверное значение.")

def _pick_model(known, title):
    """Выбор из списка по номеру или ввод своего имени. Возвращает имя или None."""
    for i, m in enumerate(known):
        print(f"  {i}: {m}")
    print(f"  m: ввести своё имя модели")
    s = input(f"  {title} > ").strip()
    if s.lower() == "m":
        name = input("  Имя модели: ").strip()
        return name or None
    if s.isdigit() and 0 <= int(s) < len(known):
        return known[int(s)]
    return None

def choose_models(d):
    models = d.setdefault("models", {})
    print("\n  Выбор модели ИИ для генерации анализа:")
    print("  1) Gemini: порядок приоритета (первая основная, остальные запасные при ошибках 429/5xx)")
    print("  2) Claude: одна модель")
    print("  3) Сбросить обе на значения по умолчанию")
    s = input("  > ").strip()
    if s == "1":
        for i, m in enumerate(GEMINI_KNOWN):
            print(f"  {i}: {m}")
        print("  Введите номера моделей по порядку приоритета через запятую (например 1,2); можно одну. Enter=отмена:")
        raw = input("  > ").strip()
        if not raw:
            return
        names = []
        for x in raw.split(","):
            x = x.strip()
            if x.isdigit() and 0 <= int(x) < len(GEMINI_KNOWN) and GEMINI_KNOWN[int(x)] not in names:
                names.append(GEMINI_KNOWN[int(x)])
        if names:
            models["gemini"] = names
            save(d)
        else:
            print("  Ничего не выбрано.")
    elif s == "2":
        name = _pick_model(CLAUDE_KNOWN, "Номер")
        if name:
            models["claude"] = name
            save(d)
        else:
            print("  Ничего не выбрано.")
    elif s == "3":
        d["models"] = {}
        save(d)

def push_to_github():
    """Отправляет data/ai_schedule.json на GitHub через push_file_via_api.py; True при успехе."""
    import subprocess, sys
    r = subprocess.run([sys.executable, os.path.join(BASE_DIR, "scripts", "push_file_via_api.py"),
                        "data/ai_schedule.json", "ai_schedule: update"], cwd=BASE_DIR)
    return r.returncode == 0

def generate_now():
    import subprocess, sys
    print("  Провайдер: 1=claude, 2=gemini, 3=оба (Enter=оба):")
    s = input("  > ").strip()
    scripts = os.path.join(BASE_DIR, "scripts")
    py = sys.executable
    if s == "2":
        subprocess.run([py, os.path.join(scripts, "generate_ai_analysis.py"), "--force-gemini"])
        subprocess.run([py, os.path.join(scripts, "make_blocks_gemini.py")])
    elif s == "3":
        subprocess.run([py, os.path.join(scripts, "generate_ai_analysis.py"), "--force", "--force-gemini"])
        subprocess.run([py, os.path.join(scripts, "make_blocks.py"), "--force"])
        subprocess.run([py, os.path.join(scripts, "make_blocks_gemini.py")])
    else:
        subprocess.run([py, os.path.join(scripts, "generate_ai_analysis.py"), "--force"])
        subprocess.run([py, os.path.join(scripts, "make_blocks.py"), "--force"])

def main():
    d = load()
    while True:
        show(d)
        print("1) Добавить точку времени")
        print("2) Удалить точку времени")
        print("3) Переключить триггеры по моделям")
        print("4) Изменить допуск (±мин)")
        print("5) Генерировать немедленно")
        print("6) Выбрать модель ИИ")
        print("7) Отправить расписание на GitHub")
        print("0) Выход")
        choice = input("> ").strip()
        if choice == "1": add_time_point(d)
        elif choice == "2": remove_time_point(d)
        elif choice == "3": toggle_model_trigger(d)
        elif choice == "4": set_tolerance(d)
        elif choice == "5": generate_now()
        elif choice == "6": choose_models(d)
        elif choice == "7":
            global DIRTY
            if push_to_github():
                DIRTY = False
            else:
                print("  ✗ Не отправлено: проверьте ошибку выше (часто токен GH_DISPATCH_TOKEN в .env истёк).")
        elif choice == "0":
            if DIRTY:
                ans = input("  Есть неотправленные изменения. Отправить на GitHub? [Y/n] ").strip().lower()
                if ans in ("", "y", "д", "да"):
                    if not push_to_github():
                        again = input("  ✗ Не отправлено. Выйти всё равно? [y/N] ").strip().lower()
                        if again not in ("y", "д", "да"):
                            continue
            break
        else: print("  ?")

if __name__ == "__main__":
    main()
