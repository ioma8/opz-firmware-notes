#!/usr/bin/env python3
"""opzengine.py - read, verify, and author OP-Z `.engine` modules.

An OP-Z engine module is *not* a flat image and not an ELF. It is a small list of
load segments, each introduced by a 16-byte header:

    +0x00 u16  flags            bit 15 = last segment, bit 8 = fill instead of copy
    +0x02 u8   checksum         XOR of the other 15 header bytes
    +0x03 u8   0xAD             magic
    +0x04 u32  destination      absolute Blackfin+ address
    +0x08 u32  length
    +0x0c u32  fill value       only used when flags bit 8 is set

followed by `length` bytes of payload. The loader (dlm.cpp) validates the magic,
the checksum and that every destination lies inside the caller's window, copies
each payload to its destination, then flushes the instruction cache.

The first segment is a preamble: it names the destination the module *wants*
(L1 instruction space, 0x11a00000) with length 0, and its fill field carries the
total payload size. Engines are pre-linked to absolute addresses, so a new engine
must target a free window in the same range the factory engines use.

The module's first 56 bytes (first real segment) are its header:

    +0x00 u32 0xfeed0ad1
    +0x04 u32 0xad1facef
    +0x08      five (name pointer, function pointer) pairs -> initModule, init,
               render|renderFX, onNoteOn, onNoteOff   (32-bit each, absolute)

Usage:
    python3 opzengine.py dump    chord.engine
    python3 opzengine.py verify  *.engine        # repack and compare byte-for-byte
    python3 opzengine.py expand  chord.engine    # flat image for a disassembler
"""
import struct, sys, pathlib

MAGIC = 0xAD
FLAG_LAST = 0x8000
FLAG_FILL = 0x0100
MODULE_MAGIC = (0xFEED0AD1, 0xAD1FACEF)
EXPORTS = ("initModule", "init", "render|renderFX", "onNoteOn", "onNoteOff")


def header(flags, dest, length, fill=0):
    b = bytearray(16)
    struct.pack_into("<IIII", b, 0, flags, dest, length, fill)
    b[3] = MAGIC
    chk = 0
    for i in range(16):
        if i != 2:
            chk ^= b[i]
    b[2] = chk
    return bytes(b)


def parse(data):
    """-> [(flags, dest, length, fill, payload)] ; raises ValueError on a bad segment.

    `length` is the field as stored. For a fill segment it is the memory span to
    zero and `payload` is empty; otherwise `payload` is `length` bytes long.
    """
    segs, pos = [], 0
    while pos + 16 <= len(data):
        h = data[pos:pos + 16]
        flags, dest, length, fill = struct.unpack_from("<IIII", h, 0)
        if h[3] != MAGIC:
            raise ValueError(f"segment at 0x{pos:x}: bad magic 0x{h[3]:02x}")
        chk = 0
        for i in range(16):
            if i != 2:
                chk ^= h[i]
        if chk != h[2]:
            raise ValueError(f"segment at 0x{pos:x}: checksum 0x{h[2]:02x} != 0x{chk:02x}")
        # A fill segment (BSS) zeroes `length` bytes of memory and carries no payload.
        payload = b"" if flags & FLAG_FILL else data[pos + 16:pos + 16 + length]
        if len(payload) != (0 if flags & FLAG_FILL else length):
            raise ValueError(f"segment at 0x{pos:x}: truncated payload")
        segs.append((flags, dest, length, fill, payload))
        pos += 16 + len(payload)
        if flags & FLAG_LAST:
            break
    if pos != len(data):
        raise ValueError(f"trailing {len(data)-pos} bytes after the last segment")
    return segs


def pack(segs):
    out = bytearray()
    for i, (flags, dest, length, fill, payload) in enumerate(segs):
        flags = (flags | FLAG_LAST) if i == len(segs) - 1 else (flags & ~FLAG_LAST)
        out += header(flags, dest, length, fill)
        out += payload
    return bytes(out)


def expand(data):
    """-> (base_address, flat bytearray) with every payload at its load address."""
    segs = [s for s in parse(data) if s[4]]
    lo = min(seg[1] for seg in segs)
    hi = max(seg[1] + len(seg[4]) for seg in segs)
    img = bytearray(hi - lo)
    for seg in segs:
        img[seg[1] - lo:seg[1] - lo + len(seg[4])] = seg[4]
    return lo, img


def read_module(data):
    """-> dict describing the module header (magics, exports) or None."""
    segs = [s for s in parse(data) if s[4]]
    if not segs:
        return None
    base, _ = expand(data)
    struct_payload = segs[0][4]
    m1, m2 = struct.unpack_from("<II", struct_payload, 0)
    if (m1, m2) != MODULE_MAGIC:
        return None
    _, img = expand(data)
    exports = []
    for i in range(5):
        name_p, fn_p = struct.unpack_from("<II", struct_payload, 8 + 8 * i)
        name = "?"
        if base <= name_p < base + len(img):
            raw = img[name_p - base:]
            name = bytes(raw[:raw.index(0)]).decode("latin1")
        exports.append((name, fn_p))
    return {"base": base, "exports": exports, "segments": len(segs)}


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1
    cmd, paths = argv[1], [pathlib.Path(p) for p in argv[2:]]
    if cmd == "verify":
        bad = 0
        for p in paths:
            original = p.read_bytes()
            segs = parse(original)
            rebuilt = pack(segs)
            ok = rebuilt == original
            print(f"{p.name:24s} {'OK  ' if ok else 'DIFF'} segments={len(segs):2d} bytes={len(original):6d}")
            bad += 0 if ok else 1
        print(f"\n{len(paths)-bad}/{len(paths)} round-trip clean")
        return 1 if bad else 0
    for p in paths:
        data = p.read_bytes()
        if cmd == "dump":
            mod = read_module(data)
            segs = parse(data)
            print(f"=== {p.name} ({len(data)} B, {len(segs)} segments) ===")
            for flags, dest, length, fill, payload in segs:
                kind = "L1" if dest >> 24 == 0x11 else "DDR" if dest >> 24 == 0x81 else "?"
                bss = " BSS" if flags & FLAG_FILL else ""
                print(f"  seg flags=0x{flags:08x} dest=0x{dest:08x} len={length:5d} "
                      f"file={len(payload):5d} fill=0x{fill:x} last={bool(flags & FLAG_LAST)} {kind}{bss}")
            if mod:
                print(f"  module base 0x{mod['base']:08x}")
                for name, addr in mod["exports"]:
                    print(f"    {name:14s} 0x{addr:08x}")
        elif cmd == "expand":
            lo, img = expand(data)
            out = p.with_name(p.stem + "_flat.bin")
            out.write_bytes(img)
            print(f"{p.name}: 0x{lo:08x}..0x{lo+len(img):08x} ({len(img)} B) -> {out}")
        else:
            print(__doc__)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
