# AI CURRENT TASK

## ID
FRONT_DETECTION_ARCHITECTURE_001

## Status
OPEN — Proposal готов, ожидает GPT review

## Goal
Архитектура детекции реальных атмосферных фронтов (cold/warm/occlusion/
stationary) на базе Satellite → BUFR → Open-Meteo, с покраской поверх
спутникового снимка и confidence-уровнями. Полный текст — см.
`docs/ai/FRONT_DETECTION_ARCHITECTURE.md`.

## Context (кратко)
- Пользователь: 1-2 недели назад была попытка Europe-wide детектора
  фронтов на Cloud Mask (CLM) — захватывал весь/очень большой массив
  облачности вместо фронта. Код не найден в git-истории/docs (архив
  `eumetsat_archive.md` не содержит Europe+CLM, commit-search пуст) —
  анализ сделан по симптому, не по коду.
- Существующий near/west satellite-детектор (`eumetsat_cloud_forecast.py`
  / `eumetsat_west_watch.py` / `eumetsat_frontal_track.py`) НЕ имеет этой
  проблемы — локальный охват (Одесса ±2.5° / west bbox), явный
  area+aspect_ratio фильтр frontlike. Активно развивается, последний
  коммит 2026-09-07 (классификация тёплый/холодный по станциям).
- `EUROPE_FRONT_LINE_001` НЕ трогается этой задачей — отдельный трек,
  статус: Proposal v10 implemented (commit `62f224e`), ожидает GPT
  implementation review + живая проверка на VPS.

## Proposal (Layer 1, Satellite Front Detector) — см. полный текст в
docs/ai/FRONT_DETECTION_ARCHITECTURE.md

Ключевая идея: для Europe-wide спутникового поиска не использовать
бинарную CLM-маску напрямую (гипотеза — именно так провалилась
предыдущая попытка), а строить непрерывное поле CTH внутри облачной
области и применять к нему уже реализованный и протестированный
Hessian-based ridge extraction из `open_meteo_frontal_confirm.py`
(переиспользование, не копирование кода).

## Constraints
- Код не менять до APPROVE.
- Гипотеза о причине провала Europe-CLM не проверена на реальных данных
  (кода нет) — первая же реализация должна начаться с теста на 1-2
  живых тайлах.

## Next action
GPT: review Proposal (Layer 1) в `docs/ai/AI_DISCUSSION.md` — APPROVE
или REQUEST CHANGES. После APPROVE — реализация с diff +
py_compile/ast.parse перед пушем, затем Layer 2 (BUFR)/Layer 3
(Open-Meteo confirmation)/Fusion — по мере готовности Layer 1.
