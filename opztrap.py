#!/usr/bin/env python3
"""Watch the mounted OP-Z update volume for the plaintext archive the bootloader writes,
and copy it off the moment it appears (no eject -> the LUN should stay mounted)."""
import glob, os, shutil, time, sys
OUT = os.path.expanduser("~")
LOG = "/tmp/opztrap.log"
def log(m):
    line = f"[{time.strftime('%H:%M:%S')}] {m}"
    print(line, flush=True)
    open(LOG, "a").write(line + "\n")
deadline = time.time() + 900          # 15 min of watching
seen = set()
log("trap armed: watching for the decrypted archive (900 s)")
vols_prev = None
while time.time() < deadline:
    vols = sorted(glob.glob("/Volumes/OP-Z*"))
    if vols != vols_prev:
        log(f"volumes now: {vols if vols else 'NONE'}")
        vols_prev = vols
    if vols:
        for v in vols:
            try:
                entries = sorted(os.listdir(v))
            except Exception as e:
                continue
            for name in entries:
                p = os.path.join(v, name)
                if name.startswith("._") or not os.path.isfile(p):
                    continue
                if name.lower().endswith(".zip") and "firmware" in name.lower() and p not in seen:
                    dst = os.path.join(OUT, f"opz-capture-{time.strftime('%H%M%S')}.zip")
                    try:
                        shutil.copyfile(p, dst)
                        sz = os.path.getsize(dst)
                        seen.add(p)
                        log(f"*** CAPTURED {name} ({os.path.getsize(p)} B) -> {dst}")
                        if sz > 1000:
                            log("*** capture size looks real -- stopping trap")
                            sys.exit(0)
                    except Exception as e:
                        log(f"copy of {name} failed: {e}")
            joined = ",".join(entries)
            if joined not in seen:
                seen.add(joined)
                log(f"listing {v}: {joined[:300]}")
    time.sleep(0.15)
log("trap expired")
