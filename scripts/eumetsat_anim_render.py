"""
eumetsat_anim_render.py — готовые MP4-петли (последние ~2 часа) для каждого
слоя просмотрщика eumetsat.html, вместо живой покадровой анимации по WMS-
тайлам в браузере.

ПОЧЕМУ ТАК: живая анимация в Leaflet (add/remove WMS-тайлов на каждый тик)
оказалась ненадёжной на практике — каждый кадр это НЕСКОЛЬКО отдельных
GetMap-запросов (по тайлу стандартной XYZ-сетки), и если хотя бы один тайл
не успел/не смог загрузиться, в этом месте кадра видно НАСКВОЗЬ базовую
карту (см. обсуждение в чате, скриншот с "дырой" у Констанцы). Патчи
(двойной буфер с кроссфейдом, порог допустимых ошибок тайлов) снижали
частоту, но не убирали проблему в принципе — слишком много точек отказа на
клиенте. Теперь сервер (GitHub Actions) сам один раз собирает готовый ролик
из ОДНОГО GetMap-запроса на кадр (не тайлами — цельным изображением на весь
обзор), кодирует в MP4, кладёт ОДИН файл на слой. Браузер просто проигрывает
обычный <video> — ни одного сетевого запроса к EUMETSAT на клиенте, мерцать
нечему.

ГЕОГРАФИЯ: BBOX шире, чем маленький квадрат анализа вокруг Одессы (у
eumetsat_cloud_forecast.py и т.п.) — здесь это обзорная картинка для
просмотра (как на скринах: Николаев, Крым, Констанца), не точка для
пиксельных расчётов.

ПРОЗРАЧНОСТЬ: у видео (H.264/MP4) нет альфа-канала — прозрачные "нет
данных" пиксели WMS-слоя иначе стали бы чёрными провалами без контекста.
Поэтому каждый кадр перед кодированием накладывается на сплошную подложку
(тёмно-серый, нейтрально и для дневных, и для ночных сцен) — это ПРОЩЕ и
надёжнее, чем тянуть в кадр ещё и базовую карту (OSM-тайлы), а качество
достаточное для просмотра движения. Настоящую карту-подложку можно добавить
позже, если понадобится (см. TODO ниже).

ЧАСТОТА: не на каждый гейт 10-15 мин (это 9 слоёв * до 13 кадров = больше
сотни GetMap-запросов за прогон) — отдельный, более редкий гейт в
gh_satellite_pipeline.py (см. check_eumetsat_anim_render, ~20-25 мин).

Пишет по одному файлу на слой: data/anim/<key>.mp4 (перезаписывается
каждый раз, история не копится — только текущая петля).
"""

import os
import shutil
import subprocess
import tempfile

import numpy as np
from PIL import Image

import field_motion_common as fc

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANIM_DIR = os.path.join(BASE_DIR, "data", "anim")
MANIFEST_FILE = os.path.join(ANIM_DIR, "manifest.json")

# Широкий обзорный bbox (lon_min, lat_min, lon_max, lat_max) — покрывает
# примерно ту же зону, что была доступна при свободном панорамировании в
# старой live-версии (Молдова/зап.Украина до Ростова/Краснодара, Киев до
# Стамбула), а не маленький квадрат анализа вокруг Одессы. ВАЖНО: должен
# совпадать 1:1 с ANIM_BOUNDS в eumetsat.js — если меняешь здесь, поменяй и
# там, иначе видео "уедет" от реальных координат на карте.
BBOX = (22.0, 40.0, 40.0, 52.0)
WIDTH, HEIGHT = 1000, 666  # ВАЖНО: оба размера должны быть чётными — libx264
                           # с yuv420p требует этого (chroma subsampling делит
                           # пополам), нечётные 667 валили кодирование на
                           # каждом прогоне ("height not divisible by 2")

BG_COLOR = (18, 20, 24, 255)  # нейтральная подложка вместо альфа-прозрачности

MAX_ANIM_FRAMES = 13  # потолок кадров даже для li_afa (шаг 5 мин = 25/2ч) —
                       # это ПРОСМОТР петли, не точный анализ, для плавности
                       # достаточно, а стоимость (кол-во запросов) ограничена
MIN_FRAMES_FOR_VIDEO = 2
FPS = 2  # 0.5 сек/кадр — достаточно медленно, чтобы разглядеть движение

# Зеркало LAYERS из eumetsat.js — если добавляешь/меняешь слой там, поменяй
# и здесь (общего конфига между Python и JS в проекте пока нет).
LAYERS = {
    "clm":        {"name": "msg_fes:clm",           "style": "",                                   "step_minutes": 15},
    "cth":        {"name": "msg_fes:cth",            "style": "",                                   "step_minutes": 15},
    "h60b":       {"name": "msg_fes:h60b",           "style": "",                                   "step_minutes": 15},
    "h40b":       {"name": "mtg_fd:h40b",            "style": "mtg_fd:mtg_h40b_default",             "step_minutes": 10},
    "gii_kindex": {"name": "msg_fes:gii_kindex",     "style": "",                                   "step_minutes": 15},
    "li_afa":     {"name": "mtg_fd:li_afa",          "style": "",                                   "step_minutes": 5},
    "geocolour":  {"name": "mtg_fd:rgb_geocolour",   "style": "",                                   "step_minutes": 10},
    "ir108":      {"name": "mtg_fd:ir105_hrfi",      "style": "mtg_fd:mtg_fd_ir105_hrfi_grayscale",  "step_minutes": 10},
    "cloudtype":  {"name": "mtg_fd:rgb_cloudtype",   "style": "raster",                              "step_minutes": 10},
    "cloudphase": {"name": "mtg_fd:rgb_cloudphase",  "style": "raster",                              "step_minutes": 10},
}


def _time_steps(step_minutes, server_latest_iso):
    n = min(MAX_ANIM_FRAMES, (120 // step_minutes) + 1)
    if server_latest_iso:
        latest_min = fc._parse_iso_minutes(server_latest_iso)
        return [
            fc.datetime.fromtimestamp((latest_min - step_minutes * i) * 60, tz=fc.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:00.000Z")
            for i in range(n - 1, -1, -1)
        ]
    return fc.build_time_steps(step_minutes, n, latest_as_none=False)


def _composite_frame(rgba):
    bg = Image.new("RGBA", (rgba.shape[1], rgba.shape[0]), BG_COLOR)
    fg = Image.fromarray(rgba, mode="RGBA")
    bg.alpha_composite(fg)
    return bg.convert("RGB")


def render_layer(key, cfg):
    server_latest_iso, _ = fc.get_layer_latest_time(cfg["name"])
    times_iso = _time_steps(cfg["step_minutes"], server_latest_iso)

    tmp_dir = tempfile.mkdtemp(prefix=f"eumanim_{key}_")
    frame_i = 0
    failed = 0
    try:
        for t_iso in times_iso:
            try:
                arr = fc.fetch_map_custom(cfg["name"], BBOX, WIDTH, HEIGHT,
                                           time_iso=t_iso, style=cfg["style"])
            except Exception as e:
                # одиночный недоступный кадр не обрывает весь ролик — как и
                # в bootstrap других eumetsat_*.py скриптов, пропускаем и
                # собираем ролик из того, что получилось
                failed += 1
                print(f"  [SKIP] eumetsat_anim_render.py: {key} @ {t_iso} недоступен: {e}")
                continue
            frame = _composite_frame(arr)
            frame.save(os.path.join(tmp_dir, f"frame_{frame_i:03d}.png"))
            frame_i += 1

        if frame_i < MIN_FRAMES_FOR_VIDEO:
            print(f"  [WARN] eumetsat_anim_render.py: {key} — годных кадров {frame_i}/{len(times_iso)}, пропуск ролика")
            return False

        os.makedirs(ANIM_DIR, exist_ok=True)
        out_path = os.path.join(ANIM_DIR, f"{key}.mp4")
        tmp_out = out_path.replace(".mp4", ".tmp.mp4")  # ВАЖНО: расширение
        # должно остаться .mp4 у временного файла тоже — ffmpeg определяет
        # формат контейнера ПО РАСШИРЕНИЮ имени файла, а не по -c:v; с
        # "<key>.mp4.tmp" он не мог понять, что это MP4, и падал с "Unable
        # to choose an output format" (см. инцидент — все 10 слоёв упали
        # на этом одновременно). "-f mp4" ниже — дополнительная страховка,
        # чтобы не зависеть от расширения впредь.
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", os.path.join(tmp_dir, "frame_%03d.png"),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-f", "mp4",
            tmp_out,
        ]
        # capture_output вместо -loglevel error + check=True: без реального
        # текста stderr от ffmpeg причину сбоя не увидеть — логи самого
        # запуска GitHub Actions мне недоступны (редирект на Azure Blob
        # Storage вне разрешённых доменов песочницы), а голый exit code
        # (например, 234) сам по себе ничего не объясняет.
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg exit {r.returncode}: {r.stderr[-2000:]}")
        os.replace(tmp_out, out_path)  # атомарная замена — не оставить битый файл, если упадёт на середине
        print(f"  [OK] eumetsat_anim_render.py: {key} — {frame_i}/{len(times_iso)} кадров, пропущено {failed}")
        return True
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def main():
    import json
    now = fc.datetime.now(fc.timezone.utc)
    manifest = {}
    if os.path.exists(MANIFEST_FILE):
        try:
            with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}

    # ВАЖНО: каждый слой в своём try/except — раньше необработанное
    # исключение на ПЕРВОМ слое (например, сбой ffmpeg) убивало весь
    # процесс, и ни один из следующих 9 слоёв даже не пробовался, и ничего
    # не писалось вообще (см. инцидент — data/anim отсутствовал в репо
    # целиком после "успешного" по логам GH Actions прогона).
    debug = {}
    for key, cfg in LAYERS.items():
        try:
            ok = render_layer(key, cfg)
            debug[key] = {"ok": ok}
            if ok:
                manifest[key] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception as e:
            debug[key] = {"ok": False, "error": str(e)}
            print(f"  [ERROR] eumetsat_anim_render.py: {key} упал целиком: {e}")

    os.makedirs(ANIM_DIR, exist_ok=True)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    # Отдельный debug-файл — логи самого запуска GitHub Actions недоступны
    # для чтения через API (редирект на Azure Blob Storage вне разрешённых
    # доменов), поэтому статус каждого слоя нужно видеть прямо в репо.
    with open(os.path.join(ANIM_DIR, "debug.json"), "w", encoding="utf-8") as f:
        json.dump({"timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "layers": debug}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
