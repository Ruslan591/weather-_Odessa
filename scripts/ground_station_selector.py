"""
ground_station_selector.py — выбор наземной станции "впереди" и "позади"
трека фронта вдоль его траектории движения (см. docs/topics/eumetsat.md,
план шага 5 "Наземные наблюдения вдоль траектории фронта", 2026-08-14,
пункт 2).

Не запрашивает сеть и не пишет файлов — чистая геометрия. Источники
данных (data/ground_stations.json, data/eumetsat_frontal_track.json)
читаются вызывающим кодом; сюда передаются уже распарсенные структуры,
чтобы функцию было легко тестировать изолированно и переиспользовать
из будущего скрипта fetch по станциям (пункт 3-4 плана).

Система координат — ТА ЖЕ, что везде в проекте (см.
field_motion_common.pixel_to_km_offset()): dx_km = восток, dy_km = север
от центра Одессы (geo_config.json: center_lat/center_lon), bearing —
компасный угол atan2(dx, dy), 0°=С, 90°=В, растёт по часовой.

Геометрия выбора (см. план, пункт 2, обоснование пользователя 2026-08-14):
искать станцию не просто "ближайшую по прямой" к треку (её может снести
далеко в сторону от курса), а станцию, лежащую БЛИЖЕ ВСЕГО К ЛИНИИ
ДВИЖЕНИЯ трека (минимальное перпендикулярное отклонение perp_km от оси
движения), раздельно для "перед" (along_km > 0, куда фронт движется) и
"позади" (along_km < 0, откуда пришёл). Ограничение по along_km — чтобы
не утащить сколь угодно далёкую станцию просто потому что она точно на
оси: разумный диапазон "перед"/"позади" тоже ограничен (MAX_ALONG_KM).
"""

import math

# ── Параметры отбора (см. обоснование в докстринге модуля) ──────────────────
# Полуширина коридора вдоль оси движения — станция дальше этого
# перпендикулярного отклонения не считается "лежащей на курсе".
MAX_PERP_KM = 80.0
# Максимальное расстояние вдоль оси движения (в любую сторону) — соответствует
# буферу "~100-150км вдоль траектории" из плана 2026-08-14, взят верхний край.
MAX_ALONG_KM = 150.0


def _station_dx_dy_km(lat, lon, center_lat, center_lon, km_per_deg_lat, km_per_deg_lon):
    """Переводит lat/lon станции в (dx_km, dy_km) относительно центра Одессы,
    той же линейной (экваториальной) проекцией, что и pixel_to_km_offset() —
    km_per_deg_lon уже включает cos(center_lat), см. field_motion_common.py."""
    dx_km = (lon - center_lon) * km_per_deg_lon
    dy_km = (lat - center_lat) * km_per_deg_lat
    return dx_km, dy_km


def select_ahead_behind(track_dx_km, track_dy_km, movement_bearing_deg,
                         stations, center_lat, center_lon,
                         km_per_deg_lat, km_per_deg_lon,
                         max_perp_km=MAX_PERP_KM, max_along_km=MAX_ALONG_KM):
    """Возвращает {"ahead": entry|None, "behind": entry|None}.

    track_dx_km/track_dy_km — текущая позиция трека (та же система координат,
    что dx_km/dy_km в eumetsat_frontal_track.json).
    movement_bearing_deg — movement_bearing_deg трека (None → вернёт оба None,
    без скорости направление движения не определено, выбор станции по курсу
    в принципе не имеет смысла).
    stations — список словарей минимум с полями name, lat, lon
    (data/ground_stations.json как есть).

    entry — словарь исходной станции + добавленные along_km, perp_km, dist_km.
    """
    if movement_bearing_deg is None:
        return {"ahead": None, "behind": None}

    b = math.radians(movement_bearing_deg)
    # Единичный вектор оси движения в конвенции dx=восток,dy=север,
    # bearing=atan2(dx,dy) ⇒ dx=sin(b), dy=cos(b) (см. _bearing_compass
    # в eumetsat_frontal_track.py — та же формула, инвертированная).
    ux, uy = math.sin(b), math.cos(b)

    ahead_candidates = []
    behind_candidates = []

    for st in stations:
        lat, lon = st.get("lat"), st.get("lon")
        if lat is None or lon is None:
            continue
        st_dx, st_dy = _station_dx_dy_km(lat, lon, center_lat, center_lon,
                                          km_per_deg_lat, km_per_deg_lon)
        vx = st_dx - track_dx_km
        vy = st_dy - track_dy_km

        along_km = vx * ux + vy * uy          # проекция на ось движения
        perp_km = -vx * uy + vy * ux          # перпендикулярное отклонение

        if abs(perp_km) > max_perp_km or abs(along_km) > max_along_km:
            continue

        entry = dict(st)
        entry["along_km"] = round(along_km, 1)
        entry["perp_km"] = round(perp_km, 1)
        entry["dist_km"] = round(math.hypot(along_km, perp_km), 1)

        if along_km > 0:
            ahead_candidates.append(entry)
        elif along_km < 0:
            behind_candidates.append(entry)
        # along_km == 0 (ровно на траверзе трека) — не "перед" и не "позади",
        # сознательно не берём ни в одну группу (пограничный случай, крайне
        # маловероятен на реальных координатах).

    def _best(cands):
        if not cands:
            return None
        # Первичный критерий — минимальное перпендикулярное отклонение
        # (станция максимально "на курсе"), вторичный — минимальное
        # расстояние вдоль оси (ближайшая, а не самая дальняя на курсе).
        return min(cands, key=lambda e: (abs(e["perp_km"]), abs(e["along_km"])))

    return {
        "ahead": _best(ahead_candidates),
        "behind": _best(behind_candidates),
    }


def generate_axis_samples(track_dx_km, track_dy_km, axis_deg, area_km2, aspect_ratio,
                           step_km=60.0, min_half_km=60.0, max_half_km=300.0,
                           extend_factor=1.3):
    """[Добавлено 2026-09-03, см. docs/topics/frontal_line_stations.md]
    Возвращает список (offset_km, dx_km, dy_km) точек вдоль оси
    вытянутости системы (axis_deg) — не одна пара ahead/behind в центре
    трека, а несколько, разнесённых вдоль фронта, чтобы потом соединить их
    в кривую (сама сборка кривой — отдельный шаг, не здесь, здесь только
    геометрия точек отбора).

    Половина длины оси оценивается из area_km2/aspect_ratio, приближая
    систему эллипсом (area = π·a·b, aspect_ratio = a/b ⇒
    a = sqrt(area·aspect_ratio/π) — большая полуось), с запасом
    extend_factor: near-tier сам обрезан окном ~192км, реальный фронт
    обычно длиннее видимого куска. Результат зажат в [min_half_km,
    max_half_km] — если area_km2/aspect_ratio отсутствуют или некорректны
    (<=0), используется min_half_km как половина длины.

    axis_deg — тот же bearing-convention, что и movement_bearing_deg
    (atan2(dx,dy), 0°=С, 90°=В) — см. докстринг модуля. У оси эллипса
    направление определено с точностью до 180° (ось 12° и 192° — одна и
    та же линия), для симметричного сэмплирования в обе стороны это
    неважно.

    Если axis_deg is None — вернёт только сам центр трека (одна точка,
    offset_km=0.0), без попытки разнести вдоль неизвестной оси."""
    if axis_deg is None:
        return [(0.0, round(track_dx_km, 2), round(track_dy_km, 2))]

    if area_km2 and aspect_ratio and area_km2 > 0 and aspect_ratio > 0:
        semi_major_km = math.sqrt(area_km2 * aspect_ratio / math.pi)
        half_len_km = semi_major_km * extend_factor
    else:
        half_len_km = min_half_km
    half_len_km = max(min_half_km, min(max_half_km, half_len_km))

    rad = math.radians(axis_deg)
    ux, uy = math.sin(rad), math.cos(rad)  # та же конвенция, что bearing_compass

    n_steps = max(1, int(round(half_len_km / step_km)))
    samples = []
    for i in range(-n_steps, n_steps + 1):
        offset_km = i * step_km
        dx = track_dx_km + offset_km * ux
        dy = track_dy_km + offset_km * uy
        samples.append((round(offset_km, 1), round(dx, 2), round(dy, 2)))
    return samples


if __name__ == "__main__":
    # Автономный смоук-тест (не требует сети/файлов) — синтетический трек и
    # горстка синтетических станций, чтобы руками проверить геометрию перед
    # прогоном на реальных data/ground_stations.json +
    # eumetsat_frontal_track.json (это отдельный интеграционный шаг, план
    # пункт 4).
    center_lat, center_lon = 46.4406, 30.7703
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(math.radians(center_lat))

    # Трек прямо в центре Одессы (dx=dy=0), движется строго на восток (90°).
    track_dx, track_dy = 0.0, 0.0
    bearing = 90.0

    synth_stations = [
        # Ближе по ПРЯМОЙ дистанции (~54км), но заметно в стороне от оси
        # движения (perp≈20км) — специально ближе по прямой, чем следующая,
        # чтобы проверить, что выбор идёт НЕ по dist_km, а по perp_km.
        {"name": "Ближе по прямой, но в стороне от курса", "lat": center_lat + 20 / km_per_deg_lat, "lon": center_lon + 50 / km_per_deg_lon},
        # Чуть дальше по прямой (~52км), но почти точно на оси (perp≈5км) —
        # должна победить предыдущую при верной геометрии выбора.
        {"name": "Дальше по прямой, но почти на курсе", "lat": center_lat + 5 / km_per_deg_lat, "lon": center_lon + 51.8 / km_per_deg_lon},
        {"name": "Точно позади (З, 50км)", "lat": center_lat, "lon": center_lon - 50 / km_per_deg_lon},
        {"name": "Слишком далеко впереди (200км)", "lat": center_lat, "lon": center_lon + 200 / km_per_deg_lon},
        {"name": "Строго на север (не перед и не позади)", "lat": center_lat + 50 / km_per_deg_lat, "lon": center_lon},
    ]

    result = select_ahead_behind(track_dx, track_dy, bearing, synth_stations,
                                  center_lat, center_lon, km_per_deg_lat, km_per_deg_lon)

    print("=== Смоук-тест: трек в центре Одессы, движение строго на восток ===")
    for side in ("ahead", "behind"):
        e = result[side]
        if e is None:
            print(f"{side}: нет подходящей станции")
        else:
            print(f"{side}: {e['name']}  along_km={e['along_km']}  perp_km={e['perp_km']}  dist_km={e['dist_km']}")

    # Ожидаемо: ahead = "Дальше по прямой, но почти на курсе" (меньше
    # |perp_km|, несмотря на бОльшую прямую дистанцию, чем у станции "в
    # стороне от курса") — подтверждает, что критерий отбора именно
    # perp_km, а не dist_km. behind = "Точно позади". "Слишком далеко
    # впереди" (за MAX_ALONG_KM) и "строго на север" (along_km≈0, ни перед,
    # ни позади) не должны попасть ни в одну группу результата.
    assert result["ahead"] is not None and result["ahead"]["name"] == "Дальше по прямой, но почти на курсе", result["ahead"]
    assert result["behind"] is not None and result["behind"]["name"] == "Точно позади (З, 50км)"
    print("\nOK: все assert прошли (выбор по perp_km подтверждён, не по dist_km).")

    print("\n=== Смоук-тест: generate_axis_samples ===")
    # Ось строго на восток-запад (90°), система area=9888.5 aspect=2.27
    # (реальные значения track_id=892 на момент написания, см.
    # docs/topics/frontal_line_stations.md) ⇒ semi_major≈84.5км,
    # half_len с запасом 1.3× ≈ 109.9км ⇒ зажимается в [60,300] без
    # изменений ⇒ при step=60км это n_steps=round(109.9/60)=2 ⇒ 5 точек
    # offset -120,-60,0,60,120.
    samples = generate_axis_samples(0.0, 0.0, 90.0, 9888.5, 2.27, step_km=60.0)
    offsets = [s[0] for s in samples]
    print("offsets_km:", offsets)
    assert offsets == [-120.0, -60.0, 0.0, 60.0, 120.0], offsets
    # При axis_deg=90° (восток) точка offset=60 должна сдвинуться на
    # dx=+60, dy=0 (а не наоборот) — проверка конвенции bearing.
    off60 = [s for s in samples if s[0] == 60.0][0]
    assert abs(off60[1] - 60.0) < 0.01 and abs(off60[2] - 0.0) < 0.01, off60
    # axis_deg=None ⇒ одна точка, сам центр.
    single = generate_axis_samples(10.0, -5.0, None, 1000.0, 2.0)
    assert single == [(0.0, 10.0, -5.0)], single
    print("OK: generate_axis_samples — offsets и dx/dy-конвенция подтверждены.")
