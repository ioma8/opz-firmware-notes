#!/usr/bin/env python3
"""Autonomous cycle: stage probe -> eject -> capture leak -> wait for medium to return (no user action)."""
import glob, os, subprocess, time, serial, re, json, sys
REPO='/Users/jakubkolcar/projects/customs/opz-firmware-notes'
ZIP_LEN=1490575; HDR=0x400
X=1490319                      # zip offset of the last 256-byte window (contains the EOCD)
src=open(f'{REPO}/z_firmware_1_2_45.zfw','rb').read()
f=HDR+X
iv=bytearray(src[f-16:f])
for j in range(16): iv[j]^=0x01
p=bytearray(src[:HDR]); p[0x70:0x80]=iv; p[0x300:0x400]=src[f:f+256]
probe=bytes(p)+b'\0'*1024
LOG='/tmp/opzautocycle.log'
def log(m):
    line=f"[{time.strftime('%H:%M:%S')}] {m}"; print(line,flush=True)
    open(LOG,'a').write(line+"\n")
open(LOG,'w').write("")
log(f"probe for zip offset {X} built ({len(probe)} B)")
VOL=None
for _ in range(120):
    v=glob.glob('/Volumes/OP-Z*')
    if v: VOL=v[0]; break
    time.sleep(1)
if not VOL: log("no volume"); sys.exit(1)
log(f"volume {VOL}")
for q in glob.glob(VOL+'/*.zfw')+glob.glob(VOL+'/._*'):
    try: os.remove(q)
    except Exception: pass
open(VOL+'/z_firmware_probe_000.zfw','wb').write(probe)
for _ in range(3):
    for q in glob.glob(VOL+'/._*'):
        try: os.remove(q)
        except Exception: pass
    time.sleep(0.2)
log(f"staged; probes={len(glob.glob(VOL+'/*.zfw'))} sidecars={len(glob.glob(VOL+'/._*'))}")
# capture console in a thread while ejecting
cap=[]
import threading
stop=[False]
def reader():
    try:
        s=serial.Serial('/dev/cu.usbmodemX3CJN79E1',115200,timeout=1)
    except Exception as e:
        log(f"port open failed: {e}"); return
    t=time.time()
    while not stop[0] and time.time()-t<240:
        try:
            d=s.read(4096)
        except Exception:
            log("serial died (device re-enumerated)"); break
        if d: cap.append(d)
    try: s.close()
    except Exception: pass
th=threading.Thread(target=reader,daemon=True); th.start()
time.sleep(1)
r=subprocess.run(['diskutil','eject',VOL],capture_output=True,text=True,timeout=60)
log(f"eject rc={r.returncode}")
# wait for the leak, then keep polling for the medium
medium_back=None; t0=time.time()
while time.time()-t0 < 300:
    if glob.glob('/Volumes/OP-Z*'):
        medium_back=time.time()-t0; break
    time.sleep(2)
stop[0]=True; time.sleep(1)
blob=b''.join(cap)
end=len(blob)
if b'failed to find .zip file in ' in blob:
    print("RAW CONSOLE SAVED:", '/tmp/opzautocycle.raw')
open('/tmp/opzautocycle.raw','wb').write(blob)
m=re.search(rb'failed to find \.zip file in (.*?)(?=\xc0\x1e\x04|\x00)', blob, re.S)
if m:
    leak=bytearray(m.group(1))
    for j in range(min(16,len(leak))): leak[j]^=0x01
    log(f"LEAK at zip {X}: {len(leak)} bytes")
    log("raw      : "+bytes(m.group(1)).hex(' '))
    log("unmasked : "+bytes(leak).hex(' '))
    log("text     : "+bytes(leak).decode('latin1').replace('\n',' ')[:120])
else:
    log("no leak line captured")
log(f"MEDIUM RETURNED AFTER {medium_back:.0f}s" if medium_back is not None else "MEDIUM DID NOT RETURN within 300 s (needs a manual power cycle)")
