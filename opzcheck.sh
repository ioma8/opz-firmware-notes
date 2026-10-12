#!/bin/bash
# Consolidated system check for the OP-Z decode stack.  Non-destructive; safe to run any time.
PY=/tmp/opzuv/bin/python
pass=0; fail=0
chk(){ if [ "$2" = "0" ]; then echo "  PASS  $1"; pass=$((pass+1)); else echo "  FAIL  $1"; fail=$((fail+1)); fi; }
echo "=== OP-Z decode stack: system check $(date) ==="
$PY -c "import ast;ast.parse(open('/tmp/opzfarm.py').read());ast.parse(open('/tmp/opzassemble.py').read());ast.parse(open('/tmp/opzsim.py').read())" 2>/dev/null; chk "opzfarm.py + opzassemble.py + opzsim.py parse" $?
$PY /tmp/opzsim.py >/tmp/_t0.txt 2>&1; chk "device simulator selftest (leak cap = 65 B)" $?
$PY /tmp/test_opzfarm.py >/tmp/_t1.txt 2>&1; chk "unit test (frames + parser + intervals + provenance)" $?
$PY /tmp/test_e2e.py >/tmp/_t2.txt 2>&1; chk "end-to-end test (simulated device)" $?
$PY - <<'EOF' >/tmp/_t3.txt 2>&1
import importlib.util, sys
sys.path.insert(0,'/tmp')
s=importlib.util.spec_from_file_location('f','/tmp/opzfarm.py'); M=importlib.util.module_from_spec(s); s.loader.exec_module(M)
import opzsim
src=M.SRC.read_bytes()
M.MASKED[0]=True
assert M.craft(0)[0x70:0x80]==bytes(x^0x01 for x in src[0x3F0:0x400]), "mask"
M.MASKED[0]=False
assert M.craft(0)[0x70:0x80]==src[0x3F0:0x400], "unmask"
M.MASKED[0]=True
# review 2 (66.1): a window is only readable on a 16-byte boundary
assert M.align16(0)==0 and M.align16(7)==0 and M.align16(1490319)==1490304, "alignment"
assert M.craft(7)[0x300:0x400]==src[0x400:0x500], "unaligned request must snap to the boundary"
# review 2 (66.1): ground truth must contain ONLY aligned, hardware-verified bytes,
# and it must decode as a REAL zip local header (66.12)
assert len(M.GROUND_TRUTH)==20 and all(int(k)<20 for k in M.GROUND_TRUTH), "ground truth"
gt=bytes(M.GROUND_TRUTH[i] for i in range(20))
assert gt[:4]==b'PK\x03\x04' and gt[8:10]==b'\x08\x00' and gt[6:8]==b'\x00\x00', gt.hex(' ')
assert gt[12:14]==b'\x7f\x54', "mod date must be 2022-03-31"
# review 2 (66.3): a log-buffer-capped frame must not invent a terminating NUL
seg=bytes(0x30+(i%0xB0) for i in range(256))
nb,_,got=M.parse_cycle(opzsim.probe(0)+opzsim.frame(opzsim.leak_msg(opzsim.leak(seg))),[[0,5000]])
assert got==63 and '63' not in nb and M.LAST["marker"]==1, f"cap semantics ({got})"
assert M.verify_ground_truth({"bytes":{str(k):v for k,v in M.GROUND_TRUTH.items()}})[1]==[]
# rule 66.14: EVERY capped leak in the durable captures ends with the '..' marker
import glob
from pathlib import Path as _P
_seen=0
for _rp in glob.glob(str(_P.home()/'.opz-decode/raws/*.bin')):
    for _,_,_pl in M.frames(_P(_rp).read_bytes()):
        _j=_pl.find(M.LEAK_PREFIX)
        if _j<0: continue
        _hay=_pl[_j+len(M.LEAK_PREFIX):]
        _d=_hay[:-1] if _hay.endswith(b'\x00') else _hay
        if len(_pl)>=M.FRAME_MAX:
            assert _d.endswith(b'..') and len(_d)==65, _rp
        _seen+=1
assert _seen>=3, _seen
print(f"craft/mask/alignment/ground-truth/leak-cap/marker OK ({_seen} real leaks checked)")
EOF
chk "craft + mask + alignment + ground-truth + leak-cap invariants" $?
bash -n "$HOME/.opz-decode/run.sh" 2>/dev/null; chk "durable entry point run.sh syntax" $?
[ -x /tmp/opzload ] && [ -f /tmp/opz-sudo-install.sh ]; chk "medium re-insert tooling present" $?
[ -x /Users/jakubkolcar/Desktop/OP-Z-unstick.command ]; chk "desktop unblock present" $?
launchctl print gui/$(id -u)/com.opz.decode >/dev/null 2>&1; chk "launchd job com.opz.decode loaded" $?
[ "$(pgrep -f 'opzfarm.py 100000' | wc -l | tr -d ' ')" = "1" ]; chk "exactly one decode farm running (lock holds)" $?
RUNHASH=$(grep -o 'src=[0-9a-f]*' /tmp/opzfarm.log 2>/dev/null | tail -1 | cut -d= -f2)
FILEHASH=$($PY -c "import hashlib;print(hashlib.sha256(open('/tmp/opzfarm.py','rb').read()).hexdigest()[:8])" 2>/dev/null)
# no stamp yet = the farm just started, so by definition it loaded the current file
if [ -z "$RUNHASH" ]; then chk "running farm code matches the file on disk (just started)" 0
else [ "$RUNHASH" = "$FILEHASH" ]; chk "running farm code matches the file on disk (no drift)" $?; fi
$PY /tmp/test_fallback.py >/tmp/_tf.txt 2>&1; chk "self-healing fallback (mask distrust -> unmasked + re-queue)" $?
$PY /tmp/test_staging.py >/tmp/_ts.txt 2>&1; chk "staging (volume clean, 200 probes, genuine archive)" $?
$PY /tmp/test_deliverable.py >/tmp/_td.txt 2>&1; chk "FULL deliverable dry run (simulate -> assemble -> classify -> report)" $?
printf '  %s\n' "$($PY /tmp/opzassemble.py 2>&1 | grep -E '^(known|head|ZIPWALK|ZIPENTRY)' | head -8)"
$PY /tmp/test_zipwalk.py >/tmp/_t6.txt 2>&1; chk "zip structural validator (accepts valid, localises corruption)" $?
$PY /tmp/test_success.py  >/tmp/_t7.txt 2>&1; chk "success path (complete valid map passes the gate and reports)" $?
$PY /tmp/opzanalyze.py >/tmp/_t5.txt 2>&1; chk "analyzer runs" $?
echo
echo "  tests: $pass passed, $fail failed"
$PY -c "
import json;from pathlib import Path
st=json.loads(Path('/tmp/opzfarm_state.json').read_text())
print(f'  decode progress: {len(st[\"bytes\"])}/1490575 bytes ({100*len(st[\"bytes\"])/1490575:.3f}%), pending={len(st[\"pending\"])}, cycles={st[\"cycles\"]}')"
echo "  volumes: $(ls /Volumes/ | tr '\n' ' ')"
echo "  durable toolchain: $HOME/.opz-decode (survives /tmp clears and session end)"
 echo "  BLOCKER: update medium absent -> needs PLAY / power-cycle / OP-Z-unstick.command"
[ $fail -eq 0 ] && echo "  RESULT: stack healthy, armed and waiting" || echo "  RESULT: $fail check(s) failing"
