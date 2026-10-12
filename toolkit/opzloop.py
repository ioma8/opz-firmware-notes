#!/usr/bin/env python3
"""Autonomous OP-Z cycle: stage probe -> eject -> leak -> device self-reboots (successful upgrade) -> repeat.
Windows are taken from a worklist; the payload stays GENUINE so the upgrade succeeds and the unit resets itself."""
import glob, os, subprocess, time, serial, re, json, sys, threading
REPO='/Users/jakubkolcar/projects/customs/opz-firmware-notes'
ZFW=f'{REPO}/z_firmware_1_2_45.zfw'
ZIP_LEN=1490575; HDR=0x400
src=open(ZFW,'rb').read()
LOG='/tmp/opzloop.log'; LEAKS='/tmp/opzloop_leaks.json'
DEADLINE=time.time()+float(os.environ.get('OPZ_MAX_SECS','60'))
def log(m):
    line=f"[{time.strftime('%H:%M:%S')}] {m}"; print(line,flush=True); open(LOG,'a').write(line+"\n")

def craft_namefield(targets):
    """Leak targets while keeping the payload GENUINE so the upgrade succeeds and the unit reboots.
    Chain: name blocks 1 and 2 stay genuine (block 2 carries '.zip'), block 15 stays genuine (payload
    predecessor). Free: block 0 and blocks 3..14.  Block 3's predecessor is the genuine block 2, so its
    plaintext is recovered as leak XOR genuine_C2 XOR payload_predecessor."""
    nm=bytearray(src[0x300:0x400]); iv=bytearray(src[0x70:0x80])
    slots=[0]+list(range(3,15))
    for k,(slot,tb) in enumerate(zip(slots,targets)):
        f=HDR+tb*16
        nm[slot*16:(slot+1)*16]=src[f:f+16]          # target ciphertext
        pred=src[f-16:f]
        if slot==0: iv=bytearray(pred)
        elif slot>=4: nm[(slot-1)*16:slot*16]=pred   # predecessor in the previous (free) block
        # slot==3: block 2 must stay genuine; predecessor recorded separately by the decoder
    p=bytearray(src[:HDR]); p[0x70:0x80]=iv; p[0x300:0x400]=nm
    return bytes(p)+src[HDR:]

def cycle(idx, targets, use_genuine=False):
    VOL=None
    while time.time()<DEADLINE:
        v=glob.glob('/Volumes/OP-Z*')
        if v: VOL=v[0]; break
        time.sleep(1)
    if not VOL: log(f"cycle {idx}: no volume within 180 s"); return False
    for q in glob.glob(VOL+'/*.zfw')+glob.glob(VOL+'/._*'):
        try: os.remove(q)
        except Exception: pass
    data=src if use_genuine else craft_namefield(targets)
    open(VOL+'/z_firmware_probe_000.zfw','wb').write(data)
    for _ in range(3):
        for q in glob.glob(VOL+'/._*'):
            try: os.remove(q)
            except Exception: pass
        time.sleep(0.2)
    log(f"cycle {idx}: staged {len(data)} B, targets={targets}, sidecars={len(glob.glob(VOL+'/._*'))}")
    cap=[]
    def reader():
        try: s=serial.Serial('/dev/cu.usbmodemX3CJN79E1',115200,timeout=1)
        except Exception as e: log(f"  port open failed: {e}"); return
        t=time.time()
        while time.time()-t<200:
            try: d=s.read(4096)
            except Exception: break
            if d: cap.append(d)
        try: s.close()
        except Exception: pass
    th=threading.Thread(target=reader,daemon=True); th.start(); time.sleep(1)
    subprocess.run(['diskutil','eject',VOL],capture_output=True,text=True,timeout=60)
    log("  ejected; waiting for leak")
    while time.time()<DEADLINE-20: time.sleep(2)
    blob=b''.join(cap)
    open(f'/tmp/opzloop_raw_{idx}.bin','wb').write(blob)
    mg=re.search(rb'filename found:', blob); ml=re.search(rb'failed to find \.zip file in (.*?)(?=\xc0\x1e\x04|\x00)', blob, re.S)
    if mg: log("  name check PASSED (upgrade path)")
    if ml:
        leak=bytearray(ml.group(1))
        log(f"  LEAK raw {len(leak)} B: {bytes(leak).hex(' ')[:150]}")
    n_det=len(re.findall(rb'detected encrypted file', blob))
    n_ext=len(re.findall(rb'extract', blob))
    n_upg=len(re.findall(rb'successfully upgraded', blob))
    log("  console: detected=%d extract=%d upgraded=%d"%(n_det,n_ext,n_upg))
    # wait for the medium to come back on its own
    tb=None; t0=time.time()
    while time.time()<DEADLINE and time.time()-t0<240:
        if glob.glob('/Volumes/OP-Z*'): tb=time.time()-t0; break
        time.sleep(2)
    log("  MEDIUM RETURNED after %.0f s (autonomous reboot CONFIRMED)"%tb if tb is not None else "  MEDIUM DID NOT RETURN within 240 s")
    return tb is not None

open(LOG,'a').write("")
log("loop start: cycle 1 = genuine archive (reboot foundation test)")
if cycle(1, [], use_genuine=True):
    log("cycle 2 = crafted probe (leak + reboot in one boot)")
    cycle(2, [100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140, 144, 148])
else:
    log("reboot foundation failed - stopping")
log("loop done")
