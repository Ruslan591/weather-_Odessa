"""
Тянет температуру воды с сайта ГМЦ ЧАМ (hmcbas.od.ua), виджет "Погода за
вікном" в правом верхнем блоке главной страницы — это реальные (не
прогнозные) замеры.

Прямой фетч сайта часто отдаёт 421 (антибот/SNI-защита на их стороне) —
в этом случае фоллбэк через публичный reader-прокси r.jina.ai, который
рендерит страницу браузерным движком и обычно проходит там, где голый
HTTP-клиент блокируется.

Виджет отображает 5 значений в фиксированном порядке (см. скриншот):
  22°C (воздух) · 757 (давление, мм рт.ст.) · 4 м/с (ветер) · 63% (влажность)
  · N°C (вода — последнее значение с ним же)
Берём ПОСЛЕДНЕЕ значение вида "N°C" в окне вокруг заголовка виджета.

Известное ограничение: сайт иногда отдаёт 0°C для воды вне утренних часов
(похоже на баг/незаполненное поле на их стороне) — такие значения и любые
физически невозможные для Чёрного моря у Одессы отбрасываем как невалид.
Если текущая попытка не дала валидного значения — сохраняем предыдущее
известное валидное (с пометкой stale), чтобы график/блок не дёргался в 0.

Пишет data/hmcbas_sea_temp_realtime.json:
  {"timestamp": ISO8601Z, "sea_temp": float|None, "source": "direct"|"proxy"|None,
   "stale": bool (опционально)}
"""

import json
import os
import re
import urllib.request
from datetime import datetime, timezone

URL_DIRECT = "http://hmcbas.od.ua/"
URL_PROXY  = "https://r.jina.ai/http://hmcbas.od.ua/"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_FILE = os.path.join(BASE_DIR, "data", "hmcbas_sea_temp_realtime.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def _parse_sea_temp(html):
    idx = html.find("Погода за вікном")
    window = html[idx: idx + 1500] if idx != -1 else html

    temps = re.findall(r'(-?\d{1,2})\s*°\s*C?', window)
    if len(temps) < 2:
        return None

    try:
        sea = float(temps[-1])
    except ValueError:
        return None

    # санити-фильтр: 0°C (известный баг виджета) или вне разумного диапазона
    if sea == 0 or sea < 3 or sea > 32:
        return None
    return sea


def main():
    html, source = None, None
    try:
        html = _fetch(URL_DIRECT)
        source = "direct"
    except Exception as e:
        print(f"  [WARN] прямой фетч hmcbas.od.ua не удался: {e}")
        try:
            html = _fetch(URL_PROXY, timeout=30)
            source = "proxy"
        except Exception as e2:
            print(f"  [WARN] прокси-фетч (r.jina.ai) тоже не удался: {e2}")

    result = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sea_temp":  None,
        "source":    source,
    }

    if html:
        sea = _parse_sea_temp(html)
        result["sea_temp"] = sea
        if sea is None:
            print("  [WARN] не удалось распарсить валидную температуру воды (нет данных / 0°C-брак)")
        else:
            print(f"  ✓ ГМЦ ЧАМ температура воды: {sea}°C (source={source})")

    if result["sea_temp"] is None and os.path.exists(OUT_FILE):
        try:
            with open(OUT_FILE, encoding="utf-8") as f:
                prev = json.load(f)
            if prev.get("sea_temp") is not None:
                print("  [INFO] оставляю предыдущее валидное значение (stale)")
                result["sea_temp"] = prev["sea_temp"]
                result["stale"] = True
        except Exception:
            pass

    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
