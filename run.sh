#!/bin/bash
# Durable OP-Z decode job: restore the /tmp toolchain (macOS clears /tmp) then run the
# decode farm IN THE FOREGROUND so launchd keep-alive supervises it directly.  The farm
# writes OPZ_DECODE_REPORT.txt itself once the worklist drains.
#
# The restore must be GENERIC: a hardcoded list silently goes stale and then the
# recovery path is missing pieces exactly when it is needed.
H="$HOME/.opz-decode"
for f in "$H"/*.py "$H"/*.sh "$H"/opzload; do
  [ -f "$f" ] && cp -f "$f" "/tmp/$(basename "$f")"
done

# Python: the venv lives in /tmp, so a reboot destroys it.  Prefer the DURABLE copy in
# ~/.opz-decode (symlinked into /tmp so every hardcoded /tmp/opzuv path keeps working),
# then try rebuilding with uv, then any python3 that already has pyserial -- otherwise
# the launchd job would fail on every retry and the decode would never resume.
PY=/tmp/opzuv/bin/python
if ! "$PY" -c 'import serial' 2>/dev/null; then
  echo "python venv unusable at $PY"
  if "$H/opzuv/bin/python" -c 'import serial' 2>/dev/null; then
    rm -rf /tmp/opzuv; ln -sfn "$H/opzuv" /tmp/opzuv
    echo "restored the durable venv $H/opzuv -> /tmp/opzuv"
  elif command -v uv >/dev/null 2>&1; then
    uv venv /tmp/opzuv >/dev/null 2>&1
    uv pip install --python "$PY" pyserial pycryptodome >/dev/null 2>&1
  fi
  if ! "$PY" -c 'import serial' 2>/dev/null; then
    PY=$(command -v python3)
    echo "falling back to $PY"
  fi
fi
"$PY" -c 'import serial' 2>/dev/null || { echo "FATAL: no python with pyserial; cannot run the farm"; exit 1; }
echo "using interpreter $PY"

# state: only restore when /tmp has none (never clobber newer progress)
[ -f "$H/opzfarm_state.json" ] && [ ! -f /tmp/opzfarm_state.json ] && cp -f "$H/opzfarm_state.json" /tmp/opzfarm_state.json
[ -f "$H/opzfarm_map.json" ]   && [ ! -f /tmp/opzfarm_map.json ]   && cp -f "$H/opzfarm_map.json"   /tmp/opzfarm_map.json
SRC="/Users/jakubkolcar/projects/customs/opz-firmware-notes/z_firmware_1_2_45.zfw"
[ -f "$SRC" ] || cp -f "$H/z_firmware_1_2_45.zfw" "$SRC" 2>/dev/null
chmod +x /tmp/*.sh /tmp/opzload 2>/dev/null
exec "$PY" /tmp/opzfarm.py 100000 1
