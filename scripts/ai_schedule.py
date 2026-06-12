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

def load():
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            d.setdefault("time_points", [])
            d.setdefault("model_triggers", [])
            d.setdefault("tolerance_min", 20)
            return d
        except Exception as e:
            print(f"Ошибка чтения: {e}")
    return dict(DEFAULT)

def save(d):
    os.makedirs(os.path.dirname(SCHEDULE_FILE), exist_ok=True)
    with open(SCHEDULE_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    print("Сохранено.")

def fmt_days(days):
    if len(days) == 7: return "ежедневно"
    return ",".join(DAY_NAMES[d] for d in sorted(days))

def show(d):
    print("\n── Текущее расписание ──")
    if not d["time_points"]:
        print("  Точки времени: нет")
    else:
        for i, tp in enumerate(d["time_points"]):
            print(f"  [{i}] {tp['hour']:02d}:{tp['minute']:02d} UTC — {fmt_days(tp.get('days', list(range(7))))}")
    print(f"  Допуск: ±{d['tolerance_min']} мин")
    if not d["model_triggers"]:
        print("  Триггеры по моделям: нет")
    else:
        print(f"  Триггеры по моделям: {', '.join(d['model_triggers'])}")
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
    d["time_points"].append({"hour": hh, "minute": mm, "days": days})
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

def toggle_model_trigger(d):
    print("\n  Модели:")
    for i, m in enumerate(ALL_MODELS):
        mark = "✓" if m in d["model_triggers"] else " "
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
            if m in d["model_triggers"]:
                d["model_triggers"].remove(m)
            else:
                d["model_triggers"].append(m)
    save(d)

def set_tolerance(d):
    try:
        v = int(input("  Допуск в минутах: "))
        if v < 1: raise ValueError
        d["tolerance_min"] = v
        save(d)
    except Exception:
        print("  Неверное значение.")

def main():
    d = load()
    while True:
        show(d)
        print("1) Добавить точку времени")
        print("2) Удалить точку времени")
        print("3) Переключить триггеры по моделям")
        print("4) Изменить допуск (±мин)")
        print("0) Выход")
        choice = input("> ").strip()
        if choice == "1": add_time_point(d)
        elif choice == "2": remove_time_point(d)
        elif choice == "3": toggle_model_trigger(d)
        elif choice == "4": set_tolerance(d)
        elif choice == "0": break
        else: print("  ?")

if __name__ == "__main__":
    main()
