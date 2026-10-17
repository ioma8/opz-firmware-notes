#!/usr/bin/env python3
"""build_struck.py - emit the "struck body" .engine module.

Assembles the modal resonator with toolkit/opzasm.py (every encoding verified against factory bytes),
builds the 56-byte module header and the segment list, and writes a loadable `.engine`.

Design, and why each choice was forced:

* **Monophonic, state in the module's data segment.** The ABI hands each voice a context pointer, but a
  fixed data area keeps the engine away from stack arguments, whose offsets are where an unverifiable
  bug would hide. render() therefore reads only R0 (out) and R1 (frequency), both register args.
* **A 128-entry coefficient table indexed directly by MIDI note.** The table is computed at build time
  by toolkit/opzstruck.py, so the engine contains no transcendentals at all - a note is an index, not
  a computation - and no clamping is needed for the legal 0..127 range.
* **Only verified instruction forms.** opzasm raises `Unsupported` rather than guessing, so a mistake
  fails the build instead of producing a module that loads and misbehaves.
* **Volatile registers only, plus the verified push/pop pair** for the registers render() must borrow.

Known limitations, stated rather than hidden:
  - the decay macro is read from params[PARAM_DECAY], an index that has not been confirmed on hardware.
    The mechanism is right (argument 5 is a stack argument, walked with post-increment loads because the
    encoder has no displacement load) and the mapping is accurate - buckets land within 1% of their
    target T60 - but which entry of params[] the OS binds to the decay knob is an assumption. If it is
    wrong, the knob that moves the tail will be a different one;
  - the strike position is fixed at 0.3 (baked into the seed table), not a live macro;
  - `mul32` emits the (T) extraction, and that extraction is `>> 32` rather than the `>> 31` of a Q31
    fractional multiply (SLEIGH's `rounding(..., 4)` clears four bytes). Every multiply therefore
    returns half scale and each mode output is doubled with one add, mirroring `frac_q31()` in
    opzstruck.py, which implements the same arithmetic and passes its measurement checks.
"""
import math, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzasm as A
import opzengine as E
import opzstruck as S

MOD_BASE  = 0x81C0A000
CODE_BASE = MOD_BASE + 0x38
DATA_BASE = 0x81C0B000
FS        = S.FS

D_GATE   = DATA_BASE + 0x00
D_INDEX  = DATA_BASE + 0x04
D_HOST   = DATA_BASE + 0x08
D_STRIKE = DATA_BASE + 0x10         # 6 per-mode excitation seeds (the strike comb)
D_ROWP   = DATA_BASE + 0x28         # the coefficient row pointer, saved so it can be rewound
D_G      = DATA_BASE + 0x2C         # the decay factor chosen for this note
D_STATE  = DATA_BASE + 0x30         # 6 modes x (y1, y2) = 12 words
D_TABLE  = DATA_BASE + 0x60         # 128 notes x 6 modes x (c, s)
D_GAINS  = DATA_BASE + 0x1860       # 8 per-block decay factors, selected by the decay macro
T60_LONG = 8.0                      # the table's own damping; the macro shortens from here
PARAM_DECAY = 2                     # which entry of params[] carries the decay macro (assumption)
N_MODES = 6
T60     = 1.2


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
        self.emit(getattr(A, name)(*a, **k))

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
                enc = A.jump_s(here, self.labels[label])
            else:
                enc = A.brcc(here, self.labels[label], cond)
            self.buf[off:off + 2] = enc
        return bytes(self.buf)


def coefficient_table():
    """(c, s) = r*(cos w, sin w) per MIDI note per mode, straight from opzstruck's maths."""
    rows = []
    for note in range(128):
        f0 = 440.0 * 2 ** ((note - 69) / 12.0)
        for m in range(N_MODES):
            ratio = S.HARMONIC[m] + (S.BAR[m] - S.HARMONIC[m]) * 0.75
            f = f0 * ratio
            if f > FS * 0.45:
                rows.append((0, 0))
                continue
            w = 2.0 * math.pi * f / FS
            r = 1.0            # no damping here: the per-block gain below owns the whole tail
            rows.append((S.to_q31(r * math.cos(w)), S.to_q31(r * math.sin(w))))
    return rows


def build():
    c = Code(CODE_BASE)

    # ---------------------------------------------------------- initModule(id, host_table, out)
    c.label("initModule")
    c.ins("cmp_eq0", "R0")
    c.branch("im_fail", cond=False)        # id != 0 -> refuse (the OS passes 0)
    c.ins("ldimm32", "R0", D_HOST)
    c.emit(A.regmv("P0", "R0"))
    c.emit(A.ldst("P0", "R1", store=True, aop=2))    # save the host services table
    c.emit(A.regmv("P0", "R2"))
    c.ins("cmp_eq0", "R0")
    c.ins("ldimm7", "R0", 0)
    c.emit(A.ldst("P0", "R0", store=True, aop=2))    # *out = 0
    c.ins("ldimm7", "R0", 1)
    c.emit(A.rts())
    c.label("im_fail")
    c.ins("ldimm7", "R0", 0)
    c.emit(A.rts())

    # ---------------------------------------------------------- init: clear the mode state
    c.label("init")
    c.ins("ldimm32", "R0", D_STATE)
    c.emit(A.regmv("P0", "R0"))
    c.ins("ldimm7", "R1", 0)
    for _ in range(N_MODES * 2):
        c.emit(A.ldst("P0", "R1", store=True))
    c.emit(A.rts())

    # ---------------------------------------------------------- onNoteOn(a1, note, ctx, a4)
    c.label("onNoteOn")
    c.ins("ldimm32", "R0", D_INDEX)         # index = R1 (the note) -> the table row
    c.emit(A.regmv("P0", "R0"))
    c.emit(A.ldst("P0", "R1", store=True, aop=2))
    c.ins("ldimm32", "R0", D_GATE)
    c.emit(A.regmv("P0", "R0"))
    c.ins("ldimm7", "R1", 1)
    c.emit(A.ldst("P0", "R1", store=True, aop=2))    # gate = 1
    # strike: seed each mode from the comb table, so the excitation has the sign pattern of a
    # body hit at a fixed position (0.3) rather than every mode starting in phase
    c.ins("ldimm32", "R0", D_STRIKE)
    c.emit(A.regmv("P1", "R0"))
    c.ins("ldimm32", "R0", D_STATE)
    c.emit(A.regmv("P0", "R0"))
    c.ins("ldimm7", "R2", 0)
    for _ in range(N_MODES):
        c.emit(A.ldst("P1", "R1"))                   # seed for this mode
        c.emit(A.ldst("P0", "R1", store=True))       # y1 = seed
        c.emit(A.ldst("P0", "R2", store=True))       # y2 = 0
    c.emit(A.rts())

    # ---------------------------------------------------------- onNoteOff
    c.label("onNoteOff")
    c.ins("ldimm32", "R0", D_GATE)
    c.emit(A.regmv("P0", "R0"))
    c.ins("ldimm7", "R1", 0)
    c.emit(A.ldst("P0", "R1", store=True, aop=2))
    c.emit(A.rts())

    # ---------------------------------------------------------- render(out, freq_q16, ...)
    c.label("render")
    c.emit(A.push_r7_p5())
    c.emit(A.regmv("P5", "R0"))             # out buffer (interleaved stereo, 64 frames)

    # The decay macro lives in argument 5, a stack argument. The push above moved SP by 7 words,
    # so arg5 sits at SP+36; nine discarded post-increment loads walk there because the encoder
    # still has no displacement load (doc 11 section 11.12).
    c.emit(A.regmv("P0", "SP"))
    for _ in range(9):
        c.emit(A.ldst("P0", "R0"))
    c.emit(A.ldst("P0", "R1"))              # R1 = params pointer
    c.ins("cmp_eq0", "R1")
    c.branch("no_params", cond=True)        # a null pointer must not fault the whole device
    c.emit(A.regmv("P0", "R1"))
    for _ in range(PARAM_DECAY):
        c.emit(A.ldst("P0", "R2"))          # walk to params[PARAM_DECAY]
    c.emit(A.ldst("P0", "R2"))
    c.emit(A.shr("R2", "R2", 28))           # top three bits select one of eight buckets
    c.emit(A.shl("R3", "R2", 2))            # *4, the word stride of the gain table
    c.ins("ldimm32", "R4", D_GAINS)
    c.emit(A.addsub32("R4", "R4", "R3", "+"))
    c.emit(A.regmv("P0", "R4"))
    c.emit(A.ldst("P0", "R3"))              # R3 = the decay factor for this block
    c.jump("have_gain")
    c.label("no_params")
    c.ins("ldimm32", "R3", 0x7FFFFFFF)      # gain 1.0: keep the tail, apply no extra damping
    c.label("have_gain")
    c.ins("ldimm32", "R4", D_G)
    c.emit(A.regmv("P0", "R4"))
    c.emit(A.ldst("P0", "R3", store=True))  # remember it for the per-block state scaling
    c.ins("ldimm32", "R0", D_GATE)          # (P0 was borrowed, so reload the gate below)

    c.ins("ldimm32", "R0", D_GATE)          # if the gate is closed, this voice costs nothing
    c.emit(A.regmv("P0", "R0"))
    c.emit(A.ldst("P0", "R0", aop=2))
    c.ins("cmp_eq0", "R0")
    c.branch("done", cond=True)

    c.label("setup_ptr")                    # row = table + index*48 ; state pointers
    c.ins("ldimm32", "R0", D_INDEX)
    c.emit(A.regmv("P0", "R0"))
    c.emit(A.ldst("P0", "R2", aop=2))       # R2 = index
    # row = index * 48 bytes, built from shifts: mul32 is a FRACTIONAL multiply ((a*b)>>32), so using
    # it for integer arithmetic silently returns 0 and every note plays row 0
    c.emit(A.shl("R4", "R2", 4))            # index * 16
    c.emit(A.shl("R5", "R2", 5))            # index * 32
    c.emit(A.addsub32("R2", "R4", "R5", "+"))
    c.ins("ldimm32", "R3", D_TABLE)
    c.emit(A.addsub32("R3", "R3", "R2", "+"))
    c.emit(A.regmv("P1", "R3"))             # P1 walks the coefficient row
    c.emit(A.regmv("P0", "R3"))
    c.ins("ldimm32", "R4", D_ROWP)          # save the row pointer: P1 advances 96 bytes per frame
    c.emit(A.regmv("P4", "R4"))             # and must be put back at the start of the next one
    c.emit(A.ldst("P4", "R3", store=True, aop=2))
    c.ins("ldimm32", "R3", D_STATE)
    c.emit(A.regmv("P0", "R3"))             # P0 walks the state
    c.emit(A.regmv("P2", "R3"))             # P2 writes it back, trailing P0
    c.ins("ldimm32", "R6", 64)              # 64 frames per block

    c.label("frame")
    c.ins("ldimm7", "R7", 0)                # accumulator
    for _ in range(N_MODES):
        c.emit(A.ldst("P0", "R0"))          # y1
        c.emit(A.ldst("P0", "R1"))          # y2
        c.emit(A.ldst("P1", "R2"))          # c
        c.emit(A.ldst("P1", "R3"))          # s
        c.emit(A.mul32("R4", "R2", "R0"))   # c*y1
        c.emit(A.mul32("R5", "R3", "R1"))   # s*y2
        c.emit(A.addsub32("R4", "R4", "R5", "-"))    # y1' = c*y1 - s*y2
        # the (T) multiply extracts >>32, not the >>31 of a Q31 fractional multiply, so every
        # term comes back half scale and is doubled here - one add, mirroring frac_q31()
        c.emit(A.addsub32("R4", "R4", "R4", "+"))
        c.emit(A.ldst("P2", "R4", store=True))
        c.emit(A.addsub32("R7", "R7", "R4", "+"))    # acc += y1'
        c.emit(A.mul32("R4", "R3", "R0"))   # s*y1
        c.emit(A.mul32("R5", "R2", "R1"))   # c*y2
        c.emit(A.addsub32("R4", "R4", "R5", "+"))    # y2' = s*y1 + c*y2
        c.emit(A.addsub32("R4", "R4", "R4", "+"))    # same >>32 compensation
        c.emit(A.ldst("P2", "R4", store=True))
    c.emit(A.ldst("P5", "R7", store=True))           # left
    c.emit(A.ldst("P5", "R7", store=True))           # right
    c.ins("ldimm7", "R0", 1)
    c.emit(A.addsub32("R6", "R6", "R0", "-"))
    # rewind both walks: the state pointer pair, and the coefficient row pointer
    c.ins("ldimm32", "R0", D_STATE)
    c.emit(A.regmv("P0", "R0"))
    c.emit(A.regmv("P2", "R0"))
    c.ins("ldimm32", "R0", D_ROWP)
    c.emit(A.regmv("P4", "R0"))
    c.emit(A.ldst("P4", "R0", aop=2))
    c.emit(A.regmv("P1", "R0"))
    c.ins("cmp_eq0", "R6")
    c.branch("frame", cond=False)
    # The decay factor belongs to a BLOCK, not a sample: applying it inside the 64-sample loop made
    # it act 64 times per block (0.99885^64 = 0.929 - a 7% per-block collapse, which is exactly what
    # the simulator measured before this moved here).
    # Apply the decay factor to the mode state: one multiply per state word per block is the same
    # decay as scaling every sample, and it is what makes the decay macro move the tail.
    c.ins("ldimm32", "R0", D_G)
    c.emit(A.regmv("P4", "R0"))
    c.emit(A.ldst("P4", "R5"))                       # R5 = gain
    c.ins("ldimm32", "R0", D_STATE)
    c.emit(A.regmv("P0", "R0"))
    c.emit(A.regmv("P2", "R0"))
    for _ in range(N_MODES * 2):
        c.emit(A.ldst("P0", "R0"))
        c.emit(A.mul32("R1", "R0", "R5"))
        c.emit(A.addsub32("R1", "R1", "R1", "+"))    # >>32 extraction, doubled back
        c.emit(A.ldst("P2", "R1", store=True))
    c.label("done")
    c.emit(A.pop_r7_p5())
    c.emit(A.rts())

    # names, in the code segment after the code
    names = {}
    for nm in ("initModule", "init", "render", "onNoteOn", "onNoteOff"):
        names[nm] = c.pos()
        c.emit(nm.encode() + b"\x00")
    code = c.finish()

    hdr = bytearray()
    hdr += (0xFEED0AD1).to_bytes(4, "little")
    hdr += (0xAD1FACEF).to_bytes(4, "little")
    for nm in ("initModule", "init", "render", "onNoteOn", "onNoteOff"):
        hdr += names[nm].to_bytes(4, "little")
        hdr += c.labels[nm].to_bytes(4, "little")
    hdr += b"\x00" * 8          # the factory header is 56 B: five pairs end at 0x30, then two zero words
    assert len(hdr) == 56, len(hdr)

    data = bytearray(0x60)
    for m in range(N_MODES):
        gain = 0.55 ** m
        seed = S.to_q31(0.125 * math.cos(math.pi * (m + 1) * 0.3) * gain)
        data[0x10 + 4 * m:0x14 + 4 * m] = (seed & 0xFFFFFFFF).to_bytes(4, "little")
    for cc, ss in coefficient_table():
        data += (cc & 0xFFFFFFFF).to_bytes(4, "little")
        data += (ss & 0xFFFFFFFF).to_bytes(4, "little")
    # eight buckets: per-block factor for a target T60, longest last so the top bucket barely damps
    for t60 in (0.1, 0.2, 0.4, 0.8, 1.6, 3.0, 5.0, T60_LONG):
        g = 10 ** (-3.0 * S.BLOCK / (t60 * FS))
        data += int(round(g * 2 ** 31)).to_bytes(4, "little")

    payload = len(hdr) + len(code) + len(data)
    segs = [
        (0x5000, 0x11A00000, 0, payload, b""),
        (0x0000, MOD_BASE,   len(hdr),  0, bytes(hdr)),
        (0x0000, CODE_BASE,  len(code), 0, code),
        (0x0000, DATA_BASE,  len(data), 0, bytes(data)),
        (0x8000, 0x11A00000, 0, 0, b""),
    ]
    return E.pack(segs), c, len(hdr), len(code), len(data)


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "struck.engine")
    raw, c, hl, cl, dl = build()
    out.write_bytes(raw)
    print(f"wrote {out} ({len(raw)} B)")
    print(f"  header {hl} B @0x{MOD_BASE:08x}   code {cl} B @0x{CODE_BASE:08x}   data {dl} B @0x{DATA_BASE:08x}")
    print("  exports: " + ", ".join(f"{k}=0x{v:08x}" for k, v in c.labels.items()))
    mod = E.read_module(raw)
    print("  container round-trip: " + ("parsed OK" if mod else "PARSE FAILED"))
    if mod:
        for name, addr in mod["exports"]:
            print(f"    {name:12s} 0x{addr:08x}")
