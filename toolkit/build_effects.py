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


def build_crush(drop=20):
    """Bit-crush: keep only the top (32 - drop) bits of each sample. That is quantisation, which is
    what a bitcrusher is, so the name is accurate rather than borrowed."""
    c = B.Code(CODE_BASE)
    for nm in ("initModule", "init", "onNoteOn", "onNoteOff"):
        c.label(nm)
        c.emit(A.ldimm7("R0", 0))
        c.emit(A.rts())
    c.label("renderFX")
    c.emit(A.link(0))
    c.emit(A.regmv("P0", "SP"))
    for _ in range(2):
        c.emit(A.ldst("P0", "R0"))
    c.emit(A.ldst("P0", "R1"))
    c.emit(A.ldst("P0", "R2"))
    c.emit(A.regmv("P1", "R1"))
    c.emit(A.regmv("P2", "R2"))
    c.emit(A.push_r7_p5())
    c.emit(A.ldimm32("R7", 64))
    c.emit(A.ldimm7("R6", 1))
    c.label("loop")
    c.emit(A.ldst("P1", "R0"))
    c.emit(A.shr("R0", "R0", drop))
    c.emit(A.shl("R0", "R0", drop))
    c.emit(A.ldst("P2", "R0", store=True))
    c.emit(A.addsub32("R7", "R7", "R6", "-"))
    c.emit(A.cmp_eq0("R7"))
    c.branch("loop", cond=False)
    c.emit(A.pop_r7_p5())
    c.emit(A.unlink())
    c.emit(A.rts())
    return _pack(c, "renderFX")


D_BUF_OFF = 0x40          # delay buffer sits after the small header area in module data
BUF_BYTES = 16384         # 4096 words = 85 ms at 48 kHz, power of two so the wrap is a mask
BUF_MASK = BUF_BYTES - 1
DLY_BYTES = 4096          # read 1024 words (21 ms) behind the write pointer


def build_delay():
    """A real delay line: a power-of-two circular buffer in module data, `out = in + buf[idx-delay]`.

    Every address stays in a DATA register because `addsub32` has no pointer form; a pointer register
    is only used for the access itself (`regmv P4, R3`). Register allocation:
    R0 sample/mix, R1 delay bytes, R2 wrap mask, R3 scratch, R4 buffer base, R5 write index,
    R6 step (4), R7 count*4.
    """
    c = B.Code(CODE_BASE)
    for nm in ("initModule", "init", "onNoteOn", "onNoteOff"):
        c.label(nm)
        c.emit(A.ldimm7("R0", 0))
        c.emit(A.rts())

    c.label("renderFX")
    c.emit(A.link(0))
    c.emit(A.regmv("P0", "SP"))
    for _ in range(2):                                  # saved FP, saved RETS
        c.emit(A.ldst("P0", "R0"))
    c.emit(A.ldst("P0", "R1"))                          # in
    c.emit(A.ldst("P0", "R2"))                          # out
    c.emit(A.regmv("P1", "R1"))
    c.emit(A.regmv("P2", "R2"))
    c.emit(A.push_r7_p5())
    c.emit(A.ldimm32("R7", 256))                        # 64 frames x 4
    c.emit(A.ldimm7("R6", 4))
    c.emit(A.ldimm32("R1", DLY_BYTES))
    c.emit(A.ldimm32("R2", BUF_MASK))
    c.emit(A.ldimm32("R4", DATA_BASE + D_BUF_OFF))
    c.emit(A.ldimm32("P0", DATA_BASE))
    c.emit(A.ldst("P0", "R5", aop=2))                   # R5 = persisted write index

    c.label("loop")
    c.emit(A.ldst("P1", "R0"))                          # R0 = in
    c.emit(A.addsub32("R3", "R4", "R5", "+"))           # write address
    c.emit(A.regmv("P4", "R3"))
    c.emit(A.ldst("P4", "R0", store=True, aop=2))       # buf[idx] = in
    c.emit(A.addsub32("R3", "R5", "R1", "-"))           # idx - delay
    c.emit(A.logic32("R3", "R3", "R2", "&"))            # wrap
    c.emit(A.addsub32("R3", "R4", "R3", "+"))           # read address
    c.emit(A.regmv("P4", "R3"))
    c.emit(A.ldst("P4", "R3", aop=2))                   # R3 = delayed
    c.emit(A.addsub32("R0", "R0", "R3", "+"))           # mix
    c.emit(A.ldst("P2", "R0", store=True))              # out[i]
    c.emit(A.addsub32("R5", "R5", "R6", "+"))           # idx += 4
    c.emit(A.logic32("R5", "R5", "R2", "&"))            # wrap index
    c.emit(A.addsub32("R7", "R7", "R6", "-"))
    c.emit(A.cmp_eq0("R7"))
    c.branch("loop", cond=False)

    c.emit(A.ldimm32("P0", DATA_BASE))
    c.emit(A.ldst("P0", "R5", store=True, aop=2))       # persist the index
    c.emit(A.pop_r7_p5())
    c.emit(A.unlink())
    c.emit(A.rts())
    return _pack(c, "renderFX", data_bytes=D_BUF_OFF + BUF_BYTES)


def _pack(c, render_name, data_bytes=0x40):
    names = {}
    for nm in ("initModule", "init", render_name, "onNoteOn", "onNoteOff"):
        names[nm] = c.pos()
        c.emit(nm.encode() + b"\x00")
    code = c.finish()
    hdr = bytearray()
    hdr += (0xFEED0AD1).to_bytes(4, "little")
    hdr += (0xAD1FACEF).to_bytes(4, "little")
    for nm in ("initModule", "init", render_name, "onNoteOn", "onNoteOff"):
        hdr += names[nm].to_bytes(4, "little")
        hdr += c.labels[nm].to_bytes(4, "little")
    hdr += b"\x00" * 8
    data = bytearray(data_bytes)
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
    for name, builder in (("dist", build_dist), ("crush", build_crush), ("delay", build_delay)):
        raw = builder()
        p = outdir / f"{name}.engine"
        p.write_bytes(raw)
        print(f"  wrote {p} ({len(raw)} B)")


if __name__ == "__main__":
    main(sys.argv)
