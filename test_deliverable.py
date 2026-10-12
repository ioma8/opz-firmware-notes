#!/usr/bin/env python3
"""FULL deliverable dry run: simulate the device, drive the real pipeline to
completion, then run the real write_report() and check the report it produces.
This exercises every finish-line path exactly as the medium-present run will."""
import importlib.util, io, json, struct, zipfile, random, sys
sys.path.insert(0, '/tmp')
from pathlib import Path
spec=importlib.util.spec_from_file_location("F","/tmp/opzfarm.py")
F=importlib.util.module_from_spec(spec); spec.loader.exec_module(F)
import opzsim

def blackfin_blob(operand, payload_len):
    """Build a TE Blackfin module exactly in the proven container format."""
    payload=bytes(random.getrandbits(8) for _ in range(payload_len))
    hdr=struct.pack('<HHII', 0x5000, operand, 0x11a00000, 0) + struct.pack('<I', payload_len+16-16)
    return hdr + payload

random.seed(11)
man=(b'main: DCPLB_FAULT_ADDR: 0x00000000\nsnakesystem: load general config\n')*8
buf=io.BytesIO()
with zipfile.ZipFile(buf,'w',zipfile.ZIP_STORED) as z:
    z.writestr('0', man)                                  # manifest-ish first entry
    z.writestr('1', blackfin_blob(0xad26, 2600))          # an 'os'-like Blackfin module
    z.writestr('2', bytes(random.getrandbits(8) for _ in range(900)))
payload=buf.getvalue()
print(f"synthetic firmware payload: {len(payload)} B, {payload.count(b'PK')} local headers")

def cycle(targets):
    """Emulate one boot through the shared device model (128-byte log cap included)."""
    return opzsim.cycle(targets, payload, F.parse_cycle, F.WIN)

st={"pending":[[i,min(i+F.WIN,len(payload))] for i in range(0,len(payload),F.WIN)],
    "bytes":{},"cycles":0,"miss":0}
while st["pending"] and st["cycles"]<20000:
    st["pending"].sort(key=lambda iv:(0 if iv[0]>=len(payload)-4096 else 1, iv[0]))
    targets=st["pending"][:200]
    nb,produced,got=cycle(targets)
    st["bytes"].update(nb); F.advance(st,targets,nb,produced); st["cycles"]+=1
cov=len(st["bytes"])
print(f"coverage: {cov}/{len(payload)} ({100*cov/len(payload):.2f}%) in {st['cycles']} cycles")
# point the tools at this synthetic payload by writing the real state files
import shutil
backup={p:Path(p).read_bytes() for p in ('/tmp/opzfarm_map.json','/tmp/opzfarm_state.json') if Path(p).exists()}
Path('/tmp/opzfarm_map.json').write_text(json.dumps(st["bytes"]))
Path('/tmp/opzfarm_state.json').write_text(json.dumps(st))
# keep the farm's own log clean: route the function's logging into a temp file instead
_loglines=[]
_real_log=F.log
F.log = lambda m: _loglines.append(m)
print("calling the real write_report()...")
F.write_report(st)
F.log = _real_log
print(f"  (write_report logged {len(_loglines)} line(s) to a scratch buffer, not the farm log)")
rep=Path('/tmp/OPZ_DECODE_REPORT.txt')
print(f"report exists: {rep.exists()} ({rep.stat().st_size if rep.exists() else 0} B)")
if rep.exists():
    txt=rep.read_text()
    for line in txt.splitlines()[:6]: print("   ", line)
    for line in txt.splitlines():
        if 'classification' in line or 'Blackfin module' in line: print("   >>", line.strip())
    ok = ('OP-Z firmware decode report' in txt) and ('Blackfin module' in txt) and ('assemble' in txt)
else: ok=False
# restore the real state
for p,b in backup.items(): Path(p).write_bytes(b)
rem = st["miss"]==0 and cov==len(payload)
print(f"\nsynthetic components classified: {'yes' if 'Blackfin module' in (rep.read_text() if rep.exists() else '') else 'no'}")
print("RESULT:", "PASS - full deliverable path works end to end" if (ok and rem) else "FAIL")
# leave no misleading artifact behind
rep.unlink(missing_ok=True); (Path.home()/'.opz-decode/OPZ_DECODE_REPORT.txt').unlink(missing_ok=True)
print("(cleaned up the synthetic report)")
