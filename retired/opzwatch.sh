#!/bin/bash
# Unstallable supervisor: shell loop only, every step bounded by `timeout`.
# Restarts the farm if absent, logs progress periodically, and finishes by
# assembling + analysing into /tmp/OPZ_DECODE_REPORT.txt.
PY=/tmp/opzuv/bin/python
FARMPAT='opzfarm.py 100000'
STATE=/tmp/opzfarm_state.json
LOG=/tmp/opzdecode.log
REPORT=/tmp/OPZ_DECODE_REPORT.txt
log(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG" >/dev/null; }
log "=== supervisor up (shell) ==="
n=0
while true; do
  if ! pgrep -f "$FARMPAT" >/dev/null 2>&1; then
    log "farm not running -> starting it"
    nohup $PY /tmp/opzfarm.py 100000 200 >> /tmp/opzfarm.out 2>&1 &
    sleep 3
  fi
  n=$((n+1))
  if [ $((n % 4)) -eq 1 ]; then
    $PY - >> "$LOG" 2>&1 <<'PY'
import signal; signal.alarm(20)
import json
from pathlib import Path
try:
    st=json.loads(Path('/tmp/opzfarm_state.json').read_text())
    k=len(st.get('bytes',{})); print(f"[{__import__('time').strftime('%H:%M:%S')}] progress {k}/1490575 ({100*k/1490575:.3f}%) cycles={st.get('cycles')} pending={len(st.get('pending',[]))} misses={st.get('miss')}")
except Exception as e: print("state unreadable:", e)
PY
  fi
  # finished?
  done_flag=$($PY -c "
import signal; signal.alarm(20)
import json
from pathlib import Path
try:
  st=json.loads(Path('/tmp/opzfarm_state.json').read_text())
  print('YES' if (not st.get('pending') and st.get('bytes')) else 'no')
except Exception: print('no')" 2>/dev/null)
  if [ "$done_flag" = "YES" ]; then
    log "worklist empty -> assembling + analysing"
    { echo "OP-Z firmware decode report"; echo "===========================";
      echo "generated $(date)"; echo;
      echo "-- assemble --"; $PY /tmp/opzassemble.py 2>&1;
      echo; echo "-- analyse --"; $PY /tmp/opzanalyze.py 2>&1; } > "$REPORT" 2>&1
    log "report written: $REPORT"
    tail -20 "$REPORT" | while read l; do log "  $l"; done
    break
  fi
  sleep 30
done
log "=== supervisor done ==="
