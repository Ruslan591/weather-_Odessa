#!/usr/bin/env python3
"""
Прогон изобар/L-H/фронтов на ЗАМОРОЖЕННОМ снимке реальных полей — офлайн, без скачивания
GRIB и без зависимости от того, какая погода сейчас за окном. Нужен для подбора порогов
ICON_FRONT_*/ICON_ISOBAR_* так, чтобы менять один параметр и сразу видеть разницу на ОДНОЙ
и той же картинке, а не гадать — это новый прогон или новый порог поменял результат.

Как получить снимок (один раз, на реальных данных):
    ICON_FRONT_SAVE_TESTCASE=data/icon_front_testcase/case1.npz \
        python3 scripts/icon_front_very_far_snapshot.py
    Обычный прогон отработает как всегда (скачает, обновит сайт), плюс сохранит .npz рядом.
    Можно накопить несколько снимков под разные ситуации (спокойная погода / выраженный
    циклон с фронтом) и сравнивать пороги на каждой отдельно.

Дальше — сколько угодно раз, без сети и без ожидания cron:
    ICON_FRONT_GRAD_PERCENTILE=90 python3 scripts/icon_front_replay.py \
        data/icon_front_testcase/case1.npz /tmp/front_test_out

    Картинки лягут в /tmp/front_test_out/<tier>_isobars.png и <tier>_fronts.png
    (near/far/very_far — те же три тира, что на сайте). Меняешь переменную окружения,
    запускаешь снова — та же погода, только новый порог. Прямое сравнение картинок
    двух прогонов и покажет, что реально изменилось.

Полный список того, что можно крутить через ENV — в docs/topics/icon_eu_fronts.md.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
_SPEC = importlib.util.spec_from_file_location(
    "icon_front_snapshot", os.path.join(HERE, "icon_front_very_far_snapshot.py"))
vf = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vf)


def main():
    if len(sys.argv) < 3:
        print("Использование: icon_front_replay.py <снимок.npz> <папка_для_картинок>")
        sys.exit(1)
    testcase_path, out_dir = sys.argv[1], sys.argv[2]

    fields, lats, lons, run_dt, lead = vf.load_testcase(testcase_path)
    print(f"снимок: run={run_dt.isoformat()} lead={lead}ч, "
          f"сетка {len(lats)}x{len(lons)}, поля: {sorted(fields.keys())}")
    os.makedirs(out_dir, exist_ok=True)

    try:
        centers = vf.find_pressure_centers(fields["pmsl"], fields.get("hsurf"), lats, lons)
        print(f"L/H: {len(centers)} центров в скачанной области")
    except Exception as e:
        print(f"L/H не посчитаны: {e}")
        centers = None

    fronts = None
    if all(fields.get(k) is not None for k in ("t850", "relhum850", "u850", "v850")):
        fronts, stats = vf.compute_fronts(fields, lats, lons, centers=centers)
        print("фронты:", stats)
    else:
        print("в снимке нет T850/RH850/U850/V850 — фронты пропущены")

    for tier_key, tier_cfg in vf.TIERS.items():
        bbox, px = tier_cfg["bbox"], tier_cfg["px"]
        iso_path = os.path.join(out_dir, f"{tier_key}_isobars.png")
        vf.render_transparent_isobars(fields["pmsl"], fields.get("hsurf"), lats, lons,
                                       iso_path, bbox, px, centers=centers)
        print(f"[{tier_key}] изобары -> {iso_path}")
        if fronts is not None:
            fr_path = os.path.join(out_dir, f"{tier_key}_fronts.png")
            n = vf.render_transparent_fronts(fronts, centers, fr_path, bbox, px)
            print(f"[{tier_key}] фронтов в кадре: {n} -> {fr_path}")


if __name__ == "__main__":
    main()
