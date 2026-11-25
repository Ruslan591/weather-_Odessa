import json, sys
from datetime import datetime, timezone
import weather_tg_ai as ai, weather_tg_channel as ch, weather_tg_issue as I
now = datetime(2026, 11, 25, 19, 0, tzinfo=timezone.utc)   # 21:00 по Киеву вчера
env = ch.load_env(); st = I.collect(env, now); hours = ch.get_ensemble(ch.load_state(), now)
ist = I.load_issue_state()
text, rec, parts = I.build_evening(st, hours, now, ist)
print("TEMPLATE:\n" + re.sub(r"<[^>]+>", "", text.split("<blockquote")[0]) if False else "")
import re
print("FACTS:\n" + re.sub(r"<[^>]+>", "", parts["facts"]))
ai.budget(250)
a = I.ai_text("evening", parts, ist)
print("\nAI:\n" + (I.assemble("evening", a, parts) if a else "(не прошёл проверку)"))
