#!/bin/bash
# One-click status of the OP-Z firmware decode. Read-only; changes nothing.
echo "=== OP-Z firmware decode status ==="
python3 - <<'PY'
import json
from pathlib import Path
n=Path('/tmp/opzfarm_state.json')
if not n.exists(): n=Path.home()/'.opz-decode/opzfarm_state.json'
try:
    st=json.loads(n.read_text()); k=len(st['bytes'])
    print(f"  decoded      : {k}/1490575 bytes ({100*k/1490575:.3f}%)")
    print(f"  cycles run   : {st['cycles']}   pending work: {len(st['pending'])}")
except Exception as e: print("  state unreadable:", e)
PY
echo "  update volume: $(ls /Volumes/ | grep -c OP-Z) present"
if ioreg -p IOUSB -w0 2>/dev/null | grep -q "OP_Z"; then echo "  device on USB: yes"; else echo "  device on USB: no (powered off or unplugged)"; fi
echo "  console port : $(ls /dev/cu.usbmodem* 2>/dev/null | head -1 || echo none)"
echo "  background job: $(launchctl print gui/$(id -u)/com.opz.decode 2>/dev/null | grep -c 'state = running') running"
echo "  report       : $(ls -1 /tmp/OPZ_DECODE_REPORT.txt 2>/dev/null || echo 'not yet written')"
echo
if ls /Volumes/ | grep -q OP-Z; then
  echo "Volume present - the decode is running or finishing. Re-run this to watch progress."
elif ioreg -p IOUSB -w0 2>/dev/null | grep -q "OP_Z"; then
  # the unit is on the bus with its medium not presented: a SCSI media-load can fix this
  echo "The OP-Z is on USB but its update medium is not presented."
  echo "Best action: double-click OP-Z-unstick.command (installs the rule once, then the"
  echo "farm re-inserts the medium by itself every cycle). Pressing PLAY also works."
else
  # not on the bus at all: no USB command can reach it, so the SCSI loader cannot help
  echo "The OP-Z is NOT on USB (powered off or unplugged) - no USB command can reach it."
  echo "Action: press PLAY once (or unplug and replug) to power it on."
  echo "A fresh boot re-presents the update medium, and the decode then resumes by itself."
  echo
  echo "If PLAY does not wake it, the battery may be flat: leave it on this USB cable for"
  echo "10-20 minutes to charge, then press PLAY again."
fi
echo; read -n1 -p "press any key to close"
