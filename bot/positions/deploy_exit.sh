#!/bin/bash
# Выкладка патча 10 (настройки выхода счетов Claude). Запуск на VPS: curl -s https://raw.githubusercontent.com/ruslan591/weather-_Odessa/<SHA>/bot/positions/deploy_exit.sh | bash -s <SHA>
# Шаги: скачать файлы по SHA -> бэкап -> применить патчи на копиях -> проверка компиляции и JS -> установить -> перезапустить сервисы -> проверить API всех счетов -> при сбое откат.
# Откат вручную: bash deploy_exit.sh rollback <каталог бэкапа /opt/trading-bot/backup_patch10_*>
P=/opt/trading-bot/positions; C=/opt/trading-bot/classic
SERV="pos-tracker pos-tracker-afd pos-tracker-regr pos-tracker-combo chan-orders chan-orders-afd chan-orders-regr chan-orders-combo acct-api-afd acct-api-regr acct-api-combo"
restart_all() { for s in $SERV; do systemctl restart $s; done; systemctl restart classicbot; }
restore() { B=$1; cp $B/pos.py $B/chan_orders.py $P/; cp $B/classic_pos_html.py $C/; rm -f $P/exit_cfg.py; restart_all; echo "ROLLED BACK from $B"; }
if [ "$1" = "rollback" ]; then restore "$2"; exit 0; fi
SHA=$1; [ -n "$SHA" ] || { echo "need commit sha"; exit 1; }
RAW=https://raw.githubusercontent.com/ruslan591/weather-_Odessa/$SHA/bot/positions
TS=$(date +%Y%m%d_%H%M%S); B=/opt/trading-bot/backup_patch10_$TS; W=/tmp/p10_$TS; mkdir -p $B $W
for f in exit_cfg.py patch_exit_cfg.py patch_exit_orders.py patch_exit_ui.py; do curl -fsS $RAW/$f -o $W/$f || { echo "FETCH FAIL $f"; exit 1; }; done
cp $P/pos.py $P/chan_orders.py $B/; cp $C/classic_pos_html.py $B/
cp $P/pos.py $P/chan_orders.py $P/sr_stop.py $W/; cp $C/classic_pos_html.py $W/
cd $W
python3 patch_exit_cfg.py $W && python3 patch_exit_orders.py $W && python3 patch_exit_ui.py $W || { echo "PATCH FAIL"; exit 1; }
python3 -m py_compile pos.py chan_orders.py classic_pos_html.py exit_cfg.py || { echo "COMPILE FAIL"; exit 1; }
python3 -c "import re,sys;sys.path.insert(0,'$W');import classic_pos_html as m;open('$W/page.js','w').write(re.findall(r'<script>(.*?)</script>',m.HTML,re.S)[0])" && node --check $W/page.js || { echo "JS FAIL"; exit 1; }
echo "patched and checked; backup $B"
OWN=$(stat -c %U:%G $P/sr_stop.py); OWNC=$(stat -c %U:%G $C/classic_pos_html.py)
cp $W/exit_cfg.py $W/pos.py $W/chan_orders.py $P/; chown $OWN $P/exit_cfg.py $P/pos.py $P/chan_orders.py
cp $W/classic_pos_html.py $C/classic_pos_html.py; chown $OWNC $C/classic_pos_html.py
restart_all
sleep 45
FAIL=0
for s in $SERV classicbot; do a=$(systemctl is-active $s); [ "$a" = "active" ] || { echo "NOT ACTIVE $s: $a"; FAIL=1; }; done
for pt in 18101 18102 18103; do
  curl -s -m 90 localhost:$pt/api/claude | python3 -c "import sys,json;j=json.load(sys.stdin);assert 'exit_cfg' in j and 'error' not in j,list(j)[:6];print('acct $pt ok, open',len(j['open']),'cfg keys',sorted(j['exit_cfg']))" || { echo "API FAIL $pt"; FAIL=1; }
done
sleep 20
curl -s -m 120 localhost:8091/api/claude | python3 -c "import sys,json;j=json.load(sys.stdin);assert 'exit_cfg' in j and 'error' not in j,list(j)[:6];print('panel 8091 ok, open',len(j['open']))" || { echo "PANEL FAIL"; FAIL=1; }
journalctl -u pos-tracker -u chan-orders -u pos-tracker-regr --since "-2 min" --no-pager 2>/dev/null | grep -i "traceback\|error" | tail -5
if [ $FAIL -ne 0 ]; then echo "VERIFY FAILED -> rollback"; restore $B; exit 1; fi
echo "DEPLOY OK $TS"
