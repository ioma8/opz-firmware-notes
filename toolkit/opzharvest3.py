#!/usr/bin/env python3
"""Continuous console harvester: raw capture + parsed leaks mapped to probe indices."""
import serial, time, json, re, os
PORT='/dev/cu.usbmodemX3CJN79E1'
RAW='/tmp/opzraw3.bin'; OUT='/tmp/opzleaks.json'
ZFW='/Users/jakubkolcar/projects/customs/opz-firmware-notes/z_firmware_1_2_45.zfw'
src=open(ZFW,'rb').read()
def log(m): open('/tmp/opzharvest3.log','a').write(f"[{time.strftime('%H:%M:%S')}] {m}\n")
log("harvester started")
buf=b''
leaks={}
try: leaks=json.load(open(OUT))
except Exception: pass
ser=serial.Serial(PORT,115200,timeout=1)
t0=time.time()
while time.time()-t0 < 3600:
    d=ser.read(4096)
    if not d: continue
    buf+=d
    open(RAW,'ab').write(d)
    # parse complete log frames: C0 2E 04 len_be32 ... text NUL
    while True:
        i=buf.find(b'\xc0\x1e\x04')
        if i<0:
            buf=buf[-8:]; break
        ln=int.from_bytes(buf[i+3:i+7],'big') if len(buf)>=i+7 else None
        if ln is None: break
        end=i+7+ln
        if len(buf)<end: break
        frame=buf[i+7:end]
        buf=buf[end:]
        m=re.search(rb'failed to find \.zip file in (.*)$', frame, re.S)
        mm=re.search(rb'detected encrypted file /z_firmware_probe_(\d+)\.zfw', frame)
        if mm and m:
            idx=int(mm.group(1)); leak=bytearray(m.group(1))
            for j in range(min(16,len(leak))): leak[j]^=0x01     # undo the 0x01 IV mask
            leaks[str(idx)]={'len':len(leak),'hex':bytes(leak).hex()}
            json.dump(leaks,open(OUT,'w'))
            log(f"window {idx:03d}: {len(leak)} bytes")
log("harvester stopped")
