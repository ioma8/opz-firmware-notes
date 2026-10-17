#!/usr/bin/env python3
"""opzasm.py - a partial assembler for the Blackfin+ subset an OP-Z engine needs.

There is no Blackfin+ toolchain on this machine and Ghidra's SLEIGH assembler does not work for
this module (doc `09` §9.5), so engine code has to be encoded here. Every encoding in this file is
transcribed from the processor module's own SLEIGH source
(Ghidra/Extensions/Ghidra-BlackFinPlus/data/languages/includes), whose per-instruction files carry
the bit-field diagrams, and each emitted form is checked against bytes taken out of the factory
engines (`engines-official/*.engine`) -- see SELFTEST.

Verified so far: 16-bit register move and 16-bit add/subtract. Everything else raises
NotImplementedError rather than emitting a guess, because a wrong encoding produces an engine that
loads and misbehaves instead of failing.

Encodings, from the diagrams in the SLEIGH source:

  RegMv (16-bit, 11-RegMv.sinc)
    +---+---+---+---|---+---+---+---|---+---+---+---|---+---+---+---+
    | 0 | 0 | 1 | 1 |....gd.....|....gs.....|....dst....|....src....|
    gd: 1 = P destination, 2 = I destination    gs: 0 = R source, 1 = P source, 2 = I source

  Comp3op (16-bit, 15-Comp3op.sinc)
    +---+---+---+---|---+---+---+---|---+---+---+---|---+---+---+---+
    | 0 | 1 | 0 | 1 |....opc....|....dst....|...src1....|...src0....|
    opc: 0 = Rd = src0 + src1, 1 = Rd = src0 - src1

  LdImmHalf (32-bit, 32-LdImmHalf.sinc)   first half:
    | 1 | 1 | 1 | 0 | 0 | 0 | 0 | 1 | z | h | s | grp | reg |
  Dsp32Mult (32-bit, 26-Dsp32Mult.sinc)   first half:
    | 1 | 1 | 0 | 0 | m | 0 | 1 | mmod | mm | p | w1 | op1 |
"""
import sys

D_REGS = ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7")
P_REGS = ("P0", "P1", "P2", "P3", "P4", "P5", "SP", "FP")
I_REGS = ("I0", "I1", "I2", "I3")


class Unsupported(Exception):
    pass


def _u16(*words):
    """Blackfin puts a 32-bit instruction's first half FIRST in memory (little endian)."""
    b = bytearray()
    for w in words:
        b += int(w & 0xFFFF).to_bytes(2, "little")
    return bytes(b)


def regmv(dst, src):
    """`dst = src` for register-to-register moves (16-bit form)."""
    w = 0x3 << 12
    if dst in P_REGS:
        w |= 1 << 9
        w |= (P_REGS.index(dst) & 7) << 3
    elif dst in I_REGS:
        w |= 2 << 9
        w |= (I_REGS.index(dst) & 7) << 3
    else:
        raise Unsupported(f"regmv destination {dst}")
    if src in D_REGS:
        w |= 0 << 6
        w |= D_REGS.index(src) & 7
    elif src in P_REGS:
        w |= 1 << 6
        w |= P_REGS.index(src) & 7
    elif src in I_REGS:
        w |= 2 << 6
        w |= I_REGS.index(src) & 7
    else:
        raise Unsupported(f"regmv source {src}")
    return _u16(w)


def addsub32(dst, src0, src1, op):
    """`dst = src0 op src1` for + and - (16-bit form, no flags)."""
    if op not in ("+", "-"):
        raise Unsupported(f"operator {op}")
    w = (0x5 << 12) | ((0 if op == "+" else 1) << 9)
    w |= (D_REGS.index(dst) & 7) << 6
    w |= (D_REGS.index(src1) & 7) << 3
    w |= D_REGS.index(src0) & 7
    return _u16(w)


# (source text, encoder call, expected bytes as seen in a factory engine)
SELFTEST = [
    ("P5 = R0",    lambda: regmv("P5", "R0"),        bytes.fromhex("2832"), "volt render prologue 0x81bf016a"),
    ("P4 = R0",    lambda: regmv("P4", "R0"),        bytes.fromhex("2032"), "chord render prologue 0x81be2552"),
    ("P1 = FP",    lambda: regmv("P1", "FP"),        bytes.fromhex("4f32"), "volt render 0x81bf0164"),
    ("P3 = P4",    lambda: regmv("P3", "P4"),        bytes.fromhex("5c32"), "volt render 0x81bf0172"),
    ("P0 = R1",    lambda: regmv("P0", "R1"),        bytes.fromhex("0132"), "volt render 0x81bf0190-ish"),
    ("I0 = P1",    lambda: regmv("I0", "P1"),        bytes.fromhex("4134"), "volt render 0x81bf02xx"),
    ("I1 = I0",    lambda: regmv("I1", "I0"),        bytes.fromhex("8834"), "volt render 0x81bf02xx"),
    ("R1 = R7 + R1", lambda: addsub32("R1", "R7", "R1", "+"), bytes.fromhex("4f50"), "volt render 0x81bf04xx"),
    ("R2 = R2 - R6", lambda: addsub32("R2", "R2", "R6", "-"), bytes.fromhex("b252"), "volt render 0x81bf03xx"),
    ("R3 = R3 - R0", lambda: addsub32("R3", "R3", "R0", "-"), bytes.fromhex("c352"), "volt render 0x81bf03xx"),
]


def selftest():
    bad = 0
    for text, fn, expect, where in SELFTEST:
        got = fn()
        ok = got == expect
        bad += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}  {text:16s} got {got.hex()} want {expect.hex()}   ({where})")
    print(f"\n{len(SELFTEST)-bad}/{len(SELFTEST)} encodings match bytes from the factory engines")
    return 1 if bad else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    print(__doc__)
    sys.exit(selftest())
