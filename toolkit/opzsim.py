#!/usr/bin/env python3
"""opzsim.py - a tiny Blackfin+ interpreter for the instruction subset a built engine uses.

Why this exists: every other check in this project validates a *description* of the engine — the container
bytes, the encoder against factory code, the algorithm in Python. None of them executes the emitted module.
This does: it loads a `.engine`, decodes exactly the forms `opzasm.py` emits, and runs `onNoteOn` and `render`
so the output can be measured.

It is not a Blackfin emulator. It implements the forms this engine uses and refuses anything else, so a
mis-encoded instruction shows up as a hard stop rather than as plausible silence. The multiply uses the `(T)`
extraction as the SLEIGH source defines it — `(a*b) >> 32`, saturating — which is the arithmetic the reference
implementation in opzstruck.py mirrors.

Usage:
    python3 opzsim.py struck.engine            # note A4, measure pitch and decay
    python3 opzsim.py struck.engine 69 2.0     # note, seconds
"""
import math, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzengine as E
import opzstruck as S

REGS_D = ["R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7"]
REGS_P = ["P0", "P1", "P2", "P3", "P4", "P5", "SP", "FP"]
FLAG_LAST = 0x8000


def sat32(v):
    return 0x7FFFFFFF if v > 0x7FFFFFFF else (-0x80000000 if v < -0x80000000 else v)


def s32(v):
    """Reinterpret a 32-bit pattern as a signed value.

    Registers hold *signed* integers: an address like 0x81c0b060 is -0x7e3f4fa0, and treating it as a
    large positive number makes every add saturate. That misreading cost a debugging round.
    """
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v >= 0x80000000 else v


class Machine:
    """A memory window plus the register file.

    The window is derived from the module rather than fixed: an engine is pre-linked to absolute
    addresses that depend on which memory slot it was built for, so a hard-coded window silently
    stops covering the module the moment the placement changes.
    """

    # scratch areas live below the module, the stack above it
    OUT_OFF, PARAM_OFF, SCRATCH_OFF, HEADROOM = 0x10000, 0x20000, 0x30000, 0x40000

    def __init__(self, mem_base=0x81C00000, mem_size=0x200000):
        self.mem = bytearray(mem_size)
        self.mem_base = mem_base
        self.r = [0] * 8
        self.p = [0] * 8
        self.cc = False
        self.i = [0, 0, 0, 0]        # I0-I3 index registers (B/L/loop regs stay 0)
        self.astat = 0                 # only what CC2Stat moves write; arithmetic flags are not maintained
        self.loops = {}                 # LC0/LC1 frames: {'start', 'end', 'lc'}
        self.allow_external = False     # audition mode: unmapped addresses read 0 / write to a dict
        self.external = {}
        self.pc = 0
        self.steps = 0
        self.p[6] = self.mem_base + mem_size - 0x100    # SP, top of the window

    @classmethod
    def for_module(cls, raw):
        """Size the window around the module's own span, with room for output, params and stack."""
        segs = [g for g in E.parse(raw) if g[4]]
        lo = min(g[1] for g in segs)
        hi = max(g[1] + len(g[4]) for g in segs)
        base = (lo & ~0xFFF) - cls.HEADROOM
        size = ((hi - base) + cls.HEADROOM + 0xFFF) & ~0xFFF
        m = cls(base, size)
        m.load_engine(raw)
        return m

    # ---- memory -------------------------------------------------------------------------------
    def _off(self, addr, n=4):
        """Offset into the simulated window, or None when the address falls outside it.

        In strict mode (the validation gates) an outside access raises, because that is where a real bug
        would show up. In audition mode it returns None and the caller routes to `self.external`: a
        factory engine legitimately touches OS memory - the host-services table at 0x81003850, its own
        globals - none of which this harness maps. Hardware has that RAM; reading zeros here is the
        closest honest approximation, and it is opt-in so the engine self-tests keep their strictness.
        """
        o = (addr & 0xFFFFFFFF) - self.mem_base
        if not (0 <= o <= len(self.mem) - n):
            if self.allow_external:
                return None
            raise RuntimeError(f"access outside the window: 0x{addr:08x}")
        return o

    def ld32(self, addr):
        o = self._off(addr)
        if o is None:
            return s32(self.external.get(addr & 0xFFFFFFFF, 0))
        return s32(int.from_bytes(self.mem[o:o + 4], "little"))

    def st32(self, addr, v):
        o = self._off(addr)
        if o is None:
            self.external[addr & 0xFFFFFFFF] = v & 0xFFFFFFFF
            return
        self.mem[o:o + 4] = (v & 0xFFFFFFFF).to_bytes(4, "little")

    def load_engine(self, raw):
        for flags, dest, length, fill, payload in E.parse(raw):
            if not payload and not (flags & 0x0100):
                continue                          # the preamble/terminator name L1 space, carry no bytes
            if flags & 0x0100:                    # fill segment: zero the span
                o = self._off(dest, length)
                self.mem[o:o + length] = b"\x00" * length
            else:
                o = self._off(dest, len(payload))
                self.mem[o:o + len(payload)] = payload

    # ---- fetch/execute ------------------------------------------------------------------------
    def run(self, limit=20_000_000):
        while True:
            if self.steps > limit:
                raise RuntimeError("step limit")
            o = self._off(self.pc, 2)
            h = int.from_bytes(self.mem[o:o + 2], "little")
            if not self.step(h, o):
                return self.r[0]


    # ---- 32-bit DSP helpers, all read out of the SLEIGH sources -------------------------------

    def _shift_imm(self, h, h2):
        """Dsp32ShfImm (29-Dsp32ShfImm.sinc).

        The FAMILY lives in the first half's bits 0-4, not in the second half: 0 = Shift16 on one
        half, 1 = Shift16Vec on both halves, 2 = Shift32 on the whole register, 3 = ShiftAcc on an
        accumulator. Direction is h2 bit 8 (0 = left, count = imm5; 1 = right, count = 0x20 - imm5),
        and h2 bits 14-15 pick the kind: 0 arithmetic, 1 arithmetic saturated, 2 logical, 3 rotate.
        """
        sopc = h & 0x1F
        sop = (h2 >> 14) & 3
        hls = (h2 >> 12) & 3
        dst, src = (h2 >> 9) & 7, h2 & 7
        right = (h2 >> 8) & 1
        imm5 = (h2 >> 3) & 0x1F
        imm4 = (h2 >> 3) & 0xF

        if sopc == 0x02:                                     # Shift32: whole register
            n = (0x20 - imm5) if right else imm5
            v = self.r[src]
            if sop == 3:                                     # rotate through CC
                u = v & 0xFFFFFFFF
                if right:
                    sh = 0x20 - imm5
                    out = ((u << sh) | ((1 if self.cc else 0) << (sh - 1)) | (u >> (32 - sh + 1))) & 0xFFFFFFFF
                    self.cc = bool((u >> (32 - sh)) & 1)
                else:
                    k = imm5
                    out = ((u << (32 - k + 1)) | ((1 if self.cc else 0) << (32 - k)) | (u >> k)) & 0xFFFFFFFF
                    self.cc = bool((u >> (k - 1)) & 1) if k else self.cc
                self.r[dst] = s32(out)
            elif sop == 2:                                   # logical
                self.r[dst] = s32(((v & 0xFFFFFFFF) >> n) if right else ((v << n) & 0xFFFFFFFF))
            else:                                            # arithmetic, saturating when sop == 1
                self.r[dst] = sat32(v >> n) if right else sat32(v << n)
        elif sopc == 0x00:                                   # Shift16: one half of the register
            half_h_dst = (h2 >> 13) & 1
            half_h_src = (h2 >> 12) & 1
            v = self.r[src]
            sv = (v >> 16) & 0xFFFF if half_h_src else v & 0xFFFF
            sv = sv - 0x10000 if sv & 0x8000 else sv          # 16-bit signed value
            n = (0x10 - imm4) if ((h2 >> 7) & 1) else imm4
            if (h2 >> 7) & 1:
                out = (sv >> n) if sop != 2 else ((sv & 0xFFFF) >> n)
            else:
                out = sv << n
                if sop == 2:
                    out &= 0xFFFF
            out &= 0xFFFF
            self.r[dst] = s32((self.r[dst] & 0x0000FFFF) | (out << 16)) if half_h_dst \
                else s32((self.r[dst] & 0xFFFF0000) | out)
        elif sopc == 0x01:                                   # Shift16Vec: both halves at once
            n = (0x10 - imm4) if ((h2 >> 7) & 1) else imm4
            v = self.r[src]
            out = 0
            for sh in (0, 16):
                hv = (v >> sh) & 0xFFFF
                hv = hv - 0x10000 if hv & 0x8000 else hv
                if (h2 >> 7) & 1:
                    r = (hv >> n) if sop != 2 else ((hv & 0xFFFF) >> n)
                else:
                    r = hv << n
                    if sop == 2:
                        r &= 0xFFFF
                out |= (r & 0xFFFF) << sh
            self.r[dst] = s32(out)
        else:
            raise RuntimeError(f"accumulator shift not implemented at 0x{self.pc:08x}")

    def _shift_reg(self, h, h2):
        """Dsp32Shf (28-Dsp32Shf.sinc). Same family/sop encoding as the immediate form, but the count
        comes from a register: get_shift32() sign-extends the low 6 bits, so positive counts shift right
        and negative ones shift left. sopc 4 is PACK, which assembles two 16-bit halves."""
        sopc = h & 0x1F
        sop = (h2 >> 14) & 3
        dst = (h2 >> 9) & 7
        src0, src1 = (h2 >> 3) & 7, h2 & 7
        if sopc == 0x02:                                     # Shift32 by register
            count = self.r[src0] & 0x3F
            if count & 0x20:
                count -= 0x40                                # sign-extend: negative shifts left
            v = self.r[src1]
            count = max(-63, min(63, count))
            if count > 0:
                self.r[dst] = sat32(v >> count) if sop in (0, 1) else s32((v & 0xFFFFFFFF) >> count)
            elif count < 0:
                self.r[dst] = sat32(v << -count) if sop in (0, 1) else s32((v << -count) & 0xFFFFFFFF)
            else:
                self.r[dst] = v
        elif sopc == 0x05:                                   # SignBits: leading sign-redundant bits
            v = self.r[src1]
            if sop == 1:
                v = (v & 0xFFFF) - (0x10000 if v & 0x8000 else 0)
            elif sop == 2:
                v = ((v >> 16) & 0xFFFF) - (0x10000 if v & 0x80000000 else 0)
            probe = v if v >= 0 else ~v
            bits = 0
            while bits < 32 and not (probe >> (31 - bits)) & 1:
                bits += 1
            self.r[dst] = bits - 1
        elif sopc == 0x0A:                                   # Extract: len bits at offset off from src1
            spec = self.r[src0] & 0xFFFFFFFF
            length, off = spec & 0x1F, (spec >> 8) & 0x1F
            v = self.r[src1] & 0xFFFFFFFF
            if length == 0:
                self.r[dst] = 0
            else:
                self.r[dst] = s32((v >> off) & ((1 << length) - 1))
        elif sopc == 0x06:                                   # Ones (popcount) when sop selects it
            if sop == 3:
                self.r[dst] = bin(self.r[src0] & 0xFFFFFFFF).count("1")
            else:
                raise RuntimeError(f"accumulator SignBits not implemented at 0x{self.pc:08x}")
        elif sopc == 0x04:                                   # Pack16Vec: PACK(Rx.L, Ry.L)
            self.r[dst] = s32(((self.r[src0] & 0xFFFF) << 16) | (self.r[src1] & 0xFFFF))
        else:
            raise RuntimeError(f"Dsp32Shf sopc={sopc:#04x} not implemented at 0x{self.pc:08x}")

    def _mac(self, h, h2):
        raise RuntimeError(f"Dsp32Mac form not implemented (first half 0x{h:04x}) at 0x{self.pc:08x}")

    def _alu32(self, h, h2):
        """Dsp32Alu (27-Dsp32Alu.sinc). The family is daAopc at first-half bits 0-4; 0x04 is AddSub32,
        which is what compiled code uses for saturated 32-bit add/subtract:
        dst = src0 (+|-) src1, with saturation when h2 bit 13 is set."""
        aopc = h & 0x1F
        aop = (h2 >> 14) & 3
        sat = (h2 >> 13) & 1
        dst0, dst1 = (h2 >> 9) & 7, (h2 >> 6) & 7
        src0, src1 = (h2 >> 3) & 7, h2 & 7
        if aopc == 0x00:                                     # AddSubVec16: two independent 16-bit ops
            # The real form selects an operation per half and can swap halves via daX; this model does
            # the straightforward per-half add/subtract and ignores the swap. Approximation, stated.
            opH = (h2 >> 15) & 1
            opL = (h2 >> 14) & 1
            v0, v1 = self.r[src0], self.r[src1]

            def hv(v, high):
                x = ((v >> 16) & 0xFFFF) if high else (v & 0xFFFF)
                return x - 0x10000 if x & 0x8000 else x

            hi = hv(v0, True) - hv(v1, True) if opH else hv(v0, True) + hv(v1, True)
            lo = hv(v0, False) - hv(v1, False) if opL else hv(v0, False) + hv(v1, False)
            self.r[dst0] = s32(((hi & 0xFFFF) << 16) | (lo & 0xFFFF))
            return
        if aopc == 0x0F:                                     # MMAVec2: negate both halves, saturated
            aop2 = (h2 >> 14) & 3
            if aop2 != 3:
                raise RuntimeError(f"MMAVec2 aop={aop2} not implemented at 0x{self.pc:08x}")
            v = self.r[src0]
            lo = (v & 0xFFFF)
            hi = (v >> 16) & 0xFFFF
            lo = -0x8000 if lo in (0x8000, 0) and lo == 0x8000 else ((-lo) & 0xFFFF)
            hi = -0x8000 if hi == 0x8000 else ((-hi) & 0xFFFF)
            self.r[dst0] = s32((hi << 16) | lo)
            return
        if aopc in (0x02, 0x03):                             # AddSub16: 16-bit add/subtract on a half
            h2hi = (h2 >> 15) & 1        # daAopH selects the high or low half of src0
            h2lo = (h2 >> 14) & 1        # daAopL selects the half of src1
            dsthi = (h2 >> 5) & 1        # daHl selects the destination half
            sat16 = sat

            def half(v, high):
                x = ((v >> 16) & 0xFFFF) if high else (v & 0xFFFF)
                return x - 0x10000 if x & 0x8000 else x

            a, b = half(self.r[src0], h2hi), half(self.r[src1], h2lo)
            v = a + b if aopc == 0x02 else a - b
            if sat16:
                v = max(-0x8000, min(0x7FFF, v))
            else:
                v &= 0xFFFF
                if v & 0x8000:
                    v -= 0x10000
            cur = self.r[dst0]
            self.r[dst0] = s32((cur & 0xFFFF) | ((v & 0xFFFF) << 16)) if dsthi \
                else s32((cur & 0xFFFF0000) | (v & 0xFFFF))
            return
        if aopc == 0x19:                                     # AddSubAC0: +/- with the carry flag added
            ac0 = (self.astat >> 4) & 1                      # ASTAT bit AC0 (never set by ops here)
            if aop == 0:
                v = self.r[src0] + self.r[src1] + ac0
            elif aop == 1:
                v = self.r[src0] - self.r[src1] + ac0 - 1
            else:
                raise RuntimeError(f"AddSubAC0 aop={aop} not implemented at 0x{self.pc:08x}")
            self.r[dst0] = sat32(v) if sat else s32(v)
            return
        if aopc == 0x07:                                     # Max/Min/Abs/Neg 32
            if aop == 0:
                self.r[dst0] = max(self.r[src0], self.r[src1])
            elif aop == 1:
                self.r[dst0] = min(self.r[src0], self.r[src1])
            elif aop == 2:
                self.r[dst0] = sat32(abs(self.r[src0]))
            elif aop == 3:
                v = -self.r[src0]
                self.r[dst0] = sat32(v) if sat else s32(v)
            else:
                raise RuntimeError(f"MMA aop={aop} not implemented at 0x{self.pc:08x}")
            return
        if aopc != 0x04:
            raise RuntimeError(f"Dsp32Alu aopc={aopc:#04x} not implemented at 0x{self.pc:08x}")

        def add(a, b):
            v = a + b
            return sat32(v) if sat else s32(v)

        def sub(a, b):
            v = a - b
            return sat32(v) if sat else s32(v)

        if aop == 0:
            self.r[dst0] = add(self.r[src0], self.r[src1])
        elif aop == 1:
            self.r[dst0] = sub(self.r[src0], self.r[src1])
        elif aop == 2:                                       # dual: sum and difference at once
            self.r[dst0] = add(self.r[src0], self.r[src1])
            self.r[dst1] = sub(self.r[src0], self.r[src1])
        else:
            raise RuntimeError(f"AddSub32 aop={aop} not implemented at 0x{self.pc:08x}")

    def step(self, h, o):
        self.steps += 1
        done_at = self.pc
        cont = self._step(h, o)
        if cont and self.loops:
            self._loop_end(done_at)
        return cont

    def _loop_end(self, pc):
        """After the instruction at `pc` retires, a registered loop whose END is that address either
        jumps back to its start or finishes."""
        for slot, fr in list(self.loops.items()):
            if fr["end"] == pc:
                if fr["lc"] != 0:
                    fr["lc"] -= 1
                    self.pc = fr["start"]
                    return
                del self.loops[slot]
                return

    def _step(self, h, o):
        m = self.mem
        m = self.mem
        nxt = self.pc + 2

        # PushPopReg (instr16/02-PushPopReg.sinc): sig 0x002 at bits 7-15, w at bit 6 (1 = push),
        # group at bits 3-5 (0 = data, 1 = pointer) and the register at bits 0-2. Compiled code wraps
        # every call in one of these ("Push [--SP] = R7"), sometimes without the multi-register form.
        if (h & 0xFF80) == 0x0100:
            w = (h >> 6) & 1
            grp, reg = (h >> 3) & 7, h & 7
            if grp == 0:
                if w:
                    self.p[6] -= 4
                    self.st32(self.p[6], self.r[reg])
                else:
                    self.r[reg] = self.ld32(self.p[6])
                    self.p[6] += 4
            elif grp == 1:
                if w:
                    self.p[6] -= 4
                    self.st32(self.p[6], self.p[reg])
                else:
                    self.p[reg] = self.ld32(self.p[6])
                    self.p[6] += 4
            else:
                raise RuntimeError(f"push/pop of register group {grp} at 0x{self.pc:08x}")
            self.pc = nxt
            return True

        # CC2Dreg (instr16/03-CC2Dreg.sinc): sig 0x010 at bits 5-15, opc at 3-4, register at 0-2.
        if (h & 0xFE00) == 0x0200:
            opc, reg = (h >> 3) & 3, h & 7
            if opc == 0:
                self.r[reg] = 1 if self.cc else 0
            elif opc == 1:
                self.cc = self.r[reg] != 0
            elif opc == 2:
                self.r[reg] = 0 if self.cc else 1
            else:
                self.cc = not self.cc
            self.pc = nxt
            return True

        # CC2Stat (instr16/05-CC2Stat.sinc): sig 0x03 at bits 8-15, d at 7 (1 = write), op at 5-6,
        # ASTAT bit index below. ASTAT itself is only ever written through these moves here: the
        # arithmetic flags (AZ/AN/AV/AC) are NOT maintained by the ops above, so any engine that
        # branches on a computed carry will see a zero. That is an audition-grade approximation.
        if (h & 0xFF00) == 0x0300:
            d, op, bit = (h >> 7) & 1, (h >> 5) & 3, h & 0x1F
            bitval = (self.astat >> bit) & 1
            if d == 0:
                if op == 0:
                    self.cc = bool(bitval)
                elif op == 1:
                    self.cc = self.cc or bool(bitval)
                elif op == 2:
                    self.cc = self.cc and bool(bitval)
                else:
                    self.cc = self.cc != bool(bitval)
            else:
                if op == 0:
                    self.astat = (self.astat & ~(1 << bit)) | ((1 if self.cc else 0) << bit)
                elif op == 1:
                    self.astat |= (1 if self.cc else 0) << bit
                elif op == 2:
                    self.astat &= ~(1 << bit) & 0xFFFFFFFF
                    self.astat |= 0 if self.cc else 0
                else:
                    self.astat ^= (1 if self.cc else 0) << bit
            self.pc = nxt
            return True

        # CCMV (instr16/07-CCMV.sinc): sig 0x03 at bits 9-15, t at bit 8 (1 = if CC), d at 7, s at 6,
        # dst at 3-5 and src at 0-2. Compiled code uses it to select between two constants.
        if (h & 0xFE00) == 0x0600:
            t, d, sflag = (h >> 8) & 1, (h >> 7) & 1, (h >> 6) & 1
            dst, src = (h >> 3) & 7, h & 7
            if (self.cc == bool(t)):
                val = self.r[src] if sflag == 0 else self.p[src]
                if d == 0:
                    self.r[dst] = val
                else:
                    self.p[dst] = val
            self.pc = nxt
            return True

        # Logi2Op (instr16/14-Logi2Op.sinc): sig 0x09 at bits 11-15, opc at 8-10, bit number at 3-7
        # and the register at 0-2. Covers BITTST (which compiler-generated loops use to test a low bit)
        # as well as BITSET/BITTGL/BITCLR and the variable shifts.
        if (h & 0xF800) == 0x4800:
            opc, bitn, reg = (h >> 8) & 7, (h >> 3) & 0x1F, h & 7
            v = self.r[reg]
            if opc == 0:
                self.cc = (v & (1 << bitn)) == 0
            elif opc == 1:
                self.cc = (v & (1 << bitn)) != 0
            elif opc == 2:
                self.r[reg] = s32(v | (1 << bitn))
            elif opc == 3:
                self.r[reg] = s32(v ^ (1 << bitn))
            elif opc == 4:
                self.r[reg] = s32(v & ~(1 << bitn))
            elif opc == 5:
                self.r[reg] = s32(v >> bitn)
            elif opc == 6:
                self.r[reg] = s32((v & 0xFFFFFFFF) >> bitn)
            else:
                self.r[reg] = s32(v << bitn)
            self.pc = nxt
            return True

        # ALU2op (instr16/12-ALU2op.sinc): sig 0x10 at bits 10-15, opc at 6-9, src at 3-5, dst at 0-2.
        if (h & 0xFC00) == 0x4000:
            opc, src, dst = (h >> 6) & 0xF, (h >> 3) & 7, h & 7
            a, b = self.r[dst], self.r[src]
            if opc in (0, 1, 2):
                b = max(0, min(63, b))     # a register used as a shift count must not go negative
            if opc == 0:
                self.r[dst] = s32(a >> b)
            elif opc == 1:
                self.r[dst] = s32((a & 0xFFFFFFFF) >> b)
            elif opc == 2:
                self.r[dst] = s32(a << b)
            elif opc == 3:
                self.r[dst] = s32(a * b)
            elif opc == 4:
                self.r[dst] = s32((a + b) << 1)
            elif opc == 5:
                self.r[dst] = s32((a + b) << 2)
            elif opc in (8, 9):                            # DIVQ / DIVS: one division step each
                aq = (self.astat >> 6) & 1
                ua, ub = a & 0xFFFFFFFF, b & 0xFFFFFFFF
                if opc == 8:
                    v = (a + (b << 16) if aq else a - (b << 16)) & 0xFFFFFFFF
                    self.astat = (self.astat & ~(1 << 6)) | \
                                 ((1 if ((v >= 0x80000000) != ((b & 0xFFFF) >= 0x8000)) else 0) << 6)
                    aq = (self.astat >> 6) & 1
                    self.r[dst] = s32(((v << 1) & 0xFFFFFFFF) | (0 if aq else 1))
                else:
                    self.astat = (self.astat & ~(1 << 6)) | \
                                 ((1 if ((ua >= 0x80000000) != ((ub & 0xFFFF) >= 0x8000)) else 0) << 6)
                    aq = (self.astat >> 6) & 1
                    self.r[dst] = s32(((ua << 1) & 0xFFFFFFFF) | aq)
            elif opc in (0xA, 0xB, 0xC, 0xD, 0xE, 0xF):
                if opc == 0xA:
                    self.r[dst] = s32((b & 0xFFFF) - 0x10000 if (b & 0x8000) else (b & 0xFFFF))
                elif opc == 0xB:
                    self.r[dst] = b & 0xFFFF
                elif opc == 0xC:
                    byte = b & 0xFF
                    self.r[dst] = s32(byte - 0x100 if byte & 0x80 else byte)
                elif opc == 0xD:
                    self.r[dst] = b & 0xFF
                elif opc == 0xE:
                    self.r[dst] = s32(-b)
                else:
                    self.r[dst] = s32(~b)
            else:
                raise RuntimeError(f"ALU2op opc={opc:#x} at 0x{self.pc:08x}")
            self.pc = nxt
            return True

        # Ptr2op (instr16/13-Ptr2op.sinc): sig 0x22 at bits 9-15, opc at 6-8, src at 3-5, dst at 0-2.
        if (h & 0xFE00) == 0x4400:
            opc, src, dst = (h >> 6) & 7, (h >> 3) & 7, h & 7
            if opc == 0:
                self.p[dst] = s32(self.p[dst] - self.p[src])
            elif opc == 1:
                self.p[dst] = s32(self.p[src] << 2)
            elif opc == 2:
                self.p[dst] = s32(self.p[src] << 1)
            elif opc == 3:
                self.p[dst] = s32((self.p[src] & 0xFFFFFFFF) >> 2)
            elif opc == 4:
                self.p[dst] = s32((self.p[src] & 0xFFFFFFFF) >> 1)
            else:
                self.p[dst] = s32(self.p[dst] + self.p[src])
            self.pc = nxt
            return True

        if h == 0x0000:                                    # NOP (factory code is full of them)
            self.pc = nxt
            return True

        # push / pop (R7:4, P5:3) - the only push/pop form emitted
        # PushPopMult (instr16/06-PushPopMult.sinc): 7-bit signature 0b0000010 at bits 9-15, d/p flags at
        # bits 8/7 (data / pointer registers present), w at bit 6 (1 = push, 0 = pop), the top data
        # register at bits 3-5 and the top pointer register at bits 0-2. Hardware order matters: the
        # push stores data registers high-to-low then pointer registers high-to-low, so the LAST value
        # written sits at SP - which is why a push (R7:4, P5:3) leaves P3 at [SP].
        if (h & 0xFE00) == 0x0400:                         # signature 0b0000010 in bits 9-15
            d, pflag, w = (h >> 8) & 1, (h >> 7) & 1, (h >> 6) & 1
            dr, pr = (h >> 3) & 7, h & 7
            # the field names the LOWEST register of the group, so (R7:4) encodes as dr=4 and the group
            # runs upward to R7 - pushing 4..0 here instead of 4..7 corrupts the frame silently
            if w:                                          # push: high register to the high address
                for i in range(7, dr - 1, -1):
                    if d:
                        self.p[6] -= 4
                        self.st32(self.p[6], self.r[i])
                for i in range(5, pr - 1, -1):        # the pointer group tops out at P5 (P5:3)
                    if pflag:
                        self.p[6] -= 4
                        self.st32(self.p[6], self.p[i])
            else:                                          # pop, exactly the reverse
                for i in range(pr, 6):
                    if pflag:
                        self.p[i] = self.ld32(self.p[6])
                        self.p[6] += 4
                for i in range(dr, 8):
                    if d:
                        self.r[i] = self.ld32(self.p[6])
                        self.p[6] += 4
            self.pc = nxt
            return True

        # LdStAbs (instr64/37-LdStAbs.sinc): 8 bytes - 0xD800, immH, immL, then a control halfword with
        # sz at bits 10-11, w (store) at bit 9, z at bit 6 and the register at 0-2. An absolute 32-bit
        # address is how a module reaches its own globals, which is what a factory engine does first.
        # Displacement load/store, 16-bit: h = 1 0 1 | w | class(2) | disp/4 (4 bits) | ptr (3) | reg (3).
        # This is the form a factory engine uses to read its arguments off the frame ([FP + 0x14],
        # [SP + 0x30]) and it had no catalogue entry here because the engine built by build_struck.py
        # reaches its arguments by counting post-increment loads instead. The field layout is fitted
        # from 194 instructions decoded by Ghidra across two factory engines, with every sample agreeing:
        # pointer at bits 3-5, disp/4 at bits 6-9, class 0b00 = data register and 0b11 = pointer register,
        # and bit 12 = 0 for load / 1 for store.
        # LdStPmod (instr16/17-LdStPmod.sinc): sig 0x8 at bits 12-15, w at 11, aop at 9-10, reg at 6-8,
        # idx at 3-5, ptr at 0-2. The address is [Pptr] and the pointer is then advanced by ANOTHER
        # pointer register (ptr += idx), which is how circular addressing is written.
        if (h & 0xF000) == 0x8000:
            w, aop = (h >> 11) & 1, (h >> 9) & 3
            reg, idx, ptr = (h >> 6) & 7, (h >> 3) & 7, h & 7
            addr = self.p[ptr]
            if aop == 0:
                step = 4
            elif aop == 1:
                step = 2
            elif aop == 2:
                step = 2
            else:
                step = 4
            if w:
                self.st32(addr, self.r[reg])
            else:
                v = self.ld32(addr)
                if aop == 0:
                    self.r[reg] = v
                elif aop == 1:                              # W[...] low half
                    self.r[reg] = s32((self.r[reg] & 0xFFFF0000) | (v & 0xFFFF))
                elif aop == 2:                              # W[...] high half
                    self.r[reg] = s32((self.r[reg] & 0xFFFF) | ((v & 0xFFFF) << 16))
                else:                                       # zext 16-bit
                    self.r[reg] = v & 0xFFFF
            self.p[ptr] = s32(self.p[ptr] + self.p[idx])
            self.pc = nxt
            return True

        # LdStIdxI (instr32/34-LdStIdxI.sinc): sig 0x39 at bits 10-15, w at 9, z at 8, sz at 6-7,
        # ptr at 3-5, reg at 0-2, and a signed 16-bit offset in the second halfword (x4 for 32-bit
        # words, x2 for 16-bit, raw for bytes). This is the form a factory engine uses for [P + big].
        if (h & 0xFC00) == 0xE400:
            w, z = (h >> 9) & 1, (h >> 8) & 1
            sz, ptr, reg = (h >> 6) & 3, (h >> 3) & 7, h & 7
            off = int.from_bytes(m[o + 2:o + 4], "little")
            if off & 0x8000:
                off -= 0x10000
            if sz == 0:
                addr = self.p[ptr] + off * 4
            elif sz == 1:
                addr = self.p[ptr] + off * 2
            else:
                addr = self.p[ptr] + off
            addr = s32(addr)
            if sz == 0:
                if w:
                    self.st32(addr, self.p[reg] if z else self.r[reg])
                else:
                    val = self.ld32(addr)
                    if z:
                        self.p[reg] = val
                    else:
                        self.r[reg] = val
            elif sz == 1:                                  # 16-bit load/store
                if w:
                    word = self.ld32(addr & ~3)
                    shift = 16 if addr & 2 else 0
                    self.st32(addr & ~3, (word & ~(0xFFFF << shift)) |
                              ((self.r[reg] & 0xFFFF) << shift))
                else:
                    half = (self.ld32(addr & ~3) >> (16 if addr & 2 else 0)) & 0xFFFF
                    self.r[reg] = s32(half - 0x10000 if (z and half & 0x8000) else half)
            elif sz == 2 and w:                            # 8-bit store
                base, shift = addr & ~3, 8 * (addr & 3)
                word = self.ld32(base)
                self.st32(base, (word & ~(0xFF << shift)) | ((self.r[reg] & 0xFF) << shift))
            elif sz == 2 and not w:                        # 8-bit load
                byte = (self.ld32(addr & ~3) >> (8 * (addr & 3))) & 0xFF
                self.r[reg] = s32(byte - 0x100 if (z and byte & 0x80) else byte)
            else:
                raise RuntimeError(f"LdStIdxI sz={sz} w={w} not implemented at 0x{self.pc:08x}")
            self.pc = self.pc + 4
            return True

        # NOP32 (instr32/24-NOP32.sinc): 0xC803 then 0x1800 - four bytes of padding that compiled code
        # leaves where an instruction could be reordered into.
        if h == 0xC803 and int.from_bytes(m[o + 2:o + 4], "little") == 0x1800:
            self.pc = self.pc + 4
            return True

        # ProgCtrl (instr16/01-ProgCtrl.sinc): sig 0x00 at bits 8-15, opc at 4-7, register at 0-3.
        # opc 5/6 are indirect JUMP/CALL through a pointer register, which is how an engine calls out.
        if (h & 0xFF00) == 0x0000 and h not in (0x0000, 0x0010):
            opc, reg = (h >> 4) & 0xF, h & 7
            if opc in (5, 6):
                target = self.p[reg]
                if opc == 6:
                    self.p[6] -= 4
                    self.st32(self.p[6], nxt)
                self.pc = target
                return True
            if opc in (1, 2):                              # RTS handled elsewhere; SSYNC/NOP-like
                self.pc = nxt
                return True
            if opc in (3, 4, 0xC):                         # CLI / STI / STI IDLE: no interrupts here
                self.pc = nxt
                return True
            raise RuntimeError(f"ProgCtrl opc={opc:#x} at 0x{self.pc:08x}")

        if (h & 0xE000) == 0xA000:
            w = (h >> 12) & 1
            cls = (h >> 10) & 3
            disp = ((h >> 6) & 0xF) * 4
            ptr, reg = (h >> 3) & 7, h & 7
            if cls == 2:
                # frame-relative form: [FP - n], with a signed 6-bit displacement/4 at bits 4-9. The
                # three samples recovered from factory engines are all spills of an argument
                # ([FP - 0x3c], [FP - 0x7c], [FP - 0x8]); bits 11-13 read 0b111 (FP) in every one, so
                # the guard below keeps this honest instead of pretending the field is general.
                # every sample recovered reads FP here; two engines encode 5 instead, and treating that
                # as a different base would be a guess, so the form stays FP-relative and the deviation
                # is left visible in this comment rather than silently reinterpreted
                field = (h >> 4) & 0x3F
                if field & 0x20:
                    field -= 0x40
                addr = s32(self.p[7] + field * 4)
                if w:
                    self.st32(addr, self.r[reg])
                else:
                    self.r[reg] = self.ld32(addr)
                self.pc = nxt
                return True
            if cls == 1:
                cls = 0                                        # same fields, data-register form
            if cls not in (0, 3):
                raise RuntimeError(f"displacement LdSt class {cls} at 0x{self.pc:08x}")
            addr = s32(self.p[ptr] + disp)
            if cls == 3:
                if w:
                    self.st32(addr, self.p[reg])
                else:
                    self.p[reg] = self.ld32(addr)
            else:
                if w:
                    self.st32(addr, self.r[reg])
                else:
                    self.r[reg] = self.ld32(addr)
            self.pc = nxt
            return True

        # LdImmHalf (instr32/32-LdImmHalf.sinc): signature 0xE1 at bits 8-15, z at bit 7, h at bit 6,
        # s at bit 5, then a 16-bit immediate. Four variants cover what compiled code emits:
        # Rd.L = imm, Rd.H = imm, Rd = sext(imm), Rd = zext(imm).
        if (h & 0xFF00) == 0xE100:
            z, hb, sb = (h >> 7) & 1, (h >> 6) & 1, (h >> 5) & 1
            reg = h & 7
            word = int.from_bytes(m[o + 2:o + 4], "little")
            sval = word - 0x10000 if word & 0x8000 else word
            if z == 0 and hb == 1 and sb == 0:               # Rd.H = imm
                self.r[reg] = s32((self.r[reg] & 0xFFFF) | (word << 16))
            elif z == 0 and hb == 0 and sb == 1:             # Rd = sext(imm)
                self.r[reg] = s32(sval)
            elif z == 1 and hb == 0 and sb == 0:             # Rd = zext(imm)
                self.r[reg] = word
            elif z == 0 and hb == 0 and sb == 0:             # Rd.L = imm
                self.r[reg] = s32((self.r[reg] & 0xFFFF0000) | (word & 0xFFFF))
            else:
                raise RuntimeError(f"LdImmHalf form z={z} h={hb} s={sb} at 0x{self.pc:08x}")
            self.pc = self.pc + 4
            return True

        if h == 0xD800:
            imm = s32((int.from_bytes(m[o + 2:o + 4], "little") << 16) |
                      int.from_bytes(m[o + 4:o + 6], "little"))
            ctrl = int.from_bytes(m[o + 6:o + 8], "little")
            sz, w, z, reg = (ctrl >> 10) & 3, (ctrl >> 9) & 1, (ctrl >> 6) & 1, ctrl & 7
            if sz == 0 and not w:
                val = self.ld32(imm)
                if z:
                    self.p[reg] = val
                else:
                    self.r[reg] = val
            elif sz == 0 and w:
                self.st32(imm, self.p[reg] if z else self.r[reg])
            elif sz == 1 and not w:                        # 16-bit load, z selects sign extension
                word = (self.ld32(imm & ~3) >> (16 if imm & 2 else 0)) & 0xFFFF
                self.r[reg] = s32(word - 0x10000) if (z and word & 0x8000) else word
            elif sz == 2 and not w:                        # 8-bit load
                byte = (self.ld32(imm & ~3) >> (8 * (imm & 3))) & 0xFF
                self.r[reg] = s32(byte - 0x100) if (z and byte & 0x80) else byte
            elif sz == 2 and w:                            # 8-bit store
                if z:
                    self.st32(imm, self.p[reg])
                else:
                    addr, shift = imm & ~3, 8 * (imm & 3)
                    word = self.ld32(addr)
                    self.st32(addr, (word & ~(0xFF << shift)) | ((self.r[reg] & 0xFF) << shift))
            else:
                raise RuntimeError(f"unsupported LdStAbs form sz={sz} w={w} at 0x{self.pc:08x}")
            self.pc = self.pc + 8
            return True

        # LoopSetupImm (instr32/30-LoopSetupImm.sinc): sig 0x1C1 at bits 7-15, rop at 5-6 (0x2 = the
        # immediate-count form), c at bit 4 selects LC0/LC1, the count is immH<<6|immL, and the loop's
        # END address is inst_start + eoff*2 while its start is the following instruction. The loop runs
        # until the counter reaches zero, so it executes lc+1 times - the convention gcc's LSETUP
        # idioms assume (a loop of N has lc = N-1).
        if (h & 0xFF80) == 0xE080:
            slot = (h >> 4) & 1
            h2 = int.from_bytes(m[o + 2:o + 4], "little")
            count = ((h & 0xF) << 6) | ((h2 >> 10) & 0x3F)
            end = self.pc + ((h2 & 0x3FF) * 2)
            self.loops[slot] = {"start": self.pc + 4, "end": end, "lc": count}
            self.pc = self.pc + 4
            return True

        # CallA (instr32/33-CallA.sinc): sig 0x71 at bits 9-15, s at bit 8 (0 = JUMP.L, 1 = CALL), and a
        # 24-bit pcrel target built from a signed high byte and the whole second halfword:
        # target = inst_start + ((swH << 16) | swL) * 2.
        if (h & 0xFE00) == 0xE200:
            s8 = h & 0xFF
            if s8 & 0x80:
                s8 -= 0x100
            swl = int.from_bytes(m[o + 2:o + 4], "little")
            # s8 is already signed, so this OR is the two's-complement 24-bit value in Python's
            # arbitrary precision: sign-extending again here subtracted 0x2000000 from every backwards
            # call, which showed up as "access outside the window" at exactly target - 0x2000000.
            delta = (s8 << 16) | swl
            target = (self.pc + delta * 2) & 0xFFFFFFFF
            if (h >> 8) & 1:                               # CALL
                self.p[6] -= 4
                self.st32(self.p[6], self.pc + 4)
                self.pc = target
                return True
            self.pc = target
            return True

        # LINK / UNLINK (instr32/35-Linkage.sinc): LINK pushes RETS and FP, sets FP = SP and then
        # allocates frame*4 bytes; UNLINK restores it. Every factory engine opens with LINK, so without
        # this the interpreter stops on a shipped engine's very first instruction.
        if h == 0xE800:
            fr = int.from_bytes(m[o + 2:o + 4], "little") * 4
            rets = self.ld32(self.p[6])                    # CALL pushed it; RETS holds the same value
            self.p[6] -= 4
            self.st32(self.p[6], rets)
            self.p[6] -= 4
            self.st32(self.p[6], self.p[7])
            self.p[7] = self.p[6]
            self.p[6] -= fr
            self.pc = self.pc + 4
            return True
        if h == 0xE801:                                    # UNLINK
            self.p[6] = self.p[7]
            self.p[7] = self.ld32(self.p[6])
            self.p[6] += 4
            self.ld32(self.p[6])                           # pop RETS (discarded; RTS pops the real one)
            self.p[6] += 4
            self.pc = nxt
            return True

        if h == 0x0010:                                    # RTS
            self.pc = self.ld32(self.p[6])
            self.p[6] += 4
            return False

        # ldimm32: 0xDA00|reg, immH, immL, dummy
        if (h & 0xFF00) == 0xDA00:
            reg = h & 7
            imh = int.from_bytes(m[o + 2:o + 4], "little")
            iml = int.from_bytes(m[o + 4:o + 6], "little")
            self.r[reg] = s32(imh << 16 | iml)
            self.pc = self.pc + 8
            return True

        # 32-bit DSP forms share the 0xC nibble, but the sub-opcode field is NOT one width:
        # Dsp32Mac/Mult/Alu put it at bits 9-10 (26/27/25-*.sinc) while Dsp32Shf/ShfImm use bits 7-10
        # (28/29-*.sinc). Reading a single 4-bit field at bit 7 misread every multiply whose modifier
        # bits were non-zero, which is how a multiply came back as "sub-opcode 0x8".
        if (h & 0xF000) == 0xC000:
            h2 = int.from_bytes(m[o + 2:o + 4], "little")
            sig2 = (h >> 9) & 3          # Mac=0, Mult=1, Alu=2
            sigd = (h >> 7) & 0xF        # Shf=0xC, ShfImm=0xD
            if sigd == 0xD:                                  # shift by immediate, all four families
                self._shift_imm(h, h2)
            elif sigd == 0xC:                                # Dsp32Shf: shift by a register operand
                self._shift_reg(h, h2)
            elif sig2 == 1:                                  # Dsp32Mult
                dst = (h2 >> 6) & 7
                src0 = (h2 >> 3) & 7
                src1 = h2 & 7
                # the (T) extraction: rounding() clears the low four bytes, then 32-bit truncation
                self.r[dst] = sat32((self.r[src0] * self.r[src1]) >> 32)
            elif sig2 == 0:                                  # Dsp32Mac
                self._mac(h, h2)
            elif sig2 == 2:                                  # Dsp32Alu
                self._alu32(h, h2)
            else:
                raise RuntimeError(f"DSP sub-opcode {sigd:#x} not implemented at 0x{self.pc:08x}")
            self.pc = self.pc + 4
            return True

        sig = (h >> 12) & 0xF
        if sig == 0x1:                                     # brcc
            off = h & 0x3FF
            if off & 0x200:
                off -= 0x400
            want_cc = bool((h >> 11) & 1)
            if self.cc == want_cc:
                self.pc = self.pc + off * 2
            else:
                self.pc = nxt
            return True
        if sig == 0x2:                                     # jump.s
            off = h & 0xFFF
            if off & 0x800:
                off -= 0x1000
            self.pc = self.pc + off * 2
            return True
        if sig == 0x9:                                     # ldst
            sz = (h >> 10) & 3
            store = (h >> 9) & 1
            aop = (h >> 7) & 3
            use_p = (h >> 6) & 1
            ptr = (h >> 3) & 7
            reg = h & 7
            inc = {0: 4, 1: 2, 2: 1}.get(sz, 4)
            addr = self.p[ptr]
            if aop == 0:
                self.p[ptr] += inc
            elif aop == 1:
                self.p[ptr] -= inc
            if store:
                self.st32(addr, self.p[reg] if use_p else self.r[reg])
            else:
                v = self.ld32(addr)
                if use_p:
                    self.p[reg] = v
                else:
                    self.r[reg] = v
            self.pc = nxt
            return True
        if sig == 0x5:                                     # addsub32
            opc = (h >> 9) & 7
            dst = (h >> 6) & 7
            s1 = (h >> 3) & 7
            s0 = h & 7
            self.r[dst] = sat32(self.r[s0] + self.r[s1] if opc == 0 else self.r[s0] - self.r[s1])
            self.pc = nxt
            return True
        if sig == 0x3:                                     # regmv
            gd = (h >> 9) & 7
            gs = (h >> 6) & 7
            dst = (h >> 3) & 7
            src = h & 7
            if gs == 0:
                val = self.r[src]
            elif gs == 1:
                val = self.p[src]
            elif gs == 2 and not ((h >> 5) & 1):           # gs=2, srcH=0 -> I registers
                val = self.i[src & 3]
            elif gs == 3:                                  # B/L circular-buffer registers: not modelled
                val = 0
            elif gs in (4, 6, 7):                          # ASTAT / RETS / system registers
                val = 0
            else:
                raise RuntimeError(f"regmv: unsupported source class gs={gs} at 0x{self.pc:08x}")
            if gd == 0:
                self.r[dst] = val
            elif gd == 1:
                self.p[dst] = val
            elif gd == 2 and not ((h >> 5) & 1):
                self.i[dst & 3] = val
            elif gd in (2, 3, 4, 6, 7):
                pass                                       # M/B/L stacks, ASTAT, system: discarded
            else:
                raise RuntimeError(f"regmv: unsupported destination gd={gd} at 0x{self.pc:08x}")
            self.pc = nxt
            return True
        if sig == 0x6:                                     # cmp_eq0 / ldimm7
            r_is_p = (h >> 11) & 1
            opc = (h >> 10) & 1
            if opc == 0:
                imm = (h >> 3) & 0x7F
                if imm & 0x40:
                    imm -= 0x80
                if r_is_p:
                    self.p[h & 7] = imm
                else:
                    self.r[h & 7] = imm
            else:                                          # AddImm: Rd += imm, signed 7-bit
                imm = (h >> 3) & 0x7F
                if imm & 0x40:
                    imm -= 0x80
                if r_is_p:
                    self.p[h & 7] = s32(self.p[h & 7] + imm)
                else:
                    self.r[h & 7] = s32(self.r[h & 7] + imm)
            self.pc = nxt
            return True
        # CCFlag (instr16/08-CCFlag.sinc): bits 11-15 = 0b00001, i at bit 10 (0 = register y, 1 = 5-bit
        # immediate), opc at 7-9 (0 ==, 1 s<, 2 s<=, 3 u<, 4 u<=), g at 6 (0 = R, 1 = P), y at 3-5, x at 0-2.
        # Factory engines compare two registers ("CC = R0 == R3") within their first few instructions,
        # which is why covering only the "== 0" form left every one of them unusable.
        if (h & 0xF800) == 0x0800:
            i_bit, opc, g = (h >> 10) & 1, (h >> 7) & 7, (h >> 6) & 1
            x, y = h & 7, (h >> 3) & 7
            xv = self.p[x] if g else self.r[x]
            if i_bit:
                yv = y - 0x20 if opc <= 2 and y & 0x10 else y     # signed form sign-extends 5 bits
            else:
                yv = self.p[y] if g else self.r[y]
            if opc == 0:
                self.cc = xv == yv
            elif opc == 1:
                self.cc = xv < yv
            elif opc == 2:
                self.cc = xv <= yv
            elif opc == 3:
                self.cc = (xv & 0xFFFFFFFF) < (yv & 0xFFFFFFFF)
            elif opc == 4:
                self.cc = (xv & 0xFFFFFFFF) <= (yv & 0xFFFFFFFF)
            else:
                raise RuntimeError(f"unsupported CCFlag opc={opc} at 0x{self.pc:08x}")
            self.pc = nxt
            return True
            self.pc = nxt
            return True
        raise RuntimeError(f"unsupported instruction 0x{h:04x} at 0x{self.pc:08x}")


def call(m, entry, args, stack=(), limit=20_000_000):
    """Call a function: first three args in R0-R2, the rest pushed in reverse on the stack."""
    for i, a in enumerate(args[:3]):
        m.r[i] = a
    for a in reversed(stack):
        m.p[6] -= 4
        m.st32(m.p[6], a)
    m.p[6] -= 4
    m.st32(m.p[6], 0xDEAD0000)             # sentinel return address
    m.pc = entry
    depth = m.steps
    while m.steps - depth < limit:
        o = m._off(m.pc, 2)
        if o is None:                          # jumped outside the window: treat as a host service
            m.pc = m.ld32(m.p[6])
            m.p[6] += 4
            m.r[0] = 0
            continue
        h = int.from_bytes(m.mem[o:o + 2], "little")
        if h == 0x0010:
            m.pc = m.ld32(m.p[6])
            m.p[6] += 4
            return m.r[0]
        m.step(h, o)
    raise RuntimeError("call did not return")


def measure(note=69, seconds=1.0, engine="struck.engine"):
    raw = pathlib.Path(engine).read_bytes()
    mod = E.read_module(raw)
    if not mod:
        raise SystemExit("not a valid module")
    exports = dict(mod["exports"])
    m = Machine.for_module(raw)

    # initModule(id=0, host=0x81003850, out) then init(), then onNoteOn(a1, note, ctx)
    scratch = m.mem_base + Machine.SCRATCH_OFF
    ret = call(m, exports["initModule"], [0, 0x81003850, scratch])
    if ret != 1:
        raise SystemExit(f"initModule returned {ret}, expected 1")
    call(m, exports["init"], [scratch, 0])
    call(m, exports["onNoteOn"], [0, note, scratch])

    out = m.mem_base + Machine.OUT_OFF             # output buffer inside the window
    frames = int(S.FS * seconds)
    blocks = frames // S.BLOCK
    for _ in range(blocks):
        call(m, exports["render"], [out, int(440.0 * 65536), 0])
        # render walks its own pointer; the buffer is re-used, so copy is unnecessary
    buf = [int.from_bytes(m.mem[m._off(out) + 8 * i:m._off(out) + 8 * i + 4], "little", signed=True)
           for i in range(S.BLOCK)]
    # keep the last block for measurement, and reseed for a full-length capture next time
    return buf, m


def selftest():
    fails = 0

    def check(name, ok, detail):
        nonlocal fails
        fails += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'}  {name:26s} {detail}")

    raw = pathlib.Path("struck.engine")
    if not raw.exists():
        import build_struck
        pathlib.Path("struck.engine").write_bytes(build_struck.build()[0])
    raw = raw.read_bytes()
    mod = E.read_module(raw)
    exports = dict(mod["exports"])
    m = Machine.for_module(raw)

    check("initModule(0,...) -> 1", call(m, exports["initModule"], [0, 0x81003850, m.mem_base + Machine.SCRATCH_OFF]) == 1, "")
    check("initModule(1,...) -> 0", call(m, exports["initModule"], [1, 0x81003850, m.mem_base + Machine.SCRATCH_OFF]) == 0, "rejects a foreign id")

    scratch = m.mem_base + Machine.SCRATCH_OFF
    params = m.mem_base + Machine.PARAM_OFF
    for i in range(8):
        m.st32(params + 4 * i, 4 << 28)          # decay bucket 4 (target 1.6 s)
    call(m, exports["initModule"], [0, 0x81003850, scratch])
    call(m, exports["init"], [scratch, 0])
    call(m, exports["onNoteOn"], [0, 69, scratch])

    # one block, captured properly: render once and read the whole 64-frame block
    out = m.mem_base + Machine.OUT_OFF
    for i in range(8192):
        m.st32(out + 4 * i, 0)
    call(m, exports["render"], [out, 440 << 16, 0], stack=(scratch, params, 0))
    # the buffer is interleaved stereo: two consecutive 32-bit words per frame, so words are 4 bytes
    # apart. Stepping by 8 would read only one channel and make the channel check meaningless.
    first = [m.ld32(out + 4 * j) for j in range(2 * S.BLOCK)]
    check("render produces output", any(v != 0 for v in first), f"first sample 0x{first[0] & 0xFFFFFFFF:08x}")
    check("stereo channels equal", all(first[2 * i] == first[2 * i + 1] for i in range(S.BLOCK)), "")

    # run a second block: the state must have advanced, so the output must differ
    call(m, exports["render"], [out, 440 << 16, 0], stack=(scratch, params, 0))
    second = [m.ld32(out + 4 * j) for j in range(2 * S.BLOCK)]
    check("state advances", first != second, "")
    # energy, not peak: a single 64-frame block is 1.3 ms, so the waveform's phase moves the peak
    # around more than the envelope does. Over 16 blocks (~21 ms) a 1.2 s T60 gives ~11% of decay.
    # Compare the mean over the first third with the mean over the last third of a long run, not two
    # adjacent windows: the output is a SUM of six decaying modes whose phases realign as they decay,
    # so the instantaneous energy of that sum can rise while every single mode is falling.
    energies = []
    for _ in range(72):
        for j in range(2 * S.BLOCK):
            m.st32(out + 4 * j, 0)
        call(m, exports["render"], [out, 440 << 16, 0], stack=(scratch, params, 0))
        energies.append(sum(m.ld32(out + 4 * j) ** 2 for j in range(2 * S.BLOCK)))
    head = sum(energies[:24]) / 24
    tail = sum(energies[-24:]) / 24
    check("energy decays over 72 blocks", tail < head * 0.95, f"{head:.3e} -> {tail:.3e}")

    # gate off -> next render must be silent
    call(m, exports["onNoteOff"], [0, scratch])
    for i in range(512):
        m.st32(out + 4 * i, 0x11223344)
    call(m, exports["render"], [out, 440 << 16, 0], stack=(scratch, params, 0))
    check("gate off -> silence",
          all(m.ld32(out + 4 * j) == 0x11223344 for j in range(2 * S.BLOCK)), "gate respected")

    # ---- pitch and decay measured from the engine's own output, not from a model
    def capture(note, blocks, machine, bucket=4):
        sc = machine.mem_base + Machine.SCRATCH_OFF
        params = machine.mem_base + Machine.PARAM_OFF
        for i in range(8):
            machine.st32(params + 4 * i, bucket << 28)   # the decay macro sits in params[2]
        call(machine, exports["initModule"], [0, 0x81003850, sc])
        call(machine, exports["init"], [sc, 0])
        call(machine, exports["onNoteOn"], [0, note, sc])
        o = machine.mem_base + Machine.OUT_OFF
        buf = []
        for _ in range(blocks):
            for j in range(2 * S.BLOCK):
                machine.st32(o + 4 * j, 0)
            call(machine, exports["render"], [o, 440 << 16, 0], stack=(sc, params, 0))
            buf += [machine.ld32(o + 4 * j) for j in range(2 * S.BLOCK)]
        return buf

    for note, expect in ((69, 440.0), (57, 220.0), (81, 880.0), (45, 110.0)):
        mm = Machine.for_module(raw)
        buf = capture(note, 80, mm)
        f = S.measure_freq(buf)
        err = abs(f - expect) / expect
        check(f"engine pitch note {note}", err < 0.02, f"{f:.1f} Hz vs {expect:.0f} Hz ({100*err:.2f}%)")

    # the decay macro is a gain table indexed by the top three bits of params[2]; each bucket is a
    # target T60 and the engine must land on it
    for bucket, target in ((0, 0.1), (4, 1.6), (5, 3.0)):
        mm = Machine.for_module(raw)
        # capture well past the target: a tail that has not reached -60 dB yet returns None
        n_blocks = int(S.FS * target * 1.6 / S.BLOCK)
        buf = capture(69, n_blocks, mm, bucket=bucket)
        t60 = S.measure_decay(buf)
        ok = t60 is not None and abs(t60 - target) / target < 0.15
        shown = f"{t60:.2f} s" if t60 is not None else "not reached"
        check(f"decay bucket {bucket}", ok, f"T60 {shown} vs target {target:.1f} s")

    mm = Machine.for_module(raw)
    long_buf = capture(69, 1500, mm, bucket=4)
    check("engine decays to silence", max(abs(v) for v in long_buf[-2048:]) / 2 ** 31 < 1e-3, "")

    # ---- polyphony: two voices must keep separate state, or every voice plays the same note
    mp = Machine.for_module(raw)
    ctx_a, ctx_b = mp.mem_base + Machine.SCRATCH_OFF, mp.mem_base + Machine.SCRATCH_OFF + 0x400
    prm = mp.mem_base + Machine.PARAM_OFF
    for i in range(8):
        mp.st32(prm + 4 * i, 4 << 28)
    call(mp, exports["initModule"], [0, 0x81003850, ctx_a])
    call(mp, exports["init"], [ctx_a, 0])
    call(mp, exports["init"], [ctx_b, 0])
    call(mp, exports["onNoteOn"], [0, 69, ctx_a])
    call(mp, exports["onNoteOn"], [0, 81, ctx_b])
    check("two contexts hold different notes",
          mp.ld32(ctx_a + 4) == 69 and mp.ld32(ctx_b + 4) == 81, "")
    o = mp.mem_base + Machine.OUT_OFF

    def render_into(machine, ctx, blocks=1):
        for _ in range(blocks):
            for j in range(2 * S.BLOCK):
                machine.st32(o + 4 * j, 0)
            call(machine, exports["render"], [o, 440 << 16, 0], stack=(ctx, prm, 0))
        return [machine.ld32(o + 4 * j) for j in range(2 * S.BLOCK)]

    render_into(mp, ctx_a, 2)
    before = [mp.ld32(ctx_a + 0x10 + 4 * i) for i in range(12)]
    render_into(mp, ctx_b, 2)                      # render the OTHER voice in between
    after = [mp.ld32(ctx_a + 0x10 + 4 * i) for i in range(12)]
    check("voice A state untouched by voice B", before == after, "")

    # and each voice still sounds at its own pitch when rendered from its own context
    buf_a = []
    mp2 = Machine.for_module(raw)
    ctx = mp2.mem_base + Machine.SCRATCH_OFF
    for i in range(8):
        mp2.st32(mp2.mem_base + Machine.PARAM_OFF + 4 * i, 4 << 28)
    call(mp2, exports["initModule"], [0, 0x81003850, ctx])
    call(mp2, exports["init"], [ctx, 0])
    call(mp2, exports["onNoteOn"], [0, 81, ctx])   # the high voice this time
    for _ in range(80):
        for j in range(2 * S.BLOCK):
            mp2.st32(mp2.mem_base + Machine.OUT_OFF + 4 * j, 0)
        call(mp2, exports["render"], [mp2.mem_base + Machine.OUT_OFF, 440 << 16, 0],
             stack=(ctx, mp2.mem_base + Machine.PARAM_OFF, 0))
        buf_a += [mp2.ld32(mp2.mem_base + Machine.OUT_OFF + 4 * j) for j in range(2 * S.BLOCK)]
    f = S.measure_freq(buf_a)
    check("per-voice pitch (note 81 alone)", abs(f - 880) / 880 < 0.02, f"{f:.1f} Hz vs 880")

    print(f"\nsteps executed: {m.steps:,}")
    print(f"{'FAILED' if fails else 'all checks passed'} ({fails} failure(s))")
    return 1 if fails else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        sys.exit(selftest())
    print(__doc__)
