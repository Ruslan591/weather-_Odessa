---
тема: расписание и выбор модели ИИ для генерации анализа (data/ai_schedule.json)
---
# Расписание генерации AI-анализа и выбор модели

## Как это работает
- Файл data/ai_schedule.json правит только человек (меню scripts/ai_schedule.py в Termux), его читает scripts/generate_ai_analysis.py (load_schedule). На VPS и в облаке файл берётся из репозитория GitHub.
- Генерация запускается, если выполнено ЛЮБОЕ из: точка времени (time_points: час и минута UTC, дни 0=Вс..6=Сб, provider claude/gemini/оба, допуск tolerance_min) или триггер по модели (model_triggers: ECMWF IFS, ICON EU, UKMO, Arpège, GFS, GRAPES; срабатывает, когда вышел новый прогон модели). Без записей генерация по расписанию не идёт (остаётся ручной запуск --force).
- run_key в data/forecast_analysis_gemini.json показывает причину последнего запуска: `time:ДАТА:ЧЧ:ММ` или `model:ДАТАTЧЧ:ММ:МОДЕЛЬ`.

## Меню (scripts/ai_schedule.py), состояние на 2026-11-28
- Пункты: 1 добавить точку времени, 2 удалить, 3 триггеры по моделям, 4 допуск, 5 генерировать немедленно, 6 выбрать модель ИИ (новое), 7 отправить расписание на GitHub (новое), 0 выход (при несохранённых в GitHub изменениях спрашивает «Отправить?»).
- Выбор модели: в ai_schedule.json ключ models: {"gemini": ["имя1","имя2"], "claude": "имя"}. Gemini это цепочка по приоритету (первая основная, остальные запасные при 429/5xx), Claude одна модель. Без ключа работают значения по умолчанию: Gemini gemini-3.8-flash → gemini-3.5-flash → gemini-2.5-flash, Claude claude-sonnet-4-5. Список в меню: gemini-4-hydrogen, gemini-3.8-flash, gemini-3.5-flash, gemini-2.5-flash; claude-sonnet-4-5, claude-haiku-5-5, claude-sonnet-5-5, claude-opus-5-5; пункт m позволяет ввести своё имя.
- generate_ai_analysis.py: gemini_chain() и claude_model() читают models из расписания; мышление low для gemini-3.x-flash, для остальных по умолчанию.
- Модель Gemini для канала задаётся отдельно (weather_tg_ai.py, smart_call), меню на неё не влияет.
- Обновить меню на телефоне: заменить scripts/ai_schedule.py в Termux (git pull или `curl -o scripts/ai_schedule.py https://raw.githubusercontent.com/ruslan591/weather-_Odessa/main/scripts/ai_schedule.py`).

## Находки 2026-11-28
- Генерация 08:04 (06:04 UTC) 28.11 была по триггеру `model:2026-11-28T06:04:ICON EU`, provider gemini, модель gemini-3.8-flash. В репозитории и на VPS расписание: точка Вт 12:05 UTC [gemini] и триггер ICON EU [gemini]. Последний коммит data/ai_schedule.json в репозитории 2026-09-22: вчерашнее отключение пользователя в репозиторий не попало (причина на телефоне не установлена; скрипт push_file_via_api.py требует GH_DISPATCH_TOKEN в .env и при ошибке только печатает «✗ Ошибка публикации»). Расписание я не менял (файл ведёт человек, 16.09 уже был откат чужого изменения).
- Открыто: [ ] пользователь решает, очищать ли точку и триггер (я могу сделать) и проверить вывод push на телефоне.
