import json, sys, time
import weather_tg_ai as ai, weather_tg_channel as ch, weather_tg_issue as I
from datetime import datetime, timezone
now = datetime.now(timezone.utc)
def caller(system, prompt):
    return ai.gemini_json(system, prompt, ai.gemini_key(), chain=[("gemini-4-hydrogen", None)])
ai.CALLER = caller
ai.budget(250)
env = ch.load_env(); st = I.collect(env, now); hours = ch.get_ensemble(ch.load_state(), now)
text, rec, parts = I.build_morning(st, hours, now)
t0 = time.time(); a = I.ai_text("morning", parts, {"headlines": []})
print("ISSUE (%.0f с)\n%s" % (time.time() - t0, I.assemble("morning", a, parts).split("<blockquote")[0] if a else "(не прошёл проверку)"))
DIGEST = "📋 Сводка по Одессе, 10:00\n🏛 Официальная сводка ГМЦ (Одесса), наблюдения 09:00\n🌡 3,4 °C · влажность 78% · давление 1021,0 гПа (за 3 ч выросло на 0,6 гПа)\n💨 ветер З 5 м/с · видимость 50 км\n☁ облачность 4/8, переменная облачность\n🌧 в момент наблюдения явлений нет."
t0 = time.time(); print("\nVERDICT (%.0f с): %s" % (time.time() - t0, ai.verdict(DIGEST, [], ch.log, now.astimezone(ch.KYIV))))
for g in ("9,1", "12,4"):
    al = "💨 Порывы ветра до %s м/с\nпос. Котовского %s; Аркадия 8,0 (м/с).\nВетер З, 6 м/с.\n🕐 12:20" % (g, g)
    t0 = time.time(); print("\nALERT %s (%.0f с): %s" % (g, time.time() - t0, ai.alert_line(al, ch.log, [])))
