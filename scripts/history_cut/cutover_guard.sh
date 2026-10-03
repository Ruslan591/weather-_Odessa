#!/bin/bash
# cutover guard: freeze cron -> wait idle -> wait for remote cutover-done ref (or deadline) -> recover clone -> restore cron
LOG=/tmp/cutover.log; ST=/tmp/cutover_state; exec >>"$LOG" 2>&1
REPO=/opt/weather-pipeline/repo; BK=/opt/weather-pipeline/crontab.root.before_cutover
URL=https://github.com/Ruslan591/weather-_Odessa.git
log(){ echo "[$(date -u +%T)] $*"; }
restore(){ if [ -f "$BK" ]; then crontab "$BK" && log "cron RESTORED"; fi; }
trap 'log "trap exit"; restore' EXIT
trap 'exit 1' TERM INT
echo STARTING > $ST; log "start"
crontab -l > "$BK" || { log "cannot read crontab"; echo ABORTED > $ST; exit 1; }
cp "$BK" /opt/weather-pipeline/crontab.root.backup_$(date +%s)
sed -E 's/^([^#].*(run_timed\.sh|dwd_fetch_digitize).*)$/#CUTOVER# \1/' "$BK" | crontab - && log "cron FROZEN"
echo FREEZING > $ST
PAT='run_timed\.sh|vps_pipeline\.py|vps_satellite_pipeline\.py|vps_ai_pipeline\.py|icon_front_very_far|icon_cyclone_case_saver|update_local\.py|git_push_locked|dwd_fetch_digitize'
ok=0; t0=$SECONDS
while [ $((SECONDS-t0)) -lt 480 ]; do
  if ! pgrep -f "$PAT" >/dev/null && [ ! -d $REPO/.git_push.lockdir ]; then ok=$((ok+1)); else ok=0; fi
  [ $ok -ge 3 ] && break; sleep 10
done
if [ $ok -lt 3 ]; then log "ABORT: jobs still running"; pgrep -af "$PAT" | cut -c1-120; echo ABORTED > $ST; exit 1; fi
cd $REPO
git fetch -q origin main --depth 30 --update-shallow; U=$(git rev-list --count origin/main..HEAD 2>/dev/null)
log "unpushed local commits: $U"
if [ "$U" != "0" ]; then log "ABORT: unpushed commits"; echo ABORTED > $ST; exit 1; fi
echo FROZEN > $ST; log "FROZEN idle, waiting for cutover-done"
t1=$SECONDS; done_flag=0
while [ $((SECONDS-t1)) -lt 900 ]; do
  if git ls-remote "$URL" refs/heads/cutover-done 2>/dev/null | grep -q cutover-done; then done_flag=1; break; fi
  sleep 5
done
log "wait finished flag=$done_flag"; echo RECOVERING > $ST
git fetch -q origin --depth 30 --update-shallow +main:refs/remotes/origin/main || { log "fetch failed"; }
git checkout -q -f -B main origin/main; log "checkout rc=$?"
git reflog expire --expire=now --all; git gc -q --prune=now; log "gc rc=$?"
log "HEAD $(git rev-parse --short HEAD) tree $(git rev-parse HEAD^{tree}) commits_visible $(git rev-list --count HEAD)"
git status --short | head -3
echo DONE > $ST; log "done"
