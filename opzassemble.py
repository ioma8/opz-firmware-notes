#!/usr/bin/env python3
import json, sys, zipfile, io
from pathlib import Path
m=json.loads(Path('/tmp/opzfarm_map.json').read_text()) if Path('/tmp/opzfarm_map.json').exists() else {}
import struct
def _zfw_len():
    for c in ('/Users/jakubkolcar/projects/customs/opz-firmware-notes/z_firmware_1_2_45.zfw',
              '/tmp/opzuv/../../Users/jakubkolcar/projects/customs/opz-firmware-notes/z_firmware_1_2_45.zfw'):
        try:
            from pathlib import Path as _P
            d=_P(c).read_bytes()[:0x84]
            if len(d)>=0x84 and d[0x04]==0xff:
                return struct.unpack_from('<I', d, 0x80)[0]
        except Exception: pass
    return 1490575
LEN=_zfw_len()
buf=bytearray(b'\x00'*LEN); known=bytearray(LEN); have=0
for k,v in m.items():
    i=int(k)
    if 0<=i<LEN: buf[i]=v; known[i]=1; have+=1
out=Path('/tmp/opzfarm_payload.bin'); out.write_bytes(bytes(buf))
# A byte-for-byte mask of what was actually OBSERVED.  Without it, an unknown
# offset is indistinguishable from an observed 0x00, and printing header fields
# from that invented buffer is exactly how the pre-review notes concluded the
# archive's first entry had an empty name (66.4).
Path('/tmp/opzfarm_known.bin').write_bytes(bytes(known))
print(f"known {have}/{LEN} bytes ({100*have/LEN:.2f}%) -> {out} (+ /tmp/opzfarm_known.bin)")


def _all_known(off, n):
    return 0 <= off and off + n <= LEN and all(known[off:off+n])


def _fld(off, n, fmt):
    """Format a header field, or say 'unknown' rather than reading invented zeros."""
    return fmt % int.from_bytes(bytes(buf[off:off+n]), 'little') if _all_known(off, n) else 'unknown'
# contiguous-run stats
runs=[]; start=None
for i in range(LEN):
    if str(i) in m:
        if start is None: start=i
    else:
        if start is not None: runs.append((start,i)); start=None
if start is not None: runs.append((start,LEN))
runs.sort(key=lambda r:-(r[1]-r[0]))
print("longest contiguous known runs:", runs[:5])
# try to parse the head as a zip if enough is known
head=bytes(buf[:4096])
if head[:4]==b'PK\x03\x04':
    print("head is a zip local header: version=%s flags=%s method=%s csize=%s usize=%s namelen=%s extralen=%s"%(
        _fld(4,2,'%d'), _fld(6,2,'0x%04x'), _fld(8,2,'%d'), _fld(18,4,'%d'), _fld(22,4,'%d'),
        _fld(26,2,'%d'), _fld(28,2,'%d')))

# ---- structural validation -------------------------------------------------
# Byte coverage alone cannot prove the map is RIGHT, and a desync (a misparsed
# leak shifting every later offset) would still reach 99%.  A zip has to satisfy a
# strict chain, so walking it is a real check on the assembled payload:
#   PK\x03\x04 ... -> PK\x03\x04 ... -> PK\x01\x02 ... -> PK\x05\x06
# with each local header's sizes deciding where the next record must begin.
LAST_ENTRIES = []


def zip_walk(buf):
    n = len(buf); off = 0; entries = 0; cdrecs = 0
    LAST_ENTRIES.clear()
    if n < 22 or buf[:4] != b'PK\x03\x04':
        return False, 0, 0, 'payload does not start with a local file header'
    while off < n:
        sig = bytes(buf[off:off+4])
        if sig == b'PK\x03\x04':
            if off + 30 > n: return False, entries, off, 'truncated local header'
            flags  = int.from_bytes(buf[off+6:off+8],   'little')
            method = int.from_bytes(buf[off+8:off+10],  'little')
            csize  = int.from_bytes(buf[off+18:off+22], 'little')
            usize  = int.from_bytes(buf[off+22:off+26], 'little')
            nlen   = int.from_bytes(buf[off+26:off+28], 'little')
            elen   = int.from_bytes(buf[off+28:off+30], 'little')
            # An entry MAY have a name.  The pre-review validator rejected any
            # nonempty name as 'archive is nameless' -- it asserted the conclusion
            # it was supposed to test, so it could not validate an ordinary zip at
            # all (66.4).  Only the chain is checked here.
            if csize == 0 and usize == 0 and (flags & 0x08):
                return False, entries, off, ('entry uses a data descriptor: its sizes live in the central '
                                             'directory, so the walk cannot chain from the local header')
            nxt = off + 30 + nlen + elen + (csize or usize)
            if nxt <= off or nxt > n: return False, entries, off, 'local header size runs past the payload'
            LAST_ENTRIES.append({'name': bytes(buf[off+30:off+30+nlen]).decode('latin1'),
                                 'method': method, 'csize': csize, 'usize': usize,
                                 'off': off, 'flags': flags})
            entries += 1; off = nxt; continue
        if sig == b'PK\x01\x02':
            if off + 46 > n: return False, entries, off, 'truncated central directory record'
            nlen = int.from_bytes(buf[off+28:off+30], 'little')
            elen = int.from_bytes(buf[off+30:off+32], 'little')
            clen = int.from_bytes(buf[off+32:off+34], 'little')
            lho = int.from_bytes(buf[off+42:off+46], 'little')
            if lho >= n or bytes(buf[lho:lho+4]) != b'PK\x03\x04':
                return False, entries, off, f'central directory record points at {lho}, not a local header'
            nxt = off + 46 + nlen + elen + clen
            if nxt <= off or nxt > n: return False, entries, off, 'central directory record runs past the payload'
            cdrecs += 1; off = nxt; continue
        if sig == b'PK\x05\x06':
            if off + 22 > n: return False, entries, off, 'truncated EOCD'
            cd_n = int.from_bytes(buf[off+10:off+12], 'little')
            cd_size = int.from_bytes(buf[off+12:off+16], 'little')
            cd_off = int.from_bytes(buf[off+16:off+20], 'little')
            comment = int.from_bytes(buf[off+20:off+22], 'little')
            if off + 22 + comment != n: return False, entries, off, 'EOCD is not at the end of the payload'
            if cd_off + cd_size != off: return False, entries, off, 'central directory does not abut the EOCD'
            if cdrecs != entries: return False, entries, off, f'{entries} local headers but {cdrecs} central directory records'
            if cd_n != entries: return False, entries, off, f'EOCD says {cd_n} entries, the walk found {entries}'
            return True, entries, off, f'{entries} entries, EOCD at {off}'
        return False, entries, off, f'expected a zip signature at {off}, found {sig!r}'
    return False, entries, off, 'ran off the end without an EOCD'

_ok,_n,_off,_why = zip_walk(bytes(buf))
print("ZIPWALK: " + ("OK (" + _why + ")" if _ok else f"FAIL at {_off} ({_why})"))
if _ok:
    for e in LAST_ENTRIES:
        print(f"ZIPENTRY: {e['name']!r} method={e['method']} csize={e['csize']} usize={e['usize']} "
              f"off={e['off']} flags=0x{e['flags']:04x}")
