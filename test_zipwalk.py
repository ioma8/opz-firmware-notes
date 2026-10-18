#!/usr/bin/env python3
"""Self-check for opzassemble.zip_walk: it must accept a valid archive whether or not
its entries carry names (the pre-review validator rejected ANY name as 'archive is
nameless', i.e. it asserted the conclusion it was meant to test -- 66.4), recover the
entry names, and report the exact offset where a corrupted one stops chaining."""
import contextlib, importlib.util, io, struct, sys, zlib
spec = importlib.util.spec_from_file_location("A", "/Users/jakubkolcar/projects/customs/opz-firmware-notes/opzassemble.py")
A = importlib.util.module_from_spec(spec)
_sink = io.StringIO()
with contextlib.redirect_stdout(_sink):    # importing runs main(); keep its output out of the way
    spec.loader.exec_module(A)


def zip_with(entries, method=0):
    """A zip whose entries are (name, payload) pairs; name may be b''."""
    lh, cd, off = b'', b'', 0
    for name, p in entries:
        crc = zlib.crc32(p)
        h = struct.pack('<4sHHHHHIIIHH', b'PK\x03\x04', 20, 0x1ec0, method, 0, 0,
                        crc, len(p), len(p), len(name), 0) + name
        cd += struct.pack('<4sHHHHHHIIIHHHHHII', b'PK\x01\x02', 20, 20, 0x1ec0, method, 0, 0,
                          crc, len(p), len(p), len(name), 0, 0, 0, 0, 0, off) + name
        lh += h + p
        off += len(h) + len(p)
    eocd = struct.pack('<4sHHHHIIH', b'PK\x05\x06', 0, 0, len(entries), len(entries),
                       len(cd), len(lh), 0)
    return lh + cd + eocd


def nameless_zip(payloads=(b'hello world',), method=0):
    """A zip whose entries all have a zero-length name, like the firmware archive
    was ASSUMED to be.  Still legal, so it must keep working."""
    return zip_with([(b'', p) for p in payloads], method)


checks = []
ok, n, off, why = A.zip_walk(nameless_zip())
checks.append((ok and n == 1 and 'EOCD' in why, f'one-entry archive accepted: ok={ok} n={n} {why}'))

ok2, n2, _, why2 = A.zip_walk(nameless_zip((b'AAAA', b'BBBBBB', b'')))
checks.append((ok2 and n2 == 3, f'three-entry archive accepted: ok={ok2} n={n2} {why2}'))

okg, _, _, _ = A.zip_walk(b'\x00' * 100)
checks.append((not okg, 'all-zero payload rejected'))

# a NAMED archive is an ordinary zip and must be accepted (review 2, 66.4)
okn, nn, _, whyn = A.zip_walk(zip_with([(b'os.bin', b'hello world')]))
checks.append((okn and nn == 1, f'named one-entry archive accepted: ok={okn} n={nn} {whyn}'))
okm, nm, _, whym = A.zip_walk(zip_with([(b'os.bin', b'AAAA'), (b'ble.bin', b'BBBBBB')]))
checks.append((okm and nm == 2, f'named two-entry archive accepted: ok={okm} n={nm} {whym}'))
checks.append(([e['name'] for e in A.LAST_ENTRIES] == ['os.bin', 'ble.bin'],
               f"entry names recovered: {[e['name'] for e in A.LAST_ENTRIES]}"))
checks.append(([e['method'] for e in A.LAST_ENTRIES] == [0, 0], 'entry methods recovered'))

# corruption localised: flip the compressed-size field of the local header (offset 18)
bad = bytearray(nameless_zip())
bad[18] ^= 0xff
ok4, _, off4, why4 = A.zip_walk(bytes(bad))
checks.append((not ok4 and off4 == 0, f'corrupt local size field rejected at 0: {why4}'))

# desync localised: corrupt the *second* entry's size, expect the walk to stop at or
# after that header rather than silently accepting a shifted archive
two = nameless_zip((b'AAAA', b'BBBBBB'))
bad2 = bytearray(two)
bad2[34 + 18] ^= 0x40                      # second local header starts at 34
ok5, _, off5, why5 = A.zip_walk(bytes(bad2))
checks.append((not ok5 and off5 >= 34, f'corruption in entry 2 localised at/after 34: off={off5} {why5}'))

# a data-descriptor entry cannot be chained from its local header alone: it must be
# reported as such rather than silently mis-sized
_dd = zip_with([(b'os.bin', b'AAAA')])
bad_dd = bytearray(_dd)
bad_dd[6] |= 0x08; bad_dd[18:22] = b'\x00\x00\x00\x00'; bad_dd[22:26] = b'\x00\x00\x00\x00'
ok6, _, _, why6 = A.zip_walk(bytes(bad_dd))
checks.append((not ok6 and 'data descriptor' in why6, f'data-descriptor entry reported: {why6}'))

# a zero where the EOCD's central-directory size belongs must be caught by the
# cd_off + cd_size == eocd cross-check, not accepted as a valid archive
holed = bytearray(nameless_zip())
holed[-22 + 12] = 0                        # low byte of EOCD cd_size
checks.append((A.zip_walk(bytes(holed))[0] is False,
               'zeroed cd_size field rejected by the EOCD cross-check'))

for c, m in checks:
    print(("  PASS  " if c else "  FAIL  ") + m)
bad_checks = [m for c, m in checks if not c]
print("RESULT:", "PASS" if not bad_checks else "FAIL")
sys.exit(0 if not bad_checks else 1)
