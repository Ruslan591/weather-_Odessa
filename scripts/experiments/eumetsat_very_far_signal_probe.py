"""
eumetsat_very_far_signal_probe.py — РАЗОВЫЙ эксперимент, НЕ production. v3
(правка 2026-09-19: НИКАКОГО git — репозиторий сейчас ~15.5 ГБ / ~38000
коммитов из-за многолетней истории PNG-коммитов от *_watch.py скриптов;
git pull/git show на телефоне, где чекаут не обновлялся с лета, means
качать всю историю разом. Вместо этого — только точечные HTTPS GET к
raw.githubusercontent.com: конкретные файлы на конкретных SHA/main, без
единого обращения к git.)

Проверяет гипотезу: существует ли внутри крупного облачного массива на
very_far bbox (~2500км) устойчивая пространственно-временная структура
(front-like), или это просто одно сплошное пятно без внутренней структуры.

НЕ пишет в data/, НЕ коммитит, НЕ трогает pipeline, НЕ клонирует и не
пуллит репозиторий целиком — скрипту достаточно интернета и Python, чекаут
репозитория на диске вообще не требуется. Не делает никаких выводов о
наличии фронта — только собирает диагностику для последующего обсуждения.

Зависимости (field_motion_common.py, eumetsat_far_watch.py, geo_config.json)
скрипт САМ скачивает свежими с ветки main в /tmp — не полагается на
локальный чекаут (который может быть устаревшим настолько же, насколько и
не запуллен: рискует не содержать функций/констант, добавленных за лето).

Raw raster (.npy) и debug-картинки — в /tmp/eumetsat_very_far_probe/, ВНЕ
репозитория. .npy можно удалить после просмотра result.json и overlay:
    rm -f /tmp/eumetsat_very_far_probe/*.npy

Запуск (из ЛЮБОЙ директории, репозиторий локально не нужен):
    pip install numpy pillow scipy requests
    python eumetsat_very_far_signal_probe.py
"""

import io
import json
import math
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import numpy as np
import requests
from PIL import Image
from scipy import ndimage

TMP_DIR = "/tmp/eumetsat_very_far_probe"
LIBS_DIR = os.path.join(TMP_DIR, "_repo_snapshot")  # зеркало layout scripts/ + data/, только 3 файла
RAW_BASE = "https://raw.githubusercontent.com/ruslan591/weather-_Odessa"
GITHUB_FETCH_TIMEOUT = 15  # не EUMETSAT-политика (NETWORK_TIMEOUT ниже) — обычный GitHub raw CDN

# Ровно 3 файла, свежие с main — НЕ из локального чекаута телефона.
DEPENDENCY_FILES = [
    ("main", "scripts/field_motion_common.py", os.path.join(LIBS_DIR, "scripts", "field_motion_common.py")),
    ("main", "scripts/eumetsat_far_watch.py", os.path.join(LIBS_DIR, "scripts", "eumetsat_far_watch.py")),
    ("main", "data/geo_config.json", os.path.join(LIBS_DIR, "data", "geo_config.json")),
]


def fetch_dependencies():
    """Скачивает 3 файла с main одним HTTPS GET каждый — НЕ git clone/pull,
    НЕ трогает никакой локальный репозиторий. Кладёт их в LIBS_DIR с тем же
    относительным layout (scripts/../data/...), который ожидает
    field_motion_common.py при вычислении своих путей через __file__."""
    for ref, repo_path, local_path in DEPENDENCY_FILES:
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        url = f"{RAW_BASE}/{ref}/{repo_path}"
        r = requests.get(url, timeout=GITHUB_FETCH_TIMEOUT)
        r.raise_for_status()
        with open(local_path, "wb") as f:
            f.write(r.content)
        print(f"[DEPS] {repo_path} <- {ref}  ({len(r.content)} bytes) -> {local_path}")


fetch_dependencies()
sys.path.insert(0, os.path.join(LIBS_DIR, "scripts"))

# Импортируем ТОЛЬКО для констант/pure-функций — ничего отсюда не
# вызывается на сеть/диск при импорте (проверено 2026-09-19), кроме чтения
# geo_config.json, который мы сами только что положили рядом.
import field_motion_common as fc  # noqa: E402
from eumetsat_far_watch import (  # noqa: E402
    _classify_cloud_mask, _cth_ordinal_index,
)

WMS_BASE = fc.WMS_BASE
GETCAPABILITIES_URL = fc.GETCAPABILITIES_URL
VERY_FAR_BBOX = fc.VERY_FAR_BBOX
VERY_FAR_KM_PER_PX = fc.VERY_FAR_TARGET_KM_PER_PX
_WMS_NS = "{http://www.opengis.net/wms}"

# Согласованная экспериментальная политика нагрузки (та же, что в
# fc.fetch_tile()/fetch_map_custom() c 2026-08-19): без retry, консервативный
# timeout — эксперимент должен мерить именно такой режим, не более мягкий.
NETWORK_TIMEOUT = 10

TMP_DIR = "/tmp/eumetsat_very_far_probe"
RESULT_JSON = os.path.join(TMP_DIR, "result.json")

# STYLE_IR105/CRS — НЕ мои предположения: это ровно то, что уже используют
# в production eumetsat_ir_motion.py и eumetsat_cloud_forecast.py для этого
# же слоя (near-tier, месяцами в работе). Дефолтный (безымянный) стиль,
# который стоял в v1 этого эксперимента, мог быть цветной палитрой — это
# была реальная ошибка v1, не гипотетическая. crs="EPSG:4326" — тоже их
# выбор, а не мой; см. capabilities-проверку supported_crs ниже для
# независимого подтверждения именно на very_far bbox.
STYLE_IR105 = "mtg_fd:mtg_fd_ir105_hrfi_grayscale"

LAYERS = {
    "clm":   {"name": "msg_fes:clm",       "crs": "CRS:84",    "style": ""},
    "cth":   {"name": "msg_fes:cth",       "crs": "CRS:84",    "style": ""},
    "ir105": {"name": "mtg_fd:ir105_hrfi", "crs": "EPSG:4326", "style": STYLE_IR105},
}

# ВАЖНО (правка по ревью, пункт 1): это ВНУТРЕННЕЕ поле "timestamp" из
# исторических data/eumetsat_very_far_watch.json (время наблюдения EUMETSAT,
# использованное для параметра time= при GetMap) — НЕ время git-коммита
# (то на ~15-20 мин позже, это когда пайплайн запушил результат). Оба
# значения проверены read-only 2026-09-19 (git show эквивалент через raw
# content на конкретном SHA):
#   0402e828: timestamp=14:30:00Z, commit pushed=14:49:55Z
#   ddb1e387: timestamp=14:45:00Z, commit pushed=15:04:40Z
#   31e04593: timestamp=15:00:00Z, commit pushed=15:17:42Z
# Используем timestamp (не commit time) — это то, что реально пойдёт в
# параметр time= GetMap-запроса и должно совпасть с кадром GeoColour.
REQUESTED_TIMESTAMPS = [
    "2026-09-18T14:30:00.000Z",
    "2026-09-18T14:45:00.000Z",
    "2026-09-18T15:00:00.000Z",
]

GIT_SHA_FOR_TIMESTAMP = {
    "2026-09-18T14:30:00.000Z": "0402e828",
    "2026-09-18T14:45:00.000Z": "ddb1e387",
    "2026-09-18T15:00:00.000Z": "31e04593",
}
GEOCOLOUR_PATH_IN_REPO = "data/anim/very_far_geocolour.png"

MIN_COMPONENT_PX = 30  # минимальный размер компоненты для connected-component диагностики


def _bbox_dimensions(bbox, target_km_per_px):
    """Локальная копия eumetsat_anim_render._bbox_dimensions() — не
    импортирую весь тот модуль ради одной формулы."""
    lon_min, lat_min, lon_max, lat_max = bbox
    center_lat = (lat_min + lat_max) / 2.0
    km_per_deg_lon = 111.32 * math.cos(math.radians(center_lat))
    km_per_deg_lat = 111.32
    width_km = (lon_max - lon_min) * km_per_deg_lon
    height_km = (lat_max - lat_min) * km_per_deg_lat
    width = max(2, int(round(width_km / target_km_per_px)))
    height = max(2, int(round(height_km / target_km_per_px)))
    width += width % 2
    height += height % 2
    return width, height


WIDTH, HEIGHT = _bbox_dimensions(VERY_FAR_BBOX, VERY_FAR_KM_PER_PX)


# ============================================================
# 1. GetCapabilities — с наследованием Dimension/CRS от родителя
#    (правка по ревью, пункт 5) + supported_crs (пункт 4)
# ============================================================

def check_capabilities(layer_name, timeout=NETWORK_TIMEOUT):
    """WMS 1.3.0 разрешает слою НЕ иметь собственный <Dimension name="time">
    и <CRS>, наследуя их от родительского <Layer>. Рекурсивно спускаемся от
    корня, накапливая last-seen Dimension/CRS по пути, и когда находим
    нужный слой по имени — возвращаем накопленное (own, если у него есть
    свой <Dimension>/<CRS>, иначе унаследованное).

    raw_layer_xml_snippet — сырой XML найденного <Layer> (обрезан), чтобы
    можно было визуально проверить результат, а не верить парсингу вслепую
    (особенно важно для msg_fes:cth, который никогда раньше не проверялся)."""
    out = {
        "layer": layer_name, "layer_found": False,
        "nearest_value": None, "default_time": None, "time_dimension_raw": None,
        "dimension_source": "none",  # "own" | "inherited" | "none"
        "supported_crs": [], "raw_layer_xml_snippet": None, "error": None,
    }
    try:
        r = requests.get(GETCAPABILITIES_URL, timeout=timeout)
        r.raise_for_status()
        root = ET.fromstring(r.content)

        def walk(el, inherited_dim, inherited_crs):
            dim_el = el.find(f'{_WMS_NS}Dimension[@name="time"]')
            crs_els = el.findall(_WMS_NS + "CRS")
            current_crs = list(inherited_crs) + [c.text.strip() for c in crs_els if c.text]

            if dim_el is not None:
                current_dim = {
                    "nearest_value": dim_el.get("nearestValue"),
                    "default_time": dim_el.get("default"),
                    "time_dimension_raw": (dim_el.text or "").strip(),
                    "dimension_source": "own",
                }
            else:
                current_dim = dict(inherited_dim)
                if current_dim["dimension_source"] == "own":
                    current_dim["dimension_source"] = "inherited"

            name_el = el.find(_WMS_NS + "Name")
            if name_el is not None and name_el.text == layer_name:
                snippet = ET.tostring(el, encoding="unicode")[:3000]
                return {**current_dim, "supported_crs": sorted(set(current_crs)),
                        "raw_layer_xml_snippet": snippet}

            for child in el.findall(_WMS_NS + "Layer"):
                found = walk(child, current_dim, current_crs)
                if found is not None:
                    return found
            return None

        base_dim = {"nearest_value": None, "default_time": None,
                    "time_dimension_raw": None, "dimension_source": "none"}
        # Баг v3, найден 2026-09-19 на живом ответе VPS: <Layer> вложены
        # внутрь <Capability>, а не напрямую под корнем <WMS_Capabilities>.
        # Обход от root напрямую никогда не заходил внутрь <Capability> —
        # находил 0 слоёв даже когда они реально есть в XML. Спускаемся
        # явно через <Capability> к корневому <Layer> дереву.
        capability_el = root.find(_WMS_NS + "Capability")
        root_layer_el = capability_el.find(_WMS_NS + "Layer") if capability_el is not None else None
        found = walk(root_layer_el, base_dim, []) if root_layer_el is not None else None
        if found is not None:
            out["layer_found"] = True
            out.update(found)
    except Exception as e:
        out["error"] = str(e)
    return out


# ============================================================
# 2. Проверка сетки времени — независимый факт, НЕ сводится с
#    used_timestamp в один статус (правка по ревью, пункт 6)
# ============================================================

def check_grid_alignment(time_dimension_raw, requested_iso):
    """ЧЕСТНО: парсинг НЕ проверен на живом ответе сервера. raw попадает в
    result.json как есть. on_grid=True/False говорит ТОЛЬКО о том, что
    requested_timestamp арифметически лежит на объявленной сетке — это
    НЕ доказывает, что сервер фактически использовал именно его (это
    отдельно, только used_timestamp из Warning-заголовка, см. ниже)."""
    result = {"raw": time_dimension_raw, "on_grid": "unknown", "note": None}
    if not time_dimension_raw or "/" not in time_dimension_raw:
        result["note"] = "raw пустой или не содержит '/' — сверить формат вручную"
        return result
    parts = time_dimension_raw.split("/")
    if len(parts) != 3:
        result["note"] = f"неожиданное число частей после split('/') = {len(parts)} — сверить raw вручную"
        return result
    start_s, _end_s, period_s = parts
    try:
        start = datetime.strptime(start_s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        req = datetime.strptime(requested_iso, "%Y-%m-%dT%H:%M:00.000Z").replace(tzinfo=timezone.utc)
        m = re.match(r"^PT(\d+)M$", period_s)
        if not m:
            result["note"] = f"период '{period_s}' не в формате 'PTxxM' — сверить вручную (может быть PT1H и т.п.)"
            return result
        step_min = int(m.group(1))
        delta_min = (req - start).total_seconds() / 60.0
        result["step_minutes"] = step_min
        result["on_grid"] = bool(abs(delta_min % step_min) < 1e-6)
    except Exception as e:
        result["note"] = f"ошибка парсинга: {e}"
    return result


# ============================================================
# 3. GetMap: timeout=10, БЕЗ retry (правка по ревью, пункт 2)
# ============================================================

def fetch_map_probe(layer_name, bbox_lonlat, width, height, time_iso, crs="CRS:84", style=""):
    """ИЗОЛИРОВАННАЯ копия минимальной GetMap-логики — доступ к HTTP
    headers/timing, которых нет в fc.fetch_map_custom(). НЕ трогает
    production-версию. timeout=10, без повторов — экспериментальная
    политика нагрузки, согласованная отдельно (не production 25с/2 или
    смягчённый вариант)."""
    min_lon, min_lat, max_lon, max_lat = bbox_lonlat
    if crs == "EPSG:4326":
        bbox_str = f"{min_lat},{min_lon},{max_lat},{max_lon}"
    else:
        bbox_str = f"{min_lon},{min_lat},{max_lon},{max_lat}"

    params = {
        "service": "WMS", "version": "1.3.0", "request": "GetMap",
        "layers": layer_name, "styles": style, "crs": crs, "bbox": bbox_str,
        "width": width, "height": height, "format": "image/png",
        "transparent": "true", "time": time_iso,
    }

    probe = {
        "layer": layer_name, "requested_timestamp": time_iso, "style": style, "crs": crs,
        "http_status": None, "elapsed_sec": None, "response_bytes": None,
        "content_type": None, "warning_header": None,
        "used_timestamp": None, "used_timestamp_source": None,
        "error": None,
    }

    t0 = time.monotonic()
    try:
        r = requests.get(WMS_BASE, params=params, timeout=NETWORK_TIMEOUT)
        probe["elapsed_sec"] = round(time.monotonic() - t0, 3)
        probe["http_status"] = r.status_code
        probe["response_bytes"] = len(r.content)
        probe["content_type"] = r.headers.get("content-type")
        warning = r.headers.get("Warning")
        probe["warning_header"] = warning

        if warning:
            m = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?", warning)
            if m:
                probe["used_timestamp"] = m.group(0)
                probe["used_timestamp_source"] = "Warning header"
        if probe["used_timestamp"] is None:
            probe["used_timestamp_source"] = (
                "недоступно: сервер не вернул время в Warning-заголовке; "
                "фактически использованный timestamp неизвестен (независимый "
                "факт от requested_timestamp/grid_alignment, не выводится из них)"
            )

        if r.status_code == 200 and "image" in (probe["content_type"] or ""):
            img = Image.open(io.BytesIO(r.content)).convert("RGBA")
            return probe, np.array(img)
        probe["error"] = (f"HTTP {r.status_code}, content-type="
                           f"{probe['content_type']}, body[:200]={r.content[:200]!r}")
        return probe, None
    except Exception as e:
        probe["elapsed_sec"] = round(time.monotonic() - t0, 3)
        probe["error"] = str(e)
        return probe, None


# ============================================================
# 4. Историческая GeoColour — точечный HTTPS GET на конкретный SHA,
#    БЕЗ git (0 новых запросов к EUMETSAT, 0 обращений к git-истории)
# ============================================================

def extract_geocolour_by_sha(sha, out_path):
    """raw.githubusercontent.com/<sha>/<path> отдаёт содержимое файла ровно
    на этом коммите — тот же результат, что git show <sha>:<path>, но без
    единого локального git-объекта: только один HTTPS GET на один файл
    (~сотни КБ), никакой истории репозитория качать не нужно."""
    result = {"sha": sha, "ok": False, "error": None}
    try:
        url = f"{RAW_BASE}/{sha}/{GEOCOLOUR_PATH_IN_REPO}"
        r = requests.get(url, timeout=GITHUB_FETCH_TIMEOUT)
        r.raise_for_status()
        with open(out_path, "wb") as f:
            f.write(r.content)
        result["ok"] = True
        result["bytes"] = len(r.content)
    except Exception as e:
        result["error"] = str(e)
    return result


# ============================================================
# 5. Декодирование CLM/CTH/IR105
# ============================================================

def _minmax(field):
    lo, hi = np.nanmin(field), np.nanmax(field)
    if hi - lo < 1e-9:
        return np.zeros_like(field, dtype=np.float32)
    return (field - lo) / (hi - lo)


def _gradient_magnitude(field):
    gy, gx = np.gradient(field.astype(np.float32))
    return np.sqrt(gx ** 2 + gy ** 2)


def _orientation_field(field, win=9):
    """Структурный тензор (Jxx,Jxy,Jyy), сглаженный окном win. Возвращает
    (coherence, orientation_deg): coherence 0=изотропный шум, 1=чёткая
    линия/край; orientation_deg — угол доминирующего направления градиента
    (для диагностики "elongation"/ориентации компонент)."""
    gy, gx = np.gradient(field.astype(np.float32))
    jxx = ndimage.uniform_filter(gx * gx, size=win)
    jyy = ndimage.uniform_filter(gy * gy, size=win)
    jxy = ndimage.uniform_filter(gx * gy, size=win)
    tmp = np.sqrt((jxx - jyy) ** 2 + 4 * jxy ** 2)
    l1 = (jxx + jyy + tmp) / 2
    l2 = (jxx + jyy - tmp) / 2
    denom = l1 + l2
    coherence = np.where(denom > 1e-9, (l1 - l2) / np.where(denom > 1e-9, denom, 1), 0.0)
    orientation = 0.5 * np.arctan2(2 * jxy, (jxx - jyy) + 1e-9)
    return coherence, np.degrees(orientation)


def decode_ir105(ir105_arr):
    """STYLE_IR105 ('..._grayscale') — тот же style, что в production
    near-tier скриптах (не догадка для этого эксперимента). Он даёт
    grayscale-изображение, которое там ТРАКТУЕТСЯ как относительный proxy
    яркостной температуры для сравнения между кадрами/трендов (см.
    eumetsat_ir_motion.py, комментарий "средняя яркость, проще говоря
    средняя яркостная температура") — это НЕ калиброванная физическая
    величина в Кельвинах. Тем не менее это дальше, чем "сырой RGB
    диагностик": используется тот же интерпретационный контракт, что уже
    месяцами работает в проекте для этого слоя."""
    gray = fc.to_grayscale_luminance(ir105_arr)
    return gray, {
        "ir105_style_used": STYLE_IR105,
        "ir105_physical_decode_available": "partial",
        "ir105_decode_note": (
            "grayscale WMS style, трактуется как относительный proxy яркостной "
            "температуры по существующей конвенции проекта (eumetsat_ir_motion.py/"
            "eumetsat_cloud_forecast.py) — НЕ калиброванное значение в Кельвинах. "
            "Годится для относительных градиентов/структуры, не для абсолютных "
            "температурных выводов."
        ),
    }


def compute_channel_fields(clm_arr, cth_arr, ir105_arr):
    """Возвращает три НЕЗАВИСИМЫХ поля-сигнала (для поканальной диагностики,
    правка по ревью пункт 10) плюс декодированные маски."""
    is_cloud, valid = _classify_cloud_mask(clm_arr)
    clm_signal = _gradient_magnitude(is_cloud.astype(np.float32))

    cth_idx = _cth_ordinal_index(cth_arr)
    cth_signal = _gradient_magnitude(cth_idx)

    ir_gray, ir_meta = decode_ir105(ir105_arr)
    ir_signal = _gradient_magnitude(ir_gray)

    return {
        "clm_signal": clm_signal, "cth_signal": cth_signal, "ir_signal": ir_signal,
        "is_cloud": is_cloud, "valid": valid, "ir_meta": ir_meta,
    }


def compute_front_score(channel_fields):
    """front_score = равновзвешенная сумма 3 min-max нормированных
    градиентных полей — ПРОИЗВОЛЬНАЯ формула для первого эксперимента,
    не финальный алгоритм (см. notes в результате)."""
    fs = (
        _minmax(channel_fields["clm_signal"])
        + _minmax(channel_fields["cth_signal"])
        + _minmax(channel_fields["ir_signal"])
    ) / 3.0
    coherence, orientation_deg = _orientation_field(fs)
    return {"front_score": fs, "coherence": coherence, "orientation_deg": orientation_deg}


# ============================================================
# 6. Connected-component диагностика (правка по ревью, пункт 8) —
#    НЕ полноценный line tracker, только area/elongation/coherence/orientation
# ============================================================

def connected_component_diagnostics(front_score, coherence, orientation_deg, valid_mask, percentile=95):
    thresh = np.percentile(front_score[valid_mask], percentile) if np.any(valid_mask) else 1.0
    strong = (front_score >= thresh) & valid_mask
    strong_closed = ndimage.binary_closing(strong, structure=np.ones((3, 3)), iterations=2)
    labeled, n = ndimage.label(strong_closed)

    components = []
    for label_id in range(1, n + 1):
        mask = labeled == label_id
        area = int(mask.sum())
        if area < MIN_COMPONENT_PX:
            continue
        ys, xs = np.nonzero(mask)
        coords = np.stack([xs, ys], axis=1).astype(np.float64)
        coords -= coords.mean(axis=0)
        cov = np.cov(coords.T)
        eigvals, eigvecs = np.linalg.eigh(cov)
        order = np.argsort(eigvals)[::-1]
        eigvals = eigvals[order]
        major_axis_len = float(4 * np.sqrt(max(eigvals[0], 0)))  # ~2 std на сторону
        minor_axis_len = float(4 * np.sqrt(max(eigvals[1], 0))) if len(eigvals) > 1 else 0.0
        elongation = float(major_axis_len / minor_axis_len) if minor_axis_len > 1e-6 else None
        components.append({
            "area_px": area,
            "major_axis_len_px": round(major_axis_len, 1),
            "minor_axis_len_px": round(minor_axis_len, 1),
            "elongation": round(elongation, 2) if elongation is not None else None,
            "mean_coherence": round(float(coherence[mask].mean()), 3),
            "mean_orientation_deg": round(float(orientation_deg[mask].mean()), 1),
        })
    components.sort(key=lambda c: c["area_px"], reverse=True)
    return {
        "percentile_threshold": percentile,
        "front_score_threshold_value": float(thresh),
        "n_components_total": n,
        "n_components_above_min_size": len(components),
        "components": components[:10],  # top-10 по площади, не весь возможный шум
    }


# ============================================================
# 7. Control region candidates — НЕ "negative control" (правка по
#    ревью, пункт 7): не предполагаем заранее, что какой-то угол однороден
# ============================================================

def control_region_candidates(front_score, valid_mask):
    h, w = front_score.shape
    regions = {
        "NW_corner": (slice(0, int(h * 0.15)), slice(0, int(w * 0.15))),
        "NE_corner": (slice(0, int(h * 0.15)), slice(int(w * 0.85), w)),
        "SW_corner": (slice(int(h * 0.85), h), slice(0, int(w * 0.15))),
        "SE_corner": (slice(int(h * 0.85), h), slice(int(w * 0.85), w)),
        "center": (slice(int(h * 0.4), int(h * 0.6)), slice(int(w * 0.4), int(w * 0.6))),
    }
    out = {}
    for name, (rs, cs) in regions.items():
        region_valid = valid_mask[rs, cs]
        region_vals = front_score[rs, cs][region_valid]
        out[name] = {
            "mean": float(np.mean(region_vals)) if region_vals.size else None,
            "std": float(np.std(region_vals)) if region_vals.size else None,
            "valid_px_count": int(region_vals.size),
        }
    return out


# ============================================================
# 8. Temporal — переименовано в global_field_shift (правка по ревью,
#    пункт 9): НЕ "front_motion", это только глобальный сдвиг всего поля
# ============================================================

def global_field_shift(field_a, field_b):
    """fc.phase_shift_px() — FFT phase correlation, уже проверенная в
    проекте. Даёт ГЛОБАЛЬНЫЙ сдвиг всего поля целиком, НЕ движение
    конкретной front-like структуры — для этого нужны connected components
    ПОСЛЕ компенсации этого сдвига, что в этом probe пока не делается."""
    try:
        return fc.phase_shift_px(field_a, field_b)
    except Exception as e:
        return {"error": str(e)}


# ============================================================
# 9. Debug-изображения: поканально + итоговый overlay (правка по
#    ревью, пункт 10)
# ============================================================

def save_field_heatmap(field, out_path):
    """Голая heatmap поля (без подложки) — для поканальной диагностики."""
    norm = (_minmax(field) * 255).astype(np.uint8)
    Image.fromarray(norm, mode="L").save(out_path)


def save_geocolour_overlay(geocolour_path, front_score, out_path):
    base = Image.open(geocolour_path).convert("RGBA")
    heat = _minmax(front_score)
    heat_resized = np.array(Image.fromarray((heat * 255).astype(np.uint8)).resize(base.size))
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    px = overlay.load()
    for y in range(0, base.size[1], 2):
        for x in range(0, base.size[0], 2):
            v = int(heat_resized[y, x])
            if v > 40:
                px[x, y] = (255, 60, 60, min(180, v))
    Image.alpha_composite(base, overlay).save(out_path)


# ============================================================
# main
# ============================================================

def main():
    os.makedirs(TMP_DIR, exist_ok=True)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "network_policy": {"timeout_sec": NETWORK_TIMEOUT, "retries": 1},
        "bbox": list(VERY_FAR_BBOX), "width_px": WIDTH, "height_px": HEIGHT,
        "capabilities": {}, "grid_alignment": {},
        "geocolour_extraction": [], "eumetsat_load_probe": [],
        "signal_analysis": {}, "notes": [],
    }

    # --- 1. GetCapabilities: 3 запроса, с наследованием Dimension/CRS ---
    for key, info in LAYERS.items():
        caps = check_capabilities(info["name"])
        result["capabilities"][key] = caps
        print(f"[CAPS] {key} ({info['name']}): found={caps['layer_found']} "
              f"nearestValue={caps['nearest_value']} source={caps['dimension_source']} "
              f"supported_crs={caps['supported_crs']} raw={caps['time_dimension_raw']!r}")

    # --- 1b. Контролируемый gate (правка по финальному согласованию):
    # если capabilities явно показывает проблему по конкретному слою
    # (слой не найден ИЛИ выбранный CRS явно отсутствует в его
    # supported_crs), не пытаемся обойти это и НЕ идём к GetMap — сохраняем
    # то, что уже есть, и останавливаемся для разбора. "unknown"/пустой
    # dimension САМ ПО СЕБЕ не считается явной проблемой — это отдельный
    # факт (grid_alignment всё равно будет "unknown"), а не стоп-фактор.
    blocking_problems = []
    for key, info in LAYERS.items():
        caps = result["capabilities"][key]
        if not caps["layer_found"]:
            blocking_problems.append(f"{key} ({info['name']}): слой не найден в GetCapabilities")
            continue
        if caps["supported_crs"] and info["crs"] not in caps["supported_crs"]:
            blocking_problems.append(
                f"{key} ({info['name']}): запрошенный crs={info['crs']!r} "
                f"отсутствует в supported_crs={caps['supported_crs']}"
            )

    if blocking_problems:
        result["notes"].append("ОСТАНОВЛЕНО ПОСЛЕ CAPABILITIES: " + "; ".join(blocking_problems))
        with open(RESULT_JSON, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("\n[STOP] Обнаружена явная проблема после GetCapabilities — GetMap НЕ выполняется:")
        for p in blocking_problems:
            print(f"  - {p}")
        print(f"Результат (только capabilities): {RESULT_JSON}")
        return

    # --- 2. Проверка сетки — независимый факт от used_timestamp ---
    for key in LAYERS:
        raw = result["capabilities"][key]["time_dimension_raw"]
        result["grid_alignment"][key] = {ts: check_grid_alignment(raw, ts) for ts in REQUESTED_TIMESTAMPS}

    # --- 3. Историческая GeoColour по SHA — без git ---
    geocolour_paths = {}
    for ts, sha in GIT_SHA_FOR_TIMESTAMP.items():
        out_path = os.path.join(TMP_DIR, f"geocolour_{ts.replace(':', '-')}.png")
        r = extract_geocolour_by_sha(sha, out_path)
        r["timestamp"] = ts
        result["geocolour_extraction"].append(r)
        if r["ok"]:
            geocolour_paths[ts] = out_path
        print(f"[RAW] geocolour {ts} (sha={sha}): ok={r['ok']} bytes={r.get('bytes')} err={r['error']}")

    # --- 4. GetMap: 9 запросов, timeout=10, без retry, без поиска альтернатив ---
    rasters = {}
    for ts in REQUESTED_TIMESTAMPS:
        for key, info in LAYERS.items():
            probe, arr = fetch_map_probe(info["name"], VERY_FAR_BBOX, WIDTH, HEIGHT,
                                          ts, crs=info["crs"], style=info["style"])
            result["eumetsat_load_probe"].append(probe)
            rasters[(ts, key)] = arr
            print(f"[GETMAP] {key} @ {ts}: status={probe['http_status']} "
                  f"bytes={probe['response_bytes']} elapsed={probe['elapsed_sec']}s "
                  f"used_ts={probe['used_timestamp']}")
            if arr is not None:
                np.save(os.path.join(TMP_DIR, f"{key}_{ts.replace(':', '-')}.npy"), arr)

    # --- 5. Анализ сигнала — только для timestamp, где получены все 3 слоя ---
    per_frame = {}
    for ts in REQUESTED_TIMESTAMPS:
        clm_arr, cth_arr, ir_arr = rasters.get((ts, "clm")), rasters.get((ts, "cth")), rasters.get((ts, "ir105"))
        if clm_arr is None or cth_arr is None or ir_arr is None:
            per_frame[ts] = {"skipped": True, "reason": "не все 3 слоя получены — см. eumetsat_load_probe"}
            continue
        try:
            channels = compute_channel_fields(clm_arr, cth_arr, ir_arr)
            fs = compute_front_score(channels)
        except Exception as e:
            per_frame[ts] = {"skipped": True, "reason": f"ошибка вычисления признаков: {e}"}
            continue

        components = connected_component_diagnostics(
            fs["front_score"], fs["coherence"], fs["orientation_deg"], channels["valid"]
        )
        controls = control_region_candidates(fs["front_score"], channels["valid"])

        per_frame[ts] = {
            "skipped": False,
            "ir105_decode": channels["ir_meta"],
            "front_score_mean": float(np.mean(fs["front_score"][channels["valid"]])),
            "front_score_std": float(np.std(fs["front_score"][channels["valid"]])),
            "connected_components": components,
            "control_region_candidates": controls,
        }

        # Поканальные debug-картинки (правка по ревью, пункт 10)
        ts_tag = ts.replace(":", "-")
        try:
            save_field_heatmap(channels["clm_signal"], os.path.join(TMP_DIR, f"signal_clm_{ts_tag}.png"))
            save_field_heatmap(channels["cth_signal"], os.path.join(TMP_DIR, f"signal_cth_{ts_tag}.png"))
            save_field_heatmap(channels["ir_signal"], os.path.join(TMP_DIR, f"signal_ir_{ts_tag}.png"))
            if ts in geocolour_paths:
                save_geocolour_overlay(geocolour_paths[ts], fs["front_score"],
                                        os.path.join(TMP_DIR, f"overlay_front_score_{ts_tag}.png"))
                per_frame[ts]["debug_images"] = {
                    "clm_signal": f"signal_clm_{ts_tag}.png",
                    "cth_signal": f"signal_cth_{ts_tag}.png",
                    "ir_signal": f"signal_ir_{ts_tag}.png",
                    "front_score_overlay": f"overlay_front_score_{ts_tag}.png",
                }
        except Exception as e:
            per_frame[ts]["debug_image_error"] = str(e)

        rasters[(ts, "_front_score")] = fs["front_score"]

    result["signal_analysis"]["per_frame"] = per_frame

    # --- 6. global_field_shift — НЕ "front_motion" ---
    shifts = {}
    valid_ts = [ts for ts in REQUESTED_TIMESTAMPS if (ts, "_front_score") in rasters]
    for a, b in zip(valid_ts, valid_ts[1:]):
        shifts[f"{a} -> {b}"] = global_field_shift(rasters[(a, "_front_score")], rasters[(b, "_front_score")])
    result["signal_analysis"]["global_field_shift"] = shifts

    result["notes"] = [
        "Цель probe — установить, СУЩЕСТВУЕТ ли пригодная пространственно-временная "
        "структура внутри облачного массива. Это НЕ вывод о наличии атмосферного фронта.",
        "front_score — равновзвешенная сумма 3 нормированных градиентных полей, "
        "ПРОИЗВОЛЬНАЯ формула для первого эксперимента, не финальный алгоритм.",
        "Три независимых факта про время, НЕ сводить в один статус: requested_timestamp "
        "(что запросили) / grid_alignment (лежит ли арифметически на сетке) / "
        "used_timestamp (что сервер реально подтвердил через Warning-заголовок, если вернул).",
        "control_region_candidates — НЕ подтверждённый negative control: однородность "
        "каждого региона не доказана заранее, сравнивать нужно по факту полученных чисел.",
        "global_field_shift — глобальный сдвиг ВСЕГО поля (FFT phase correlation), "
        "не движение конкретной front-like структуры.",
        "ir105_decode.ir105_physical_decode_available='partial' — grayscale-style "
        "как относительный proxy, не калиброванная температура в Кельвинах.",
    ]

    with open(RESULT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\nГотово. Результат: {RESULT_JSON}")
    print(f"Debug-картинки: {TMP_DIR}/signal_*.png, {TMP_DIR}/overlay_front_score_*.png")
    print(f"Удалить raw .npy после просмотра: rm -f {TMP_DIR}/*.npy")


if __name__ == "__main__":
    main()
