# -*- coding: utf-8 -*-
"""Общий слой Gemini для канала: вердикт к сводке ГМЦ и практическая строка к тревогам.

Модуль самодостаточный (не импортирует остальные weather_tg_*), чтобы его могли подключать и лента, и выпуски.
Ключ GEMINI_API_KEY берётся из .env основного пайплайна. Общий бюджет времени на запуск задаётся budget(сек),
по умолчанию 240 с: по решению пользователя можно ждать до ~5 минут, при неудаче публикуется шаблон.
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

PIPELINE_ENV = "/opt/weather-pipeline/repo/.env"
GEMINI_CHAIN = [("gemini-3.7-flash", {"thinkingLevel": "low"}), ("gemini-3.5-flash", {"thinkingLevel": "low"}),
                ("gemini-3.8-flash", {"thinkingLevel": "low"}), ("gemini-2.5-flash", None)]
# запрещённые слова: занятия на воде (война), технические термины
BANNED_WORDS = ("купан", "купат", "плавани", "плавать", "яхт", "лодк", "катер", "судов", "судн", "корабл", "пляж", "парус",
                "серф", "сёрф", "рыбал", "морж", "ансамбл", "модел", "gemini", "станци",
                # обращения к читателям и пожелания (решение пользователя: без этого)
                "одессит", "дорогие", "дорогой", "дорогих", "друзья", "друзей", "уважаем", "подписчик", "читател", "наслаждайтесь",
                "спокойной ночи", "хорошего дня", "доброе утро", "добрый вечер")
_deadline = [None]
CALLER = None   # если задан: функция (system, prompt) -> (dict, имя_модели) вместо Gemini (для Claude и сравнения моделей)
USAGE = []      # (модель, токены входа, токены выхода) для расчёта стоимости


def budget(sec):
    _deadline[0] = time.time() + sec


def left():
    return None if _deadline[0] is None else _deadline[0] - time.time()


def gemini_key():
    try:
        with open(PIPELINE_ENV, encoding="utf-8") as f:
            for line in f:
                if line.startswith("GEMINI_API_KEY="):
                    return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return os.environ.get("GEMINI_API_KEY")


def gemini_json(system, prompt, key, per_try=60, chain=None):
    """JSON-ответ Gemini по цепочке моделей, не дольше общего бюджета времени."""
    last = None
    for model, thinking in (chain or GEMINI_CHAIN):
        for attempt in (1, 2):
            rem = left()
            if rem is not None and rem < 10:
                raise RuntimeError("бюджет времени исчерпан (%s)" % (last or "нет ответа"))
            body = {"contents": [{"parts": [{"text": prompt}]}], "systemInstruction": {"parts": [{"text": system}]},
                    "generationConfig": {"responseMimeType": "application/json"}}
            if thinking:
                body["generationConfig"]["thinkingConfig"] = thinking
            url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s" % (model, key)
            try:
                req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=min(per_try, rem) if rem else per_try) as r:
                    resp = json.loads(r.read().decode())
                parts = resp["candidates"][0]["content"]["parts"]
                return json.loads("".join(p.get("text", "") for p in parts if not p.get("thought"))), model
            except urllib.error.HTTPError as e:
                last = "%s HTTP %s" % (model, e.code)
                try:
                    ebody = e.read().decode("utf-8", "ignore").lower()
                except Exception:
                    ebody = ""
                if e.code == 429 and ("quota" in ebody or "billing" in ebody):
                    last += " (квота ключа исчерпана или нет доступа к модели)"
                    break   # ждать бесполезно, следующая модель цепочки
                if e.code in (500, 502, 503, 504, 429) and attempt == 1:
                    time.sleep(5)
                    continue
                break
            except Exception as e:
                last = "%s %s" % (model, str(e)[:100])
                break
    raise RuntimeError(last or "gemini failed")


def anthropic_key():
    try:
        with open(PIPELINE_ENV, encoding="utf-8") as f:
            for line in f:
                if line.startswith("ANTHROPIC_API_KEY="):
                    return line.strip().split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


def claude_json(model, max_tokens=1500):
    """Фабрика CALLER для Claude: возвращает функцию (system, prompt) -> (dict, model)."""
    def call(system, prompt):
        key = anthropic_key()
        if not key:
            raise RuntimeError("нет ANTHROPIC_API_KEY")
        rem = left()
        body = {"model": model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), method="POST",
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=min(90, rem) if rem else 90) as r:
                resp = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError("%s HTTP %s %s" % (model, e.code, e.read().decode("utf-8", "ignore")[:160]))
        txt = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        u = resp.get("usage", {})
        USAGE.append((model, u.get("input_tokens", 0), u.get("output_tokens", 0)))
        a, b = txt.find("{"), txt.rfind("}")
        return json.loads(txt[a:b + 1]), model
    return call


def nums(t):
    return set(x.replace(".", ",") for x in re.findall(r"\d+(?:[.,]\d+)?", t))


def sun_times(day):
    """Восход и закат в Одессе (приближение NOAA) для даты day (aware datetime Киев). Возвращает (восход, закат) aware."""
    import math
    from datetime import datetime, timedelta, timezone
    lat, lon = 46.48, 30.72
    n = day.timetuple().tm_yday
    g = 2 * math.pi / 365 * (n - 1)
    eq = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g) - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    dec = 0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
    la = math.radians(lat)
    ha = math.degrees(math.acos(math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(dec)) - math.tan(la) * math.tan(dec)))
    base = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    rise = base + timedelta(minutes=720 - 4 * (lon + ha) - eq)
    sset = base + timedelta(minutes=720 - 4 * (lon - ha) - eq)
    return rise.astimezone(day.tzinfo), sset.astimezone(day.tzinfo)


def sun_context(now_local):
    """Фраза для промпта: что за окном сейчас. Возвращает (текст, тёмное_время)."""
    from datetime import timedelta
    rise, sset = sun_times(now_local)
    if now_local < rise - timedelta(minutes=40) or now_local > sset + timedelta(minutes=40):
        phase, dark = "на улице ночь", True
    elif now_local < rise + timedelta(minutes=30):
        phase, dark = "рассвет", False
    elif now_local > sset - timedelta(minutes=40):
        phase, dark = "сумерки, вечер", False
    else:
        phase, dark = "светлое время суток", False
    return "Сейчас %s местного времени: %s (сегодня восход %s, закат %s)." % (now_local.strftime("%H:%M"), phase, rise.strftime("%H:%M"), sset.strftime("%H:%M")), dark


DARK_WORDS = ("солн", "светл", "светает", "светле", "рассвет", "ярк")


def check(text, facts, max_len, dark=False):
    """Проблемы короткого текста: новые числа, запретные слова, теги, длина, время словами."""
    probs = []
    if not text:
        return ["пусто"]
    if len(text) > max_len:
        probs.append("длиннее %d знаков" % max_len)
    bad = sorted(nums(text) - nums(facts) - {"0", "00"})
    if bad:
        probs.append("числа, которых нет в сводке: " + ", ".join(bad))
    low = text.lower()
    for w in BANNED_WORDS:
        if w in low:
            probs.append("запретное слово: " + w)
    if dark:
        for w in DARK_WORDS:
            if w in low:
                probs.append("сейчас тёмное время суток, нельзя писать про «%s»" % w)
    if re.search(r"<[^>]+>", text):
        probs.append("HTML-теги недопустимы")
    if re.search(r"(одного|одному|двух|двум|трёх|трём|четырёх|четырём|пяти|шести|семи|восьми|девяти|десяти)\s+час|\b(полдень|полночь)\b", low):
        probs.append("время словами вместо цифр")
    return probs


def _ask(system, prompt, field, facts, max_len, log, dark=False):
    key = gemini_key()
    if not key and not CALLER:
        log("ai: нет ключа Gemini")
        return None
    p = prompt
    for attempt in (1, 2):
        try:
            art, model = CALLER(system, p) if CALLER else gemini_json(system, p, key)
        except Exception as e:
            log("ai: Gemini ошибка: %s" % e)
            return None
        txt = str(art.get(field, "")).strip()
        probs = check(txt, facts, max_len, dark)
        if not probs:
            log("ai: %s ok (%s, %d знаков, осталось %s с)" % (field, model, len(txt), "?" if left() is None else int(left())))
            return txt
        log("ai: %s отклонён (%s): %s" % (field, model, "; ".join(probs)))
        p = prompt + "\nПредыдущий вариант отклонён: %s. Исправь и верни только JSON." % "; ".join(probs)
    return None


BASE = ("Ты редактор Telegram-канала «Погода в Одессе». Голос: умный, тёплый, живой одессит-метеоролог, без канцелярита и штампов, без кликбейта. "
        "ПРАВИЛА ТОЧНОСТИ: используй только факты из сводки, ничего не придумывай, не добавляй чисел и времени, которых нет в сводке (лучше вообще без чисел), "
        "время только цифрами, не упоминай модели, станции, источники и занятия на воде (купание, суда, лодки, пляжи). "
        "Слова «мороз», «морозно», «заморозки» только если температура в сводке ниже 0°; при температуре выше 0° говори «холодно» или «прохладно». "
        "Тон нейтрально-журналистский, спокойный и точный; без обращений к читателям («одесситы», «друзья», «дорогие»), без пожеланий («спокойной ночи», «наслаждайтесь», «хорошего дня»), без восклицаний и сюсюканья. "
        "Без HTML и без списков. ")


def verdict(digest_text, recent, log, now_local=None):
    """Фраза-вердикт к сводке ГМЦ (до 140 знаков)."""
    facts = re.sub(r"<[^>]+>", "", digest_text)
    sun, dark = sun_context(now_local) if now_local else ("", False)
    sys_ = BASE + ("Напиши ОДНУ фразу-вердикт до 140 знаков: что эта погода значит для горожанина прямо сейчас. "
                   "Допустим один эмодзи в начале. Формат ответа: только JSON {\"verdict\": \"...\"}.")
    pr = "СВОДКА:\n%s\n" % facts
    if sun:
        pr += "\n%s Учитывай время суток: ночью не пиши про солнце и свет, небо описывай только по облачности из сводки (облачность убывает: «проясняется», растёт: «затягивается»).\n" % sun
    if recent:
        pr += "\nНедавние вердикты (не повторяй слова и конструкции):\n- " + "\n- ".join(recent[-6:]) + "\n"
    return _ask(sys_, pr + "\nВерни только JSON.", "verdict", facts, 160, log, dark)


def alert_line(alert_text, log, recent=None):
    """Короткая практическая строка к тревоге: что делать (до 170 знаков).
    Для порывов ниже 10 м/с строки нет (не пугаем); про деревья и балконы можно только при порывах от 10 м/с."""
    facts = re.sub(r"<[^>]+>", "", alert_text)
    m = re.search(r"Порывы ветра до ([\d]+(?:[.,]\d+)?)", facts)
    if m and float(m.group(1).replace(",", ".")) < 10.0:
        return None
    sys_ = BASE + ("Дан пост-предупреждение. Напиши ОДНУ короткую практическую строку до 170 знаков: что делать горожанину прямо сейчас "
                   "(зонт, осторожность, куда не идти, что убрать с балкона и т.п.) строго по фактам поста. Без запугивания и без повторения поста. "
                   "Формат ответа: только JSON {\"advice\": \"...\"}.")
    pr = "ПОСТ-ПРЕДУПРЕЖДЕНИЕ:\n%s\n" % facts
    if recent:
        pr += "\nНедавние советы (не повторяй их и не повторяй одни и те же предметы советов):\n- " + "\n- ".join(recent[-6:]) + "\n"
    return _ask(sys_, pr + "\nВерни только JSON.", "advice", facts, 190, log)
