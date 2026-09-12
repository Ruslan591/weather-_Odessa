# AI CURRENT TASK

## ID
FRONT_DETECTION_ARCHITECTURE_001

## Status
OPEN — Proposal v2 готов, ожидает GPT review (после REQUEST CHANGES на v1)

## Goal
Архитектура детекции реальных атмосферных фронтов (cold/warm/occlusion/
stationary) на базе Satellite → BUFR → Open-Meteo. Полный текст — см.
`docs/ai/FRONT_DETECTION_ARCHITECTURE.md` (Proposal v2).

## История ревью
- v1: Proposal "CTH ridge = фронт" через Hessian extraction (переиспользование
  кода EUROPE_FRONT_LINE_001) — GPT REQUEST CHANGES (6 пунктов, см.
  AI_DISCUSSION.md).
- v2: центральная схема заменена на `features → P_front_satellite →
  geometry extraction`, CTH понижен до одного признака, добавлена
  Фаза 1 (эксперимент на 2 реальных случаях: near-tier трек 135
  2026-08-18, west-tile тот же период), BUFR — station A/B по обе
  стороны normal к сегменту вместо простой близости.

## Constraints
- Код не менять/не запускать до APPROVE.
- Europe-wide production pipeline не запускать — сначала Фаза 1
  (эксперимент на 1-2 случаях).
- Hessian ridge extraction — не production-import, только временно на
  эксперименте; вынос в `scripts/front_geometry.py` — только после
  подтверждения на satellite-поле.

## Открытый вопрос (проверить первым шагом Фазы 1, до всего остального)
Хранит ли EUMETSAT WMS архивные кадры (`msg_fes:clm`/`cth`/`ir105_hrfi`/
`rgb_geocolour`) на глубину 3-4 недели? Тестовые случаи — 2026-08-17/18,
сейчас 2026-09-11. Если архив недоступен — Фаза 1 переносится на
следующий live-случай вместо исторических A/B.

## Next action
GPT: review Proposal v2 — достаточно ли конкретен план Фазы 1 (случаи +
признаки), приемлема ли схема "перенос на live-случай, если история
недоступна". APPROVE или REQUEST CHANGES.
