# -*- coding: utf-8 -*-
"""tg_sample.py: отправка в Telegram примера графика по последнему ордеру счёта «Регрессия» (из истории, чтобы показать вид сообщения)."""
import json, sys
sys.path.insert(0, "/opt/tg-notify")
import tg_notify as T
orders = json.load(open("/opt/trading-bot/positions_regr/orders.json"))
for o in reversed(orders):
    if not o.get("chan"): continue
    try:
        kl = json.load(open("/tmp/klcache/%s_5m_1000.json" % o["sym"]))
    except Exception:
        continue
    if kl[0][0] <= o["placed_t"] - 60 * 300000 and o["expire_t"] <= kl[-1][0]: break
else:
    raise SystemExit("нет подходящего ордера")
png = T.render_order(o, kl)
cap = "ПРИМЕР (старый ордер из истории, не действующий)\n" + T.caption_order(o) + "\n\nКнопки ниже пока демонстрационные: нажатия начнут работать на следующем шаге."
btn = [[{"text": "✅ Поставить", "callback_data": "demo_ok"}, {"text": "❌ Отклонить", "callback_data": "demo_no"}], [{"text": "Стоп в БУ", "callback_data": "demo_be"}, {"text": "Закрыть по рынку", "callback_data": "demo_close"}]]
r = T.send_photo(png, cap, btn)
print("sent:", r.get("ok"), o["sym"], o["side"], o["status"])
