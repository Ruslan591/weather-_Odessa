#!/data/data/com.termux/files/usr/bin/bash
# usage: git_push_locked.sh BASE_DIR
BASE_DIR="$1"
LOCKDIR="$BASE_DIR/.git_push.lockdir"
MAX_WAIT=60
WAITED=0

while ! mkdir "$LOCKDIR" 2>/dev/null; do
  if [ -d "$LOCKDIR" ]; then
    AGE=$(( $(date +%s) - $(stat -c %Y "$LOCKDIR" 2>/dev/null || echo 0) ))
    if [ "$AGE" -gt 120 ]; then
      rmdir "$LOCKDIR" 2>/dev/null
      continue
    fi
  fi
  WAITED=$((WAITED+1))
  if [ "$WAITED" -ge "$MAX_WAIT" ]; then
    echo "git_push_locked: lock timeout" >&2
    exit 1
  fi
  sleep 1
done

trap 'rmdir "$LOCKDIR" 2>/dev/null' EXIT
git -C "$BASE_DIR" push --force-with-lease
RC=$?
sleep 20
exit $RC
