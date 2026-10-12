#!/usr/bin/env python3
"""Unit test for the farm's leak parser + interval accounting (review-2 semantics).

Covers the fixes recorded in FIRMWARE_ANALYSIS.md 66.2/66.3/66.5:
  * frames are decoded with their length honoured and 7D escapes undone (the old
    parser copied raw bytes and stopped only on the rare 'C0 2E 04' routing);
  * a probe is tracked ACROSS messages (detected -> leak);
  * a log-buffer-capped frame does NOT invent a terminating NUL byte;
  * a frame that stopped short of the cap DID end on a real NUL, recorded as data;
  * a probe that produced nothing KEEPS its interval instead of advancing by one.
"""
import importlib.util, sys
sys.path.insert(0, '/tmp')
spec = importlib.util.spec_from_file_location("opzfarm", "/tmp/opzfarm.py")
F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)
import opzsim


def window(true_bytes, win=256):
    """Device-side plaintext of a window: the probe's IV mask shifts the first block."""
    b = bytearray(true_bytes[:win]) + bytes(max(0, win - len(true_bytes[:win])))
    for i in range(min(16, len(b))): b[i] ^= 0x01
    return bytes(b)


def cycle_buf(entries):
    """entries = [(probe_index, device_side_window_bytes), ...]"""
    buf = b''
    for i, seg in entries:
        buf += opzsim.probe(i) + opzsim.frame(opzsim.leak_msg(opzsim.leak(seg)))
    return buf


targets = [[0, 5000], [5000, 9000], [9096, 12000]]
ok = True


def chk(c, m):
    global ok
    if not c: print("FAIL:", m); ok = False


# 1. a real NUL past byte 16 ends the leak; the terminator itself is proven data
t0 = b'A' * 20 + b'\x00' + b'tail'
nb, produced, got = F.parse_cycle(cycle_buf([(0, window(t0))]), targets)
chk(produced == {0}, f"produced={produced}")
chk([nb.get(str(i)) for i in range(20)] == [0x41] * 20, "20 leaked bytes")
chk(nb.get('20') == 0x00, "the NUL that stopped the read is 0x00 outside the masked block")
chk('21' not in nb, "nothing is invented past the terminator")
chk(got == 20, f"got={got}")

# 2. a window with no NUL hits the 128-byte log cap: 63 real bytes + the '..' marker
t1 = bytes(0x30 + (i % 0xB0) for i in range(255))
nb1, produced1, got1 = F.parse_cycle(cycle_buf([(0, window(t1))]), targets)
chk([nb1.get(str(i)) for i in range(63)] == list(t1[:63]), "63 capped bytes")
chk('63' not in nb1, "the '..' truncation marker must NOT be recorded as payload")
chk(got1 == 63, f"got={got1}")
chk(F.LAST["truncated"] == 1 and F.LAST["leaks"] == 1 and F.LAST["marker"] == 1,
    f"truncation + marker flagged: {F.LAST}")

# 3. escapes in the frame payload are undone (0x7D/0xC0 inside the masked window)
t2 = bytes([0x7C, 0xC1, 0x41, 0x42])          # masks to 7D C0 40 43 -> escaped on the wire
nb2, _, _ = F.parse_cycle(cycle_buf([(0, window(t2))]), targets)
chk([nb2.get(str(i)) for i in range(4)] == list(t2), f"escape round-trip: {[nb2.get(str(i)) for i in range(4)]}")

# 4. the genuine archive's own read must not be mistaken for a probe leak
gen = opzsim.frame(b'bootdisk: detected encrypted file /z_firmware_z_1_2_45.zfw') + \
      opzsim.frame(opzsim.leak_msg(b'NOT-A-PROBE'))
nb3, produced3, got3 = F.parse_cycle(gen, targets)
chk(produced3 == set() and got3 == 0, f"genuine file leaked something: {produced3}")

# 5. a miss keeps its interval (the old code advanced the start by one and lost the byte)
st = {"pending": [[0, 1000], [1000, 2000]], "bytes": {}, "cycles": 0, "miss": 0}
F.advance(st, [[0, 1000], [1000, 2000]], {"0": 0x41}, {0})
chk(st["miss"] == 1, f"miss counted ({st['miss']})")
chk([1000, 2000] in st["pending"], "a missed interval must be retried, not discarded")
chk([1001, 2000] not in st["pending"], "a missed interval must NOT advance by one")
st2 = {"pending": [[0, 1000]], "bytes": {}, "cycles": 0, "miss": 0}
F.advance(st2, [[0, 1000]], {str(i): 0 for i in range(300)}, {0})
chk([300, 1000] in st2["pending"], f"partial read advanced wrong: {st2['pending']}")

# 6. provenance is recorded per cycle and points at the raw capture
st3 = {"pending": [], "bytes": {}, "cycles": 7, "miss": 0}
F.record_read(st3, targets[:1], {0}, True)
r = st3["reads"][0]
chk(r["cycle"] == 7 and r["masked"] is True and r["targets"] == [[0, 5000]], f"provenance {r}")
chk(r["capture"] == "/tmp/opzcap_cycle0007.bin", f"provenance capture {r['capture']}")

# 7. migration drops what came from unaligned reads and re-queues it aligned
st4 = {"pending": [], "bytes": {str(i): 1 for i in range(0, 20)}, "cycles": 0, "miss": 0}
for i in range(30, 82): st4["bytes"][str(i)] = 1
drop = F.migrate(st4)
chk(drop == 52, f"migration should drop the 52 unaligned bytes, dropped {drop}")
chk(all(int(k) < 20 for k in st4["bytes"]), "aligned bytes survive migration")
chk([16, 82] in st4["pending"], f"dropped range re-queued aligned: {st4['pending']}")

# 8. craft() always snaps to a readable (16-byte) boundary
chk(F.align16(0) == 0 and F.align16(30) == 16 and F.align16(1490319) == 1490304, "align16")
src = F.SRC.read_bytes()
chk(F.craft(7)[0x300:0x400] == src[0x400:0x500], "craft(7) must read the aligned window at 0")

# 9. the IV mask delta is a FREE CHOICE, not a constant (66.13).  Read #2 showed why it
#    matters: a true 0x01 prints as 0x00 under delta 1 and truncates the window.
t3 = bytes([0x41, 0x01, 0x00, 0x42])


def read_with(d):
    F.MASK_DELTA[0] = d
    seg = bytearray(t3) + bytes(252)
    for i in range(16): seg[i] ^= d          # device-side plaintext of this window
    nb4, _, _ = F.parse_cycle(cycle_buf([(0, bytes(seg))]), targets, masked=True)
    return [nb4.get(str(i)) for i in range(4)]


chk(read_with(1)[:2] == [0x41, 0x01] and read_with(1)[2] is None,
    f"delta 1 must truncate on a true 0x01 and recover that byte as 0x01: {read_with(1)}")
chk(read_with(2) == list(t3), f"delta 2 must read the whole block: {read_with(2)}")
F.MASK_DELTA[0] = 1

print("probes leaked", sorted(produced), "bytes", got, "| checks", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
