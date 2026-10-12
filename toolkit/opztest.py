#!/usr/bin/env python3
"""Decisive test: a probe that leaks payload blocks AND keeps the archive valid (blocks 1,2,15 genuine)."""
import glob, os, subprocess, time, serial, re, threading, json
REPO='/Users/jakubkolcar/projects/customs/opz-firmware-notes'
src=open(f'{REPO}/z_firmware_1_2_45.zfw','rb').read()
HDR=0x400
LOG='/tmp/opztest.log'; T0=time.time()
def log(m):
    line=f"[{time.strftime('%H:%M:%S')} +{time.time()-T0:4.0f}s] {m}"; print(line,flush=True); open(LOG,'a').write(line+"\n")
open(LOG,'a').write("")
TARGETS=list(range(100,113))            # 13 payload blocks to leak
slots=[0]+list(range(3,15))
nm=bytearray(src[0x300:0x400]); iv=bytearray(src[0x70:0x80])
for slot,tb in zip(slots,TARGETS):
    f=HDR+tb*16
    nm[slot*16:(slot+1)*16]=src[f:f+16]
    pred=src[f-16:f]
    if slot==0: iv=bytearray(pred)
    elif slot>=4: nm[(slot-1)*16:slot*16]=pred
p=bytearray(src[:HDR]); p[0x70:0x80]=iv; p[0x300:0x400]=nm
probe=bytes(p)+src[HDR:]
gen=src[0x300:0x400]
log("probe built; name blocks identical to genuine: %s" % [i for i in range(16) if nm[i*16:(i+1)*16]==gen[i*16:(i+1)*16]])
VOL=None
for _ in range(30):
    v=glob.glob('/Volumes/OP-Z*')
    if v: VOL=v[0]; break
    time.sleep(1)
if not VOL: log("NO VOLUME (device not ready)"); raise SystemExit(1)
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
log("staged %d B, sidecars=%d" % (len(probe), len(glob.glob(VOL+'/._*'))))
cap=[]
def reader():
    try: s=serial.Serial('/dev/cu.usbmodemX3CJN79E1',115200,timeout=1)
    except Exception as e: log(f"port: {e}"); return
    t=time.time()
    while time.time()-t<45:
        try: d=s.read(4096)
        except Exception: break
        if d: cap.append(d)
    try: s.close()
    except Exception: pass
th=threading.Thread(target=reader,daemon=True); th.start(); time.sleep(1)
subprocess.run(['diskutil','eject',VOL],capture_output=True,text=True,timeout=60)
log("ejected")
while time.time()-T0<60: time.sleep(2)
blob=b''.join(cap); open('/tmp/opztest_raw.bin','wb').write(blob)
txt=blob.decode('latin1')
log("console markers: detected=%d extract=%d upgraded=%d unsuccessful=%d namefound=%d namefail=%d" % (
    len(re.findall('detected encrypted file',txt)), len(re.findall('extract',txt)),
    len(re.findall('successfully upgraded',txt)), len(re.findall("upgrade was unsuccessful",txt)),
    len(re.findall('filename found',txt)), len(re.findall(r'failed to find \.zip file in',txt))))
m=re.search(rb'(filename found|failed to find \.zip file in) (.*?)(?=\xc0\x1e\x04|\x00)', blob, re.S)
if m:
    raw=bytearray(m.group(2)); log("string (raw) : "+bytes(raw).hex(' ')[:200])
    if m.group(1)==b'failed to find \.zip file in':
        unm=bytearray(raw)
        for j in range(min(16,len(unm))): unm[j]^=0x01
        log("string unmasks first block; printable: "+''.join(chr(c) if 32<=c<127 else '.' for c in unm))
    log("contains .zip in raw print: %s" % (b'.zip' in bytes(raw)))
while time.time()-T0<90:
    if glob.glob('/Volumes/OP-Z*'):
        log("MEDIUM RETURNED -> autonomous reboot CONFIRMED with a leaking probe"); raise SystemExit(0)
    time.sleep(2)
log("medium did NOT return within the budget (probe aborted / no reboot)")
