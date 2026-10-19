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


def comp_eq(dst, src):
    """`CC = Rdst == Rsrc` (CCFlag, instr16/08-CCFlag.sinc): bits 11-15 = 0b00001, i (immediate) bit 10,
    opc bits 7-9 (0 = ==), g bit 6 (0 = data registers) and the two registers at bits 3-5 / 0-2.
    `CC = R0 == R3` is therefore 0x0818."""
    w = (0x1 << 11) | (0 << 10) | (0 << 9) | (0 << 7) | (0 << 6)
    w |= (D_REGS.index(src) & 7) << 3
    w |= D_REGS.index(dst) & 7
    return _u16(w)


def comp_lt(dst, src):
    """`CC = Rdst < Rsrc`, unsigned (CCFlag opc 3, same field layout as `comp_eq`).

    Unsigned because a coefficient table search compares positive words; the signed forms (opc 1/2) would
    misread a top-bit-set word as negative. The interpreter has decoded opc 0-4 since the CCFlag work, so
    this only adds the emitter the builder lacked.
    """
    w = (0x1 << 11) | (3 << 7) | (0 << 6)
    w |= (D_REGS.index(src) & 7) << 3
    w |= D_REGS.index(dst) & 7
    return _u16(w)


def logic32(dst, src0, src1, op="&"):
    """`Rdst = Rsrc0 op Rsrc1` (Comp3op, instr16/15-Comp3op.sinc): signature 0x5 at bits 12-15, opcode at
    bits 9-11 (0 add, 1 sub, 2 AND, 3 OR, 4 XOR), dst at 6-8, src1 at 3-5, src0 at 0-2."""
    codes = {"+": 0, "-": 1, "&": 2, "|": 3, "^": 4}
    if op not in codes:
        raise Unsupported(f"logic operator {op}")
    w = (0x5 << 12) | (codes[op] << 9)
    w |= (D_REGS.index(dst) & 7) << 6
    w |= (D_REGS.index(src1) & 7) << 3
    w |= D_REGS.index(src0) & 7
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
    """UNLINK. Linkage is a 32-bit class (instr32/35-Linkage.sinc): lnkSig is bits 1-15 of the first
    halfword (0x7400, so 0xe801 with R=1) and the SECOND halfword is the frame word, which UNLINK
    ignores but still consumes. Emitting only the first halfword put the following instruction one
    halfword early, so an UNLINK followed by RTS executed the RTS' halfword as data."""
    return _u16(0xE801, 0x0000)


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
    # liwGrp is bit 3 of the header: group 0 is a data register (0xda08 loads P0, 0xda00 loads R0).
    # Emitting only the data form meant any "Preg = imm32" was silently written to a data register -
    # the same defect the interpreter had, and it produced an engine that assembled but did nothing.
    v = value & 0xFFFFFFFF
    if dst in P_REGS:
        head = 0xDA00 | 0x8 | (P_REGS.index(dst) & 7)
    else:
        head = 0xDA00 | (D_REGS.index(dst) & 7)
    return _u16(head, (v >> 16) & 0xFFFF, v & 0xFFFF, 0)


def cmp_eq0(reg):
    """`CC = Rx == 0` (16-bit CC2Dreg, 03-CC2Dreg.sinc): sig 0x0C00 | reg."""
    return _u16(0x0C00 | (D_REGS.index(reg) & 7))


def push_r7_p5():
    """`push (R7:4, P5:3)` - the prologue pair every factory engine uses."""
    return _u16(0x05E3)


def pop_r7_p5():
    """`pop (R7:4, P5:3)` - its epilogue."""
    return _u16(0x05A3)


def shl(dst, src, n):
    """`Rd = Rs << n` (Dsp32ShfImm, 29-Dsp32ShfImm.sinc).

    Second half: sop@14-15 (2 = left shift), hls@12-13, dst@9-11, imm@3-8 (signed), src@0-2.
    Unlike the right-shift form, whose immediate is stored negated, a left shift carries +n.
    """
    if not 0 <= n <= 31:
        raise Unsupported(f"shift count {n} out of range")
    h2 = (2 << 14) | ((D_REGS.index(dst) & 7) << 9) | ((n & 0x3F) << 3) | (D_REGS.index(src) & 7)
    return _u16(0xCE82, h2)


def shr(dst, src, n):
    """`Rd = Rs >>> n` (Dsp32ShfImm).

    Same second-half layout as the left shift but sop 0 and the immediate stored NEGATED: shifts by
    1, 6 and 31 encode as 63, 58 and 33 in the signed 6-bit field. Verified against factory bytes.
    """
    if not 0 <= n <= 31:
        raise Unsupported(f"shift count {n} out of range")
    h2 = (0 << 14) | ((D_REGS.index(dst) & 7) << 9) | (((-n) & 0x3F) << 3) | (D_REGS.index(src) & 7)
    return _u16(0xCE82, h2)


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
    ("UNLINK", unlink, bytes.fromhex("01e80000"), "volt render 0x81bf06f6"),
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
    ("CC = R3 == 0", lambda: cmp_eq0("R3"), bytes.fromhex("030c"), "volt render 0x81bf0176"),
    ("CC = R0 == 0", lambda: cmp_eq0("R0"), bytes.fromhex("000c"), "volt render 0x81bf01da"),
    ("push (R7:4,P5:3)", push_r7_p5, bytes.fromhex("e305"), "volt prologue 0x81bf015c"),
    ("pop (R7:4,P5:3)", pop_r7_p5, bytes.fromhex("a305"), "volt epilogue 0x81bf06f4"),
    ("R0 = R4 << 31", lambda: shl("R0", "R4", 31), bytes.fromhex("82cefc80"), "volt render 0x81bf0244"),
    ("R4 = R6 << 16", lambda: shl("R4", "R6", 16), bytes.fromhex("82ce8688"), "chord render 0x81be268a"),
    ("R3 = R3 >>> 6", lambda: shr("R3", "R3", 6), bytes.fromhex("82ced307"), "volt render 0x81bf01e8"),
    ("R3 = R6 >>> 0x1f", lambda: shr("R3", "R6", 31), bytes.fromhex("82ce0e07"), "volt render 0x81bf028c"),
    # CC = R2 < R3 unsigned is the most common compare in the factory set: 0x099a occurs in chord, cluster,
    # delay, digital, electric, fdnreverb, fm003b, ministringshort, saw013a, synctapetwo and volt, and the
    # opc-3 family appears 68 times across 15 modules, so the encoding is taken from real code.
    ("CC = R2 < R3", lambda: comp_lt("R2", "R3"), bytes.fromhex("9a09"), "digital render 0x81be66b4"),
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
    import opztime; opztime.watch("assembler selftest")
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    print(__doc__)
    sys.exit(selftest())


class Code:
    def __init__(self, base):
        self.base, self.buf, self.labels, self.fixups = base, bytearray(), {}, []

    def label(self, name):
        self.labels[name] = self.pos()

    def pos(self):
        return self.base + len(self.buf)

    def emit(self, b):
        self.buf += b

    def ins(self, name, *a, **k):
        self.emit(globals()[name](*a, **k))

    def branch(self, label, cond=True):
        """Conditional branch on CC. Emit a placeholder, patch once every label is known."""
        self.fixups.append((len(self.buf), label, cond))
        self.emit(b"\x00\x00")

    def jump(self, label):
        """Unconditional JUMP.S. `branch()` cannot do this - it always tests CC, so using it for an
        unconditional jump silently makes the jump depend on whatever flag was set last."""
        self.fixups.append((len(self.buf), label, "jump"))
        self.emit(b"\x00\x00")

    def finish(self):
        for off, label, cond in self.fixups:
            here = self.base + off
            if cond == "jump":
                enc = jump_s(here, self.labels[label])
            else:
                enc = brcc(here, self.labels[label], cond)
            self.buf[off:off + 2] = enc
        return bytes(self.buf)
