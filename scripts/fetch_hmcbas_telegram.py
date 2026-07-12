"""
Тянет реальные (не прогнозные) суточные замеры ГМЦ ЧАМ из Telegram-канала
t.me/HMC_Odesa — блок "Поточна погода в Одесі на HH:MM", публикуется ~раз
в сутки, обычно между 07:00 и 10:00. Берём ТОЛЬКО температуру морської
води — воздух/давление/влажность уже покрыты SYNOP-станцией 33837
(data/synop_YYYY.txt), дублировать не нужно.

Источник — публичный веб-превью канала t.me/s/HMC_Odesa (без авторизации,
отдаёт последние ~20 сообщений). Глубокий бэкфилл через пагинацию
(?before=N) сюда сознательно не включён: каждый цикл пайплайна добавляет
максимум один новый пост в историю, этого достаточно для постепенного
накопления. Если нужно быстро набрать долгую историю задним числом —
это отдельная разовая задача с пагинацией по ?before=.

Копит историю в data/hmcbas_telegram_sea_temp.json:
  [{"timestamp": ISO8601 (как есть из <time datetime=...>), "sea_temp": float}, ...]
Дедупликация по timestamp (у него секундная точность, посты раз в сутки —
коллизий не бывает).

Санити-фильтр: 0°C и значения вне [3, 32]°C отбрасываются как брак парсинга.
"""

import json
import os
import re
import urllib.request

URL = "https://t.me/s/HMC_Odesa"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "hmcbas_telegram_sea_temp.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

DATE_RE = re.compile(r'<time datetime="([^"]+)"')
SEA_RE  = re.compile(r'Температура морсь?кої? води\s*(-?\d+)\s*°')


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def _parse_posts(html):
    results = []
    for m in re.finditer(r'Поточна погода в Одесі', html):
        idx = m.start()
        window = html[idx: idx + 2000]

        date_m = DATE_RE.search(window)
        sea_m  = SEA_RE.search(window)
        if not date_m or not sea_m:
            continue

        try:
            sea_temp = float(sea_m.group(1))
        except ValueError:
            continue
        if sea_temp == 0 or sea_temp < 3 or sea_temp > 32:
            continue

        results.append({
            "timestamp": date_m.group(1),
            "sea_temp":  sea_temp,
        })
    return results


def main():
    try:
        html = _fetch(URL)
    except Exception as e:
        print(f"  [WARN] t.me/s/HMC_Odesa фетч не удался: {e}")
        return

    new_posts = _parse_posts(html)
    if not new_posts:
        print("  [INFO] на текущей странице канала не найдено постов 'Поточна погода'")
        return

    history = []
    if os.path.exists(OUT_FILE):
        try:
            with open(OUT_FILE, encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            history = []

    known_ts = {h.get("timestamp") for h in history}
    added = 0
    for p in new_posts:
        if p["timestamp"] in known_ts:
            continue
        history.append(p)
        known_ts.add(p["timestamp"])
        added += 1

    history.sort(key=lambda h: h.get("timestamp", ""))

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    print(f"  ✓ ГМЦ ЧАМ Telegram: {added} новых записей, всего в истории {len(history)}")


if __name__ == "__main__":
    main()
