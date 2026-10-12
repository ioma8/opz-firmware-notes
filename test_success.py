#!/usr/bin/env python3
"""Success-path test: a COMPLETE, structurally valid map must pass the completion gate
and produce the report.  test_deliverable.py calls write_report directly, so it never
exercised the gate's accept branch -- if the zip-walk gate were over-strict the decode
would reach 100% and still never report.

Backs up and restores the real map/state and deletes any report it writes, so the
presence of OPZ_DECODE_REPORT.txt keeps meaning "the real decode finished".
"""
import contextlib, importlib.util, io, json, struct, sys, zlib
from pathlib import Path

spec = importlib.util.spec_from_file_location("F", "/tmp/opzfarm.py")
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
# self-check only: never write into the farm's real evidence log, or a synthetic
# 'report written' line becomes indistinguishable from the real finish (see 62).
F.log = lambda m: None

MAP, STATE = Path('/tmp/opzfarm_map.json'), Path('/tmp/opzfarm_state.json')
REPORTS = [Path('/tmp/OPZ_DECODE_REPORT.txt'),
           Path.home() / '.opz-decode' / 'OPZ_DECODE_REPORT.txt']
_saved = {p: (p.read_bytes() if p.exists() else None) for p in (MAP, STATE)}

ok = True


def chk(c, m):
    global ok
    if not c:
        print("  FAIL", m); ok = False
    return c


def valid_nameless_zip(total):
    """One stored entry sized so the whole archive is exactly `total` bytes."""
    data_len = total - 30 - 46 - 22
    assert data_len > 0
    payload = bytes((i * 7 + 3) & 0xff for i in range(4096)) * (data_len // 4096) + b'\x00' * (data_len % 4096)
    crc = zlib.crc32(payload)
    lh = struct.pack('<4sHHHHHIIIHH', b'PK\x03\x04', 20, 0x1ec0, 0, 0, 0, crc, data_len, data_len, 0, 0)
    cd = struct.pack('<4sHHHHHHIIIHHHHHII', b'PK\x01\x02', 20, 20, 0x1ec0, 0, 0, 0,
                     crc, data_len, data_len, 0, 0, 0, 0, 0, 0, 0)
    eocd = struct.pack('<4sHHHHIIH', b'PK\x05\x06', 0, 0, 1, 1, 46, 30 + data_len, 0)
    return lh + payload + cd + eocd


try:
    payload = valid_nameless_zip(F.ZIP_LEN)
    chk(len(payload) == F.ZIP_LEN, f"fixture is exactly ZIP_LEN ({len(payload)})")
    MAP.write_text(json.dumps({str(i): b for i, b in enumerate(payload)}))
    STATE.write_text(json.dumps({"bytes": {str(i): b for i, b in enumerate(payload)},
                                 "pending": [], "cycles": 1, "miss": 0}))

    okw, detail, off = F.zipwalk_ok()
    chk(okw, f"a complete valid payload passes the walk ({detail})")

    st = json.loads(STATE.read_text())
    cov = len(st["bytes"]) / F.ZIP_LEN
    chk(cov >= F.MIN_COVERAGE, f"coverage {cov*100:.2f}% clears MIN_COVERAGE")

    # the gate's accept branch, exactly as main() writes it
    if cov >= F.MIN_COVERAGE and okw:
        F.write_report(st)
        chk(REPORTS[0].exists(), "report written at 100% coverage with a valid archive")
        if REPORTS[0].exists():
            body = REPORTS[0].read_text()
            chk('ZIPWALK: OK' in body, "report carries the structural verdict")
            chk('100.00%' in body, "report states full coverage")
    else:
        chk(False, "gate refused a complete, valid map (over-strict)")
finally:
    for p, blob in _saved.items():
        if blob is None:
            p.unlink(missing_ok=True)
        else:
            p.write_bytes(blob)
    for p in REPORTS:
        p.unlink(missing_ok=True)

# restored state must still be the real one
real = json.loads(MAP.read_text())
print(f"restored real map: {len(real)} bytes; reports removed: {not any(p.exists() for p in REPORTS)}")
_want = json.loads(_saved[MAP])
chk(real == _want, f"real map restored byte-for-byte ({len(real)} bytes, as before the test)")
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
