#!/usr/bin/env python3
"""Stage N correctly-crafted probes with ONE eject and count how many reads the device performs."""
import glob, os, subprocess, time, serial, re, threading, sys, json
REPO='/Users/jakubkolcar/projects/customs/opz-firmware-notes'
src=open(f'{REPO}/z_firmware_1_2_45.zfw','rb').read()
ZIP_LEN=1490575; HDR=0x400
N=int(os.environ.get('OPZ_N','8'))
T0=time.time(); LOG='/tmp/opzmulti.log'
def log(m):
    line=f"[{time.strftime('%H:%M:%S')} +{time.time()-T0:4.0f}s] {m}"; print(line,flush=True); open(LOG,'a').write(line+"\n")
open(LOG,'a').write("")
# central-directory windows: the last 2048 bytes of the archive, newest-looking first
offs=[ZIP_LEN-2048+256*i for i in range(N)]
def probe(zipoff, short=False):
    f=HDR+zipoff
    iv=bytearray(src[f-16:f])
    for j in range(16): iv[j]^=0x01
    p=bytearray(src[:HDR]); p[0x70:0x80]=iv; p[0x300:0x400]=src[f:f+256]
    return bytes(p)+b'\0'*1024
VOL=None
for _ in range(30):
    v=glob.glob('/Volumes/OP-Z*')
    if v: VOL=v[0]; break
    time.sleep(1)
if not VOL: log("NO VOLUME"); sys.exit(1)
for q in glob.glob(VOL+'/*.zfw')+glob.glob(VOL+'/._*'):
    try: os.remove(q)
    except Exception: pass
for i,o in enumerate(offs):
    open(VOL+f'/z_firmware_probe_{i:03d}.zfw','wb').write(probe(o))
for _ in range(3):
    for q in glob.glob(VOL+'/._*'):
        try: os.remove(q)
        except Exception: pass
    time.sleep(0.2)
log(f"staged {N} probes, sidecars={len(glob.glob(VOL+'/._*'))}, offsets {offs[0]}..{offs[-1]}")
cap=[]
def reader():
    try: s=serial.Serial('/dev/cu.usbmodemX3CJN79E1',115200,timeout=1)
    except Exception as e: log(f"port: {e}"); return
    t=time.time()
    while time.time()-t<70:
        try: d=s.read(4096)
        except Exception: break
        if d: cap.append(d)
    try: s.close()
    except Exception: pass
th=threading.Thread(target=reader,daemon=True); th.start(); time.sleep(1)
subprocess.run(['diskutil','eject',VOL],capture_output=True,text=True,timeout=60)
log("ejected (single trigger)")
while time.time()-T0<80: time.sleep(2)
blob=b''.join(cap); open('/tmp/opzmulti_raw.bin','wb').write(blob)
names=re.findall(rb'detected encrypted file /([^\x00\r\n]*)', blob)
log(f"READS={len(names)} -> {[n.decode('latin1') for n in names]}")
log("invalid-dir=%d  didn't-find=%d  comparing=%d" % (
    len(re.findall(b'invalid dir',blob)), len(re.findall(b"didn't find firmware file",blob)), len(re.findall(b'comparing',blob))))
for m in re.finditer(rb'detected encrypted file /z_firmware_probe_(\d+)\.zfw.*?failed to find \.zip file in (.*?)(?=\xc0\x1e\x04|\x00)', blob, re.S):
    idx=int(m.group(1)); raw=bytearray(m.group(2))
    for j in range(min(16,len(raw))): raw[j]^=0x01
    log(f"  leak[{idx}] {len(raw)}B {bytes(raw).hex(' ')[:90]}")
