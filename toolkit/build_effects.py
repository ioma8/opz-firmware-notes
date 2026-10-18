#!/usr/bin/env python3
"""build_effects.py - emit effect engines (renderFX) with the verified assembler.

An effect is handed 64 interleaved stereo frames and must write its result: renderFX(ctx, freq_q16,
state, in, out), with `in` and `out` as stack arguments. For our own ABI that means, after LINK 0,
`FP+8` = in and `FP+0xc` = out; the three loads below discard the two words LINK pushed and the first
stack slot, which is why they are written out rather than hidden in a helper.

Only effects the name actually describes are built. `dist` is gain then wrap, which is distortion;
slots such as chorus/reverb need delay lines and modulation and are deliberately not faked.

Usage:
    python3 toolkit/build_effects.py [outdir]
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_struck as B                              # noqa: E402
import opzasm as A                                    # noqa: E402
import opzengine as E                                 # noqa: E402

MOD_BASE, CODE_BASE, DATA_BASE = B.MOD_BASE, B.CODE_BASE, B.DATA_BASE


def build_dist(gain_shift=2):
    """out[i] = in[i] << gain_shift, left to wrap - a hard, bit-level distortion."""
    c = B.Code(CODE_BASE)

    for nm in ("initModule", "init", "onNoteOn", "onNoteOff"):
        c.label(nm)
        c.emit(A.ldimm7("R0", 0))
        c.emit(A.rts())

    c.label("renderFX")
    c.emit(A.link(0))
    # LINK pushed RETS then FP, so FP+0 and FP+4 are the saved words and FP+8 is the FIRST stack
    # argument. The arguments must therefore be read BEFORE borrowing registers - pushing first moves
    # SP by seven words and every load then lands on the saved registers instead of the arguments.
    c.emit(A.regmv("P0", "SP"))
    for _ in range(2):                                # saved FP, saved RETS
        c.emit(A.ldst("P0", "R0"))
    c.emit(A.ldst("P0", "R1"))                        # R1 = in
    c.emit(A.ldst("P0", "R2"))                        # R2 = out
    c.emit(A.regmv("P1", "R1"))
    c.emit(A.regmv("P2", "R2"))
    c.emit(A.push_r7_p5())
    c.emit(A.ldimm32("R7", 64))
    c.emit(A.ldimm7("R6", 1))
    c.label("loop")
    c.emit(A.ldst("P1", "R0"))
    for _ in range(gain_shift):
        c.emit(A.addsub32("R0", "R0", "R0", "+"))
    c.emit(A.ldst("P2", "R0", store=True))
    c.emit(A.addsub32("R7", "R7", "R6", "-"))
    c.emit(A.cmp_eq0("R7"))
    c.branch("loop", cond=False)
    c.emit(A.pop_r7_p5())
    c.emit(A.unlink())
    c.emit(A.rts())

    names = {}
    for nm in ("initModule", "init", "renderFX", "onNoteOn", "onNoteOff"):
        names[nm] = c.pos()
        c.emit(nm.encode() + b"\x00")
    code = c.finish()

    hdr = bytearray()
    hdr += (0xFEED0AD1).to_bytes(4, "little")
    hdr += (0xAD1FACEF).to_bytes(4, "little")
    for nm in ("initModule", "init", "renderFX", "onNoteOn", "onNoteOff"):
        hdr += names[nm].to_bytes(4, "little")
        hdr += c.labels[nm].to_bytes(4, "little")
    hdr += b"\x00" * 8
    assert len(hdr) == 56

    data = bytearray(0x40)
    payload = len(hdr) + len(code) + len(data)
    segs = [
        (0x5000, 0x11A00000, 0, payload, b""),
        (0x0000, MOD_BASE, len(hdr), 0, bytes(hdr)),
        (0x0000, CODE_BASE, len(code), 0, code),
        (0x0000, DATA_BASE, len(data), 0, bytes(data)),
        (0x8000, 0x11A00000, 0, 0, b""),
    ]
    return E.pack(segs)


def main(argv):
    outdir = pathlib.Path(argv[1] if len(argv) > 1 else "engines-effects")
    outdir.mkdir(parents=True, exist_ok=True)
    raw = build_dist()
    p = outdir / "dist.engine"
    p.write_bytes(raw)
    print(f"  wrote {p} ({len(raw)} B)")


if __name__ == "__main__":
    main(sys.argv)
