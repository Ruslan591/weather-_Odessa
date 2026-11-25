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
                "серф", "сёрф", "рыбал", "морж", "ансамбл", "модел", "gemini", "станци")
_deadline = [None]


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


def gemini_json(system, prompt, key, per_try=60):
    """JSON-ответ Gemini по цепочке моделей, не дольше общего бюджета времени."""
    last = None
    for model, thinking in GEMINI_CHAIN:
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
                if e.code in (500, 502, 503, 504, 429) and attempt == 1:
                    time.sleep(5)
                    continue
                break
            except Exception as e:
                last = "%s %s" % (model, str(e)[:100])
                break
    raise RuntimeError(last or "gemini failed")


def nums(t):
    return set(x.replace(".", ",") for x in re.findall(r"\d+(?:[.,]\d+)?", t))


def check(text, facts, max_len):
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
    if re.search(r"<[^>]+>", text):
        probs.append("HTML-теги недопустимы")
    if re.search(r"(одного|одному|двух|двум|трёх|трём|четырёх|четырём|пяти|шести|семи|восьми|девяти|десяти)\s+час|\b(полдень|полночь)\b", low):
        probs.append("время словами вместо цифр")
    return probs


def _ask(system, prompt, field, facts, max_len, log):
    key = gemini_key()
    if not key:
        log("ai: нет ключа Gemini")
        return None
    p = prompt
    for attempt in (1, 2):
        try:
            art, model = gemini_json(system, p, key)
        except Exception as e:
            log("ai: Gemini ошибка: %s" % e)
            return None
        txt = str(art.get(field, "")).strip()
        probs = check(txt, facts, max_len)
        if not probs:
            log("ai: %s ok (%s, %d знаков, осталось %s с)" % (field, model, len(txt), "?" if left() is None else int(left())))
            return txt
        log("ai: %s отклонён (%s): %s" % (field, model, "; ".join(probs)))
        p = prompt + "\nПредыдущий вариант отклонён: %s. Исправь и верни только JSON." % "; ".join(probs)
    return None


BASE = ("Ты редактор Telegram-канала «Погода в Одессе». Голос: умный, тёплый, живой одессит-метеоролог, без канцелярита и штампов, без кликбейта. "
        "ПРАВИЛА ТОЧНОСТИ: используй только факты из сводки, ничего не придумывай, не добавляй чисел и времени, которых нет в сводке (лучше вообще без чисел), "
        "время только цифрами, не упоминай модели, станции, источники и занятия на воде (купание, суда, лодки, пляжи). "
        "Без HTML и без списков. ")


def verdict(digest_text, recent, log):
    """Фраза-вердикт к сводке ГМЦ (до 140 знаков)."""
    facts = re.sub(r"<[^>]+>", "", digest_text)
    sys_ = BASE + ("Напиши ОДНУ фразу-вердикт до 140 знаков: что эта погода значит для горожанина прямо сейчас. "
                   "Допустим один эмодзи в начале. Формат ответа: только JSON {\"verdict\": \"...\"}.")
    pr = "СВОДКА:\n%s\n" % facts
    if recent:
        pr += "\nНедавние вердикты (не повторяй слова и конструкции):\n- " + "\n- ".join(recent[-6:]) + "\n"
    return _ask(sys_, pr + "\nВерни только JSON.", "verdict", facts, 160, log)


def alert_line(alert_text, log):
    """Короткая практическая строка к тревоге: что делать (до 170 знаков)."""
    facts = re.sub(r"<[^>]+>", "", alert_text)
    sys_ = BASE + ("Дан пост-предупреждение. Напиши ОДНУ короткую практическую строку до 170 знаков: что делать горожанину прямо сейчас "
                   "(зонт, осторожность, куда не идти, что убрать с балкона и т.п.) строго по фактам поста. Без запугивания и без повторения поста. "
                   "Формат ответа: только JSON {\"advice\": \"...\"}.")
    return _ask(sys_, "ПОСТ-ПРЕДУПРЕЖДЕНИЕ:\n%s\n\nВерни только JSON." % facts, "advice", facts, 190, log)
