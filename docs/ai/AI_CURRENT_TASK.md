# AI CURRENT TASK

## ID
FRONT_DETECTION_ARCHITECTURE_001

## Status
OPEN — Proposal v3 (архитектура + GO-NO-GO блок), archive check выполнен
(GO). Ждём APPROVE от GPT перед стартом кода Фазы 1.

## Goal
Архитектура детекции реальных атмосферных фронтов (cold/warm/occlusion/
stationary) на базе Satellite → BUFR → Open-Meteo. Полный текст — см.
`docs/ai/FRONT_DETECTION_ARCHITECTURE.md` (Proposal v3).

## История ревью
- v1: "CTH ridge = фронт" — GPT REQUEST CHANGES (6 пунктов).
- v2: схема `features → P_front_satellite → geometry extraction`, GPT
  REQUEST CHANGES (1 правка: явный GO-NO-GO блок для Фазы 1 + Case B
  reference был непроверенным предположением).
- v3: добавлен GO-NO-GO блок (5 пунктов по спецификации GPT), Case B
  исправлен на верифицированный git-коммит `1d93ef3e29`
  (`data/eumetsat_west_watch.json`, 2026-08-18T04:45:00Z).

## Archive check — РЕЗУЛЬТАТ: GO
`GetCapabilities` (`view.eumetsat.int`): time extent `msg_fes:clm`/
`msg_fes:cth` = `2020-09-01T00:00:00.000Z/2026-09-12T02:45:00.000Z/PT15M`.
Архив глубже, чем предполагалось (6 лет, не 3-4 недели) — historical
Phase 1 на случаях A/B доступен, переносить на live-случай не нужно.

## Constraints
- Код не менять/не запускать до APPROVE Proposal v3.
- Europe-wide production pipeline не запускать — сначала Фаза 1.
- Hessian ridge extraction тестируется только по схеме
  `P_front_satellite → geometry`, не `CTH ridge → Front`.
- GO/NO-GO критерии Фазы 1 зафиксированы заранее — не постфактум.

## Next action
GPT: review Proposal v3 (GO-NO-GO блок + исправленный Case B +
archive check результат) — APPROVE или REQUEST CHANGES. После APPROVE —
старт экспериментального кода Фазы 1 (feature extraction на случаях A/B,
не production, не Europe-wide).
