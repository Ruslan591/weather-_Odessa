# -*- coding: utf-8 -*-
"""Слепое сравнение моделей на одинаковых фактах: утренний выпуск, вердикт ГМЦ, строка к тревоге.
Запуск: python3 ab_models.py > /tmp/ab_out.txt   (в фоне; ответы моделей тестируются теми же промптами и проверками, что в проде)
Соответствие букв моделям: /opt/weather-tg/ab_mapping.json (раскрывать только после выбора пользователя)."""
import json
import random
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import weather_tg_ai as ai
import weather_tg_channel as ch
import weather_tg_issue as I

PRICE = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}
BACKENDS = [("Gemini (как сейчас)", None), ("Haiku 5.5", ai.claude_json("claude-haiku-5-5")),
            ("Sonnet 5.5", ai.claude_json("claude-sonnet-5-5")), ("Opus 5.5", ai.claude_json("claude-opus-5-5"))]
DIGEST = ("📋 <b>Сводка по Одессе, 10:00</b>\n🏛 <b>Официальная сводка ГМЦ</b> (Одесса), наблюдения 09:00\n🌡 3,4 °C · влажность 78% · давление 1021,0 гПа (за 3 ч выросло на 0,6 гПа)\n"
          "💨 ветер З 5 м/с · видимость 50 км\n☁ облачность 4/8, переменная облачность\n🌧 в момент наблюдения явлений нет.")
ALERT = "💨 <b>Порывы ветра до 12,4 м/с</b>\nпос. Котовского 12,4; Аркадия 10,8 (м/с).\nВетер З, 7 м/с.\n🕐 12:20"


def main():
    now = datetime.now(timezone.utc)
    env = ch.load_env()
    st = I.collect(env, now)
    hours = ch.get_ensemble(ch.load_state(), now)
    text, rec, parts = I.build_morning(st, hours, now)
    ist = {"headlines": []}
    ln = now.astimezone(ch.KYIV)
    res = {"issue": [], "verdict": [], "alert": []}
    for name, caller in BACKENDS:
        ai.CALLER = caller
        ai.budget(280)
        try:
            a = I.ai_text("morning", parts, ist)
            res["issue"].append((name, I.assemble("morning", a, parts) if a else None))
        except Exception as e:
            res["issue"].append((name, None))
        try:
            res["verdict"].append((name, ai.verdict(DIGEST, [], ch.log, ln)))
        except Exception:
            res["verdict"].append((name, None))
        try:
            res["alert"].append((name, ai.alert_line(ALERT, ch.log, [])))
        except Exception:
            res["alert"].append((name, None))
    mapping = {}
    rng = random.Random(now.timestamp())
    for task, items in res.items():
        order = list(range(len(items)))
        rng.shuffle(order)
        mapping[task] = {}
        print("\n########## %s ##########" % task.upper())
        for letter, idx in zip("АБВГ", order):
            name, val = items[idx]
            mapping[task][letter] = name
            print("\n--- %s ---\n%s" % (letter, val if val else "(модель не вернула текст, прошедший проверку)"))
    json.dump(mapping, open("/opt/weather-tg/ab_mapping.json", "w", encoding="utf-8"), ensure_ascii=False)
    cost = 0.0
    for m, i, o in ai.USAGE:
        pi, po = PRICE[m]
        cost += i * pi / 1e6 + o * po / 1e6
    print("\n[токены Claude: %d вх, %d исх; стоимость теста $%.4f]" % (sum(x[1] for x in ai.USAGE), sum(x[2] for x in ai.USAGE), cost))


if __name__ == "__main__":
    main()
