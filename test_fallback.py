#!/usr/bin/env python3
"""Self-healing test: a corrupted ground-truth byte must still be dropped and its
range re-queued, so the map is never poisoned -- and the IV mask must NOT be
auto-flipped any more (review 2, FIRMWARE_ANALYSIS 66.1: the old fallback reacted to
a GROUND_TRUTH set that itself contained misaligned garbage, and the mask is what
makes a NUL inside the first block printable at all)."""
import importlib.util, sys
from pathlib import Path
spec=importlib.util.spec_from_file_location("F","/Users/jakubkolcar/projects/customs/opz-firmware-notes/opzfarm.py")
F=importlib.util.module_from_spec(spec); spec.loader.exec_module(F)
# self-check only: never write into the farm's real evidence log (see FIRMWARE_ANALYSIS 54.3)
F.log=lambda m: None
ok=True
F.MASKED[0]=True
st={"bytes":{str(k):v for k,v in F.GROUND_TRUTH.items()},"pending":[],"cycles":0,"miss":0}
st["bytes"]["0"]^=0xFF
_,bad=F.verify_ground_truth(st)
if not bad: print("FAIL: corruption not detected"); ok=False
if F.handle_mismatch(st,bad)!='retry' or F.MASKED[0] is not True: print("FAIL: mask must not be flipped"); ok=False
if '0' in st['bytes'] or [0,1] not in st['pending']: print("FAIL: bad byte not dropped/re-queued"); ok=False
st2={"bytes":{str(k):v for k,v in F.GROUND_TRUTH.items()},"pending":[],"cycles":0,"miss":0}
st2["bytes"]["0"]^=0xFF
_,bad2=F.verify_ground_truth(st2)
if F.handle_mismatch(st2,bad2)!='retry': print("FAIL: no retry with mask off"); ok=False
if '0' in st2['bytes'] or [0,1] not in st2['pending']: print("FAIL: bad byte not dropped/re-queued (mask off)"); ok=False
if F.MASKED[0] is not True: print("FAIL: mask flipped on the second mismatch"); ok=False
print("RESULT:", "PASS" if ok else "FAIL"); sys.exit(0 if ok else 1)
