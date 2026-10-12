#!/usr/bin/env python3
"""Autonomous OP-Z cycle using the root SCSI media-load to re-present the medium (no power cycle, no PLAY).
Falls back to waiting when the sudoers rule is absent. Per cycle: remount -> stage probe -> eject -> leak."""
import glob, os, subprocess, time, serial, re, json, threading, sys
REPO='/Users/jakubkolcar/projects/customs/opz-firmware-notes'
src=open(f'{REPO}/z_firmware_1_2_45.zfw','rb').read()
ZIP_LEN=1490575; HDR=0x400
LOG='/tmp/opzloop2.log'; MAP='/tmp/opzloop2_map.json'
MAX_SECS=float(os.environ.get('OPZ_MAX_SECS','60'))
T0=time.time()
def left(): return MAX_SECS-(time.time()-T0)
def log(m):
    line=f"[{time.strftime('%H:%M:%S')} +{time.time()-T0:5.0f}s] {m}"; print(line,flush=True); open(LOG,'a').write(line+"\n")
try: MAPD=json.load(open(MAP))
except Exception: MAPD={}

def media_load():
    """root SCSI START STOP UNIT via /tmp/opzload; returns True if it reports success."""
    for tool in ('/tmp/opzload', os.path.expanduser('~/.opz-decode/opzload')):
        if not os.path.exists(tool): continue
        try:
            r=subprocess.run(['sudo','-n',tool],capture_output=True,text=True,timeout=25)
        except Exception as e:
            log(f"  media-load: could not run sudo -n ({e})"); return False
        out=(r.stdout+r.stderr).strip().splitlines()
        log(f"  media-load rc={r.returncode}: {out[-1][:100] if out else ''}")
        if r.returncode==0: return True
        if 'password' in (r.stderr or '').lower(): return False
    return False

def wait_medium(do_load=True):
    """Wait for the volume; try the root media-load first if allowed."""
    if do_load: media_load()
    while left()>5:
        v=glob.glob('/Volumes/OP-Z*')
        if v: return v[0]
        time.sleep(1)
    return None

def probe_for(block):
    nm=bytearray(src[0x300:0x400]); iv=bytearray(src[0x70:0x80])
    f=HDR+block*16
    nm[0:16]=src[f:f+16]                       # block 0 free: leaks this payload block directly
    iv=bytearray(src[f-16:f])
    p=bytearray(src[:HDR]); p[0x70:0x80]=iv; p[0x300:0x400]=nm
    return bytes(p)+b'\0'*2048                 # tiny payload: abort path (leak), then media-load

def one_cycle(n, block, genuine=False):
    VOL=wait_medium()
    if not VOL: log(f"cycle {n}: no medium (left {left():.0f}s)"); return False
    for q in glob.glob(VOL+'/*.zfw')+glob.glob(VOL+'/._*'):
        try: os.remove(q)
        except Exception: pass
    data=src if genuine else probe_for(block)
    open(VOL+'/z_firmware_probe_000.zfw','wb').write(data)
    for _ in range(3):
        for q in glob.glob(VOL+'/._*'):
            try: os.remove(q)
            except Exception: pass
        time.sleep(0.2)
    log(f"cycle {n}: staged {len(data)}B (block {block}) sidecars={len(glob.glob(VOL+'/._*'))}")
    cap=[]
    def reader():
        try: s=serial.Serial('/dev/cu.usbmodemX3CJN79E1',115200,timeout=1)
        except Exception as e: log(f"  port: {e}"); return
        t=time.time()
        while time.time()-t<25 and left()>5:
            try: d=s.read(4096)
            except Exception: break
            if d: cap.append(d)
        try: s.close()
        except Exception: pass
    th=threading.Thread(target=reader,daemon=True); th.start(); time.sleep(1)
    subprocess.run(['diskutil','eject',VOL],capture_output=True,text=True,timeout=60)
    log("  ejected")
    time.sleep(12)
    blob=b''.join(cap); open(f'/tmp/opzloop2_raw_{n}.bin','wb').write(blob)
    ml=re.search(rb'failed to find \.zip file in (.*?)(?=\xc0\x1e\x04|\x00)', blob, re.S)
    if ml:
        raw=bytearray(ml.group(1))
        unm=bytearray(raw)
        for j in range(min(16,len(unm))): unm[j]^=0x01
        MAPD[str(block)]={'raw':bytes(raw).hex(),'unmasked':bytes(unm).hex()}
        json.dump(MAPD,open(MAP,'w'))
        log(f"  LEAK block {block}: {len(raw)}B  {bytes(unm).hex(' ')[:120]}")
    elif b'filename found' in blob: log("  name check PASSED (no leak)")
    else: log("  no leak line")
    return True

open(LOG,'a').write("")
log(f"loop2 start (budget {MAX_SECS:.0f}s)")
blocks=[int(x) for x in os.environ.get('OPZ_BLOCKS','100,101,102').split(',')]
for i,b in enumerate(blocks,1):
    if left()<15: log(f"budget nearly spent, stopping before cycle {i}"); break
    one_cycle(i,b)
log(f"loop2 end after {time.time()-T0:.0f}s; leaks recorded: {len(MAPD)}")
