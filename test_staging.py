#!/usr/bin/env python3
"""Staging test: the per-cycle volume work (clean -> 200 probes -> genuine archive)
plus the invariant that craft() is always well-formed, including at payload-end offsets."""
import importlib.util, json, shutil, sys, tempfile, time
from pathlib import Path
spec=importlib.util.spec_from_file_location("F","/Users/jakubkolcar/projects/customs/opz-firmware-notes/opzfarm.py")
F=importlib.util.module_from_spec(spec); spec.loader.exec_module(F)
# self-check only: never write into the farm's real evidence log (see FIRMWARE_ANALYSIS 54.3)
F.log=lambda m: None
ok=True
# craft() invariant across the whole payload, especially the end
for idx in (0, 1, 1279, 100000, F.ZIP_LEN-256, F.ZIP_LEN-16, F.ZIP_LEN-1):
    if len(F.craft(idx)) != 1056: print("FAIL craft length at", idx); ok=False
st={"pending":[[19,30],[82,1280],[1282,1490063],[1490130,1490319],[1490323,1490575]],"bytes":{},"cycles":0,"miss":0}
vol=Path(tempfile.mkdtemp(prefix='OPZVOL')); (vol/'systeminfo').mkdir(); (vol/'junk.bin').write_bytes(b'x'*50)
try:
    t0=time.time(); n=F.stage_cycle(vol, st['pending']); dt=time.time()-t0
    probes=sorted(p for p in vol.glob('*.zfw') if 'probe_' in p.name); sz=[p.stat().st_size for p in probes]
    if n!=len(st['pending']) or min(sz)!=1056 or max(sz)!=1056: print("FAIL staging", n, sz); ok=False
    if (vol/'junk.bin').exists() or not (vol/'systeminfo').is_dir(): print("FAIL cleanup"); ok=False
    gen=[p for p in vol.glob('*.zfw') if 'probe_' not in p.name]
    if not gen or gen[0].stat().st_size != 1491600: print("FAIL genuine"); ok=False
    side=[p.name for p in vol.iterdir() if p.name.startswith('._')]
    if side: print(f"FAIL: {len(side)} AppleDouble sidecar(s) left on the volume: {side[:3]}"); ok=False
    print(f"  staging OK: {n} probes @1056 B + genuine 1,491,600 B in {dt:.2f}s")
finally:
    shutil.rmtree(vol, ignore_errors=True)
# per-cycle serial capture must survive a dead handle (USB re-enumeration mid-cycle)
class DeadPort:
    def __init__(self): self.closed=False; self.is_open=True
    def read(self,n): raise OSError(6,'Device not configured')
    def close(self): self.closed=True
class GoodPort:
    def __init__(self): self.sent=False; self.is_open=True
    def read(self,n):
        if not self.sent: self.sent=True; return b'bootdisk: failed to find .zip file in PK\x03\x04\x00'
        return b''
    def close(self): pass
d=DeadPort(); g=GoodPort()
buf,ser=F._read_all(d,2.0,reopen=lambda:g)
if ser is not g or b'failed to find .zip file in' not in buf or not d.closed:
    print("FAIL: capture did not recover from a dead port"); ok=False
else:
    print(f"  serial reconnect OK: recovered {len(buf)} B after the port died")
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
