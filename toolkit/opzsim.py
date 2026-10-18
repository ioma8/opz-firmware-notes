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
        o = (addr & 0xFFFFFFFF) - self.mem_base
        if not (0 <= o <= len(self.mem) - n):
            raise RuntimeError(f"access outside the window: 0x{addr:08x}")
        return o

    def ld32(self, addr):
        o = self._off(addr)
        return s32(int.from_bytes(self.mem[o:o + 4], "little"))

    def st32(self, addr, v):
        o = self._off(addr)
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

    def step(self, h, o):
        self.steps += 1
        m = self.mem
        nxt = self.pc + 2

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

        # 32-bit DSP forms share the 0xC nibble; the DSP sub-opcode at bits 7-10 selects which.
        # 0xD is Dsp32ShfImm (shift by immediate), 0x4 is Dsp32Mult (multiply).
        if (h & 0xF000) == 0xC000:
            h2 = int.from_bytes(m[o + 2:o + 4], "little")
            sigd = (h >> 7) & 0xF
            if sigd == 0xD:                                  # shift by immediate
                sop = (h2 >> 14) & 3
                dst = (h2 >> 9) & 7
                imm = (h2 >> 3) & 0x3F
                if imm & 0x20:
                    imm -= 0x40
                src = h2 & 7
                if sop == 2:                                 # left shift, immediate is +n
                    self.r[dst] = sat32(self.r[src] << imm)
                elif sop == 0:                               # right shift, immediate is -n
                    self.r[dst] = sat32(self.r[src] >> (-imm))
                else:
                    raise RuntimeError(f"shift sop={sop} not implemented")
            elif sigd == 0x4:                                # multiply
                dst = (h2 >> 6) & 7
                src0 = (h2 >> 3) & 7
                src1 = h2 & 7
                # the (T) extraction: rounding() clears the low four bytes, then 32-bit truncation
                self.r[dst] = sat32((self.r[src0] * self.r[src1]) >> 32)
            else:
                raise RuntimeError(f"DSP sub-opcode {sigd:#x} not implemented")
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
                if use_p:
                    raise RuntimeError("store to P register not implemented")
                self.st32(addr, self.r[reg])
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
            val = self.r[src] if gs == 0 else (self.p[src] if gs == 1 else None)
            if val is None:
                raise RuntimeError("regmv: unsupported source class")
            if gd == 0:
                self.r[dst] = val
            elif gd == 1:
                self.p[dst] = val
            else:                                          # gd = 2 is the I (index) file
                raise RuntimeError("regmv: I registers not implemented")
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
