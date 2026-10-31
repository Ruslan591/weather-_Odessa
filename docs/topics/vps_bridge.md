# Мост GitHub ↔ VPS (как Claude работает с сервером)

Прямого доступа с Claude к VPS нет (свои домены в allowlist недоступны на личных тарифах). Обходной канал: Claude пишет задачу в репозиторий, VPS по cron забирает, выполняет и пишет результат обратно. Исходный код: scripts/vps_github_bridge.py, установка: scripts/vps_github_bridge_install.sh, подробности и история: docs/topics/hosting_migration.md.

## Как пользоваться (Claude, через bash и api.github.com)
1. Записать data/vps_task.json через GitHub Contents API (PUT, нужен sha текущего файла): `{"task_id": "<уникальный>", "cmd": "<shell>", "timeout": <сек>}`.
2. Подождать: cron на VPS срабатывает раз в минуту (flock, один экземпляр). Опрашивать data/vps_result.json раз в ~15 с, пока `task_id` в результате не совпадёт с отправленным. Поля: returncode, stdout, stderr (последние 50 КБ), completed_at_utc.
3. Тот же task_id повторно не выполняется (хранится в /opt/vps-github-bridge/last_task_id.txt) — каждая задача с новым id.

## Правила
- В cmd только ASCII. Кириллица в cmd подвешивает задачу (результат не приходит). Русский текст держать в файлах.
- Мост запускает команду через sh (не bash): скрипты вызывать как `bash file` или `... | bash -s args`.
- Долгие команды: поставить timeout побольше; пока задача идёт, новые не стартуют.
- Токен GitHub на VPS лежит в /etc/vps-github-bridge/token; git-клон мост не использует.

## Классический бот на VPS
- Код: /opt/trading-bot/classic/, сервис classicbot (systemctl restart classicbot). Панели на сервере: 8091 (позиции, пользователю доступна как localhost:18091 через туннель), 8093 (графики, туннель 18093). С самого VPS проверять через localhost:8091 / :8093.
- Клон репозитория на VPS: /opt/weather-pipeline/repo (git fetch работает, pull часто нет — «cannot lock ref»).
- Выкладка файлов: `cd /opt/weather-pipeline/repo && git show origin/main:scripts/deploy_classic_files.sh | bash -s classic_panel.py:<коммит_нового_файла> ...`. Скрипт берёт файл из объектов git, сверяет VPS с родительским коммитом (при расхождении пишет DIVERGED и файл не трогает), делает бэкап в /opt/trading-bot/classic/backup_*, компилирует, перезапускает classicbot и откатывается, если сервис не поднялся.
- Если DIVERGED: сравнить файл на VPS с версиями в git (diff), убедиться, что разница — только ещё не выложенные правки, затем вручную: бэкап, `git show <коммит>:bot/classic/<файл> > файл`, py_compile, затем запуск скрипта для остальных файлов (он перезапустит сервис).
- Проверка после выкладки: `curl -s localhost:8091/api/runs` (после рестарта первый расчёт идёт до минуты), для графика предложения: /api/prop_chart?run=&t_in=&side=.

## Пример (python, с локальной стороны Claude)
Функция run(task_id, cmd, timeout): PUT vps_task.json, затем опрос vps_result.json. Файл-помощник Claude создаёт заново каждую сессию (около 20 строк на urllib).

## Токен моста на VPS (заметка 2026-10-31)
- Файл /etc/vps-github-bridge/token читается построчно, нужна строка вида GITHUB_TOKEN=ghp_... (с префиксом). Голый токен без префикса мост не находит: в /var/log/vps-github-bridge.log RuntimeError «GITHUB_TOKEN не найден». Права файла 600, владелец root.
- Когда токен GitHub истекает, мост молча перестаёт отвечать (последний результат остаётся старым). Обновление делает пользователь из Termux на VPS: printf 'GITHUB_TOKEN=%s\n' 'НОВЫЙ' | sudo tee /etc/vps-github-bridge/token; проверка: ручной запуск sudo /opt/vps-github-bridge/venv/bin/python3 /opt/vps-github-bridge/vps_github_bridge.py (exit=0), затем свежий результат в data/vps_result.json. Запрос к публичному репозиторию без токена тоже даёт 200, для проверки токена брать api.github.com/user.
- Подключение: из Termux ssh -i ~/.ssh/oracle.key ubuntu@130.61.25.212 (на самом VPS этот ключ отсутствует, ssh на сервере с сервера не нужен).
- Долгие скрипты запускать в фоне (nohup ... &) и опрашивать файл результата; команда дольше ~300 секунд обрывается.
