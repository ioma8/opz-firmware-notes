#!/usr/bin/env python3
"""opzasm.py - a partial assembler for the Blackfin+ subset an OP-Z engine needs.

There is no Blackfin+ toolchain on this machine and Ghidra's SLEIGH assembler does not work for
this module (doc `09` §9.5), so engine code has to be encoded here. Every encoding in this file is
transcribed from the processor module's own SLEIGH source
(Ghidra/Extensions/Ghidra-BlackFinPlus/data/languages/includes), whose per-instruction files carry
the bit-field diagrams, and each emitted form is checked against bytes taken out of the factory
engines (`engines-official/*.engine`) -- see SELFTEST.

Verified so far: 16-bit register move, 16-bit add/subtract, post-increment load and store,
LINK/UNLINK/RTS, short jumps, the 32-bit multiply, conditional branches, and both immediate
loads (7-bit and the 8-byte 32-bit form). That is the whole set the DSP needs. NOT yet implemented: displacement load/store
(`[P3 + 0xc] = R2`) and pointer-plus-immediate, both of which the engine design avoids: state is
walked with post-increment and a pointer copy (`P3 = P4`) instead. Everything else raises
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


def ldst(ptr, reg, store=False, sz=0, aop=0, z=0):
    """`[P++] = R` / `R = [P++]` and friends (16-bit LdSt, 18-LdSt.sinc).

    sz 0/1/2 = 32/16/8 bit, aop 0 = [P++], 1 = [P--], 2 = [P], z 0 = data reg,
    store selects the lsW bit.
    """
    w = (0x9 << 12) | (sz << 10) | ((1 if store else 0) << 9) | (aop << 7) | (z << 6)
    w |= (P_REGS.index(ptr) & 7) << 3
    w |= D_REGS.index(reg) & 7
    return _u16(w)


def link(frame_bytes):
    """LINK n. The frame field is in WORDS: LINK 0x78 encodes 0x1E."""
    if frame_bytes % 4:
        raise Unsupported("frame size not a multiple of 4")
    return _u16(0xE800, frame_bytes // 4)


def unlink():
    return _u16(0xE801)


def rts():
    return _u16(0x0010)


def jump_s(here, target):
    """JUMP.S: 12-bit signed offset in half-words, relative to the instruction."""
    off = (target - here) // 2
    if not -0x800 <= off <= 0x7FF or (target - here) % 2:
        raise Unsupported("jump out of range or misaligned")
    return _u16(0x2000 | (off & 0xFFF))


def mul32(dst, src0, src1, variant=0xCA31):
    """`Rd = Rs0 * Rs1 (T)` - 32-bit multiply (Dsp32Mult, 26-Dsp32Mult.sinc).

    The second half is fully solved against real code: h2 = 0x2000 | dst<<6 | src0<<3 | src1.
    The first half carries the modifier set; two variants appear in the factory engines for the
    same displayed `(T)` form (0xca31 and 0xc231), differing only in bit 11, which is an
    allocation detail the disassembly does not show. The common one is the default here.
    """
    h2 = 0x2000 | ((D_REGS.index(dst) & 7) << 6) | ((D_REGS.index(src0) & 7) << 3) | (D_REGS.index(src1) & 7)
    return _u16(variant, h2)


def brcc(here, target, cond=True, bp=False):
    """`if CC JUMP` / `if !CC JUMP` (16-bit BrCC, 09-BrCC.sinc).

    sig 0x1, T@11 (1 = CC), B@10 (the (BP) predicate), 10-bit half-word offset
    relative to the instruction itself.
    """
    off = (target - here) // 2
    if not -0x200 <= off <= 0x1FF or (target - here) % 2:
        raise Unsupported("branch out of range or misaligned")
    w = 0x1000 | ((1 if cond else 0) << 11) | ((1 if bp else 0) << 10)
    return _u16(w | (off & 0x3FF))


def ldimm7(dst, value, preg=False):
    """`Rd = imm7 (X)`, sign-extended (16-bit CompI2op, 16-CompI2op.sinc)."""
    if not -64 <= value <= 63:
        raise Unsupported(f"{value} does not fit the 7-bit signed immediate")
    regs = P_REGS if preg else D_REGS
    w = (0x6 << 12) | ((1 if preg else 0) << 11) | ((0 << 10)) | ((value & 0x7F) << 3)
    return _u16(w | (regs.index(dst) & 7))


def ldimm32(dst, value):
    """`Rd = imm32 (X)` - an EIGHT-byte instruction (LdImm, instr64/38-LdImm.sinc).

    Four half-words: a fixed 0xDA00|reg header, the immediate's high half, its low half, and a
    zero dummy word. Reading only four bytes of this form is what made the immediate look
    half-encoded earlier; the display hides the length.
    """
    v = value & 0xFFFFFFFF
    return _u16(0xDA00 | (D_REGS.index(dst) & 7), (v >> 16) & 0xFFFF, v & 0xFFFF, 0)


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
    ("[P4++] = R0", lambda: ldst("P4", "R0", store=True), bytes.fromhex("2092"), "chord render 0x81be28ba"),
    ("R2 = [P0++]", lambda: ldst("P0", "R2"), bytes.fromhex("0290"), "volt render 0x81bf0346"),
    ("R4 = [P0++]", lambda: ldst("P0", "R4"), bytes.fromhex("0490"), "volt render 0x81bf0364"),
    ("UNLINK", unlink, bytes.fromhex("01e8"), "volt render 0x81bf06f6"),
    ("RTS", rts, bytes.fromhex("1000"), "volt render 0x81bf06fa"),
    ("JUMP.S +0x578", lambda: jump_s(0x81bf017a, 0x81bf06f2), bytes.fromhex("bc22"), "volt render 0x81bf017a"),
    ("LINK 0x78", lambda: link(0x78), bytes.fromhex("00e81e00"), "volt render prologue 0x81bf0158"),
    ("R3 = R3 * R3 (T)", lambda: mul32("R3", "R3", "R3"), bytes.fromhex("31cadb20"), "volt render 0x81bf01c4"),
    ("R6 = R4 * R6 (T)", lambda: mul32("R6", "R4", "R6"), bytes.fromhex("31caa621"), "volt render 0x81bf034a"),
    ("R0 = R4 * R2 (T)", lambda: mul32("R0", "R4", "R2"), bytes.fromhex("31ca2220"), "volt render 0x81bf0314"),
    ("R2 = R7 * R5 (T)", lambda: mul32("R2", "R7", "R5"), bytes.fromhex("31cabd20"), "volt render 0x81bf0424"),
    ("if !CC JUMP +4 (BP)", lambda: brcc(0x81bf0178, 0x81bf017c, cond=False, bp=True), bytes.fromhex("0214"), "volt render 0x81bf0178"),
    ("R2 = 0x20", lambda: ldimm7("R2", 0x20), bytes.fromhex("0261"), "chord onNoteOn 0x81be29c6"),
    ("R1 = 0", lambda: ldimm7("R1", 0), bytes.fromhex("0160"), "chord onNoteOn 0x81be29c4"),
    ("R2 = 0x7fffffff", lambda: ldimm32("R2", 0x7FFFFFFF), bytes.fromhex("02daff7fffff0000"[:16]), "volt render 0x81bf0188"),
    ("R3 = 0x1020408", lambda: ldimm32("R3", 0x01020408), bytes.fromhex("03da020108040000"), "volt render 0x81bf02b8"),
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
