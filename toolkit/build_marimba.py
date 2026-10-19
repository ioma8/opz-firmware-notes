#!/usr/bin/env python3
"""build_marimba.py - emit the "marimba body" .engine module.

Assembles the modal resonator with toolkit/opzasm.py (every encoding verified against factory bytes),
builds the 56-byte module header and the segment list, and writes a loadable `.engine`.

Design, and why each choice was forced:

* **Per-voice state, in the context the OS passes in.** The first build kept state in module globals, which
  is wrong the moment the OS runs more than one voice: every voice would play the same note. All state now
  lives in the context handed to `init` (arg 1), `onNoteOn` (arg 3) and `render` (arg 4):

      +0x00 gate          +0x10 state[6][2]  (y1, y2 per mode)
      +0x04 note          ...
      +0x08 coefficient row pointer (saved so it can be rewound each block)
      +0x0c reserved

  Only the coefficient and gain tables stay in module data, where they are read-only and shared.
* **A 128-entry coefficient table indexed directly by MIDI note.** The table is computed at build time
  by toolkit/opzmarimba.py, so the engine contains no transcendentals at all - a note is an index, not
  a computation - and no clamping is needed for the legal 0..127 range.
* **Only verified instruction forms.** opzasm raises `Unsupported` rather than guessing, so a mistake
  fails the build instead of producing a module that loads and misbehaves.
* **Volatile registers only, plus the verified push/pop pair** for the registers render() must borrow.
* **A voice comes alive from render's own arguments**, never from `onNoteOn`: pitch is argument 2, and
  the amp object's state word (argument 6, +0x10) says whether the OS still wants this voice. The strike
  is seeded when that state goes from idle to active. `onNoteOn` is still exported - the loader requires
  it - but it only asks for a re-strike. This is what makes the engine polyphonic: every voice record the
  OS ticks has its own context, pitch and amp, so N records sound N notes.

Known limitations, stated rather than hidden:
  - the decay macro is read from params[PARAM_DECAY], and that index is still not confirmed on hardware.
    params[2] is the wrong place for it: doc `11` §11.9 shows `chord` passing params[2..5] to the OS
    parameter-smoothing service (host_table[7]), so those four are the amp/envelope arguments, not
    engine knobs, while the sibling port's param map records params[0] and params[1] as the two
    entries every ported engine reads. The mechanism is right (argument 5 is a stack argument, walked
    with post-increment loads because the encoder has no displacement load) and the mapping is accurate
    - buckets land within 1% of their target T60 - but which knob the OS binds to params[1] is still an
    assumption;
  - the strike position is fixed at 0.22 (baked into the seed table), not a live macro;
  - pitch comes from render's argument 2 (Q16 Hz) and the row is the NEAREST semitone, found with a
    seven-step binary search over the build-time frequency table. The OS derives that argument from its
    own semitone table, so for every real note the match is exact; during a pitch glide the row quantises
    to the nearest semitone (up to 50 cents) and `bend`, argument 3, is ignored. Interpolating between
    adjacent rows would remove that, and is the next thing to do if glides ever matter;
  - `mul32` emits the (T) extraction, and that extraction is `>> 32` rather than the `>> 31` of a Q31
    fractional multiply (SLEIGH's `rounding(..., 4)` clears four bytes). Every multiply therefore
    returns half scale and each mode output is doubled with one add, mirroring `frac_q31()` in
    opzmarimba.py, which implements the same arithmetic and passes its measurement checks;
  - the engine has no level control beyond the amp gate. Host entry 7 is the OS parameter-smoothing
    service that fills the amp object's current value (doc `11` §11.9), and `chord` calls it every block;
    this engine does not, so velocity, track volume and the envelope's own level are not applied here.
    Calling into the OS is exactly what a harness cannot verify, so the gap is stated rather than guessed
    - and `params[11]`, which the sibling port treats as level, is deliberately not multiplied in, because
    a wrong guess there would silence the engine;
  - the per-block decay factor is one module word (`D_G`), written and read inside a single render call.
    That is safe only because the OS ticks voices sequentially; a re-entrant or threaded caller would see
    another voice's gain. Moving it into the context costs sixteen pointer increments per block, which is
    why it is documented instead of paid for.
"""
import math, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzasm as A
import opzengine as E
import opzmarimba as S

# Placement is derived, not guessed. In the factory set the slot -> address rule is linear over
# slots 59..89 (every one of the fourteen engines in that range fits base = 0x81be4c00 +
# (slot-61)*0x1400), and the arena is a grid of 0x1400-byte slots. Slot 63 is unused and its three
# slots end exactly where reverb (slot 66) begins, so the engine lands in a real gap:
#   0x81be7400 .. 0x81be9cc8   (digital ends at 0x81be6a80, reverb starts at 0x81beb000)
MOD_BASE   = 0x81BE7400  # memoryslot 63
CODE_BASE  = MOD_BASE + 0x38
CODE_RESERVE = 0x1000                    # code area kept fixed so the data address never moves
DATA_BASE  = CODE_BASE + CODE_RESERVE
FS        = S.FS

D_STRIKE = DATA_BASE + 0x10         # 6 per-mode excitation seeds (the strike comb)
D_G      = DATA_BASE + 0x2C         # the block's decay factor; see the note in render
D_TABLE  = DATA_BASE + 0x60         # 128 notes x 6 modes x (c, s)
D_GAINS  = DATA_BASE + 0x1860       # 8 per-block decay factors, selected by the decay macro
D_FREQ   = DATA_BASE + 0x1880       # 128 notes' frequencies in Q16 Hz, the pitch search's index
T60_LONG = 8.0                      # the table's own damping; the macro shortens from here
PARAM_DECAY = 1                     # params[1]: read by every ported engine, unlike params[2..5]
N_MODES = 6
STRIKE_POS = 0.22                   # a marimba bar is struck near one end, not at 0.3


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
    """(c, s) = r*(cos w, sin w) per MIDI note per mode, straight from opzmarimba's maths."""
    rows = []
    for note in range(128):
        f0 = 440.0 * 2 ** ((note - 69) / 12.0)
        for m in range(N_MODES):
            f = f0 * S.MARIMBA[m]
            if f > FS * 0.45:
                rows.append((0, 0))
                continue
            w = 2.0 * math.pi * f / FS
            # Mode 0's radius stays 1.0 so the per-block gain owns the whole tail and the decay
            # buckets stay exact. Every upper mode carries its OWN radius, because a wooden bar's
            # overtones die in a fraction of a second whatever the knob is doing - that quick,
            # independent decay is what separates a knock from a bell.
            t60 = S.MARIMBA_T60[m]
            r = 1.0 if t60 == 0.0 else math.exp(-math.log(1000.0) / (t60 * FS))
            rows.append((S.to_q31(r * math.cos(w)), S.to_q31(r * math.sin(w))))
    return rows


def build():
    c = Code(CODE_BASE)

    # ---------------------------------------------------------- initModule(id, host_table, out)
    c.label("initModule")
    c.ins("cmp_eq0", "R0")
    c.branch("im_fail", cond=False)        # id != 0 -> refuse (the OS passes 0)
    # The host services table (R1) is deliberately not kept: this engine calls no host service, so a
    # stored pointer would be dead data. A module that does call one must save it here.
    c.emit(A.regmv("P0", "R2"))
    c.ins("ldimm7", "R0", 0)
    c.emit(A.ldst("P0", "R0", store=True, aop=2))    # *out = 0
    c.ins("ldimm7", "R0", 1)
    c.emit(A.rts())
    c.label("im_fail")
    c.ins("ldimm7", "R0", 0)
    c.emit(A.rts())

    # ---------------------------------------------------------- init(ctx, variant)
    # Every note's state lives in the context the OS passes in, not in module globals: the OS calls
    # render() once per voice, so global state would make every voice play the same note.
    c.label("init")
    c.emit(A.regmv("P0", "R0"))              # ctx is argument 1
    c.ins("ldimm7", "R1", 0)
    for _ in range(16):                      # 0x40 bytes: gate, note, rowp, reserved, 12 state words
        c.emit(A.ldst("P0", "R1", store=True))
    c.emit(A.rts())

    # ---------------------------------------------------------- onNoteOn(a1, note, ctx, a4)
    # The note-store and the strike moved into render: on the device this export is not what starts a
    # note (doc 11 §11.9), so a voice must never depend on having been called. It only asks render to
    # re-strike, which is what a live keyboard note wants.
    c.label("onNoteOn")
    c.emit(A.regmv("P0", "R2"))              # ctx is argument 3
    c.ins("ldimm7", "R3", 0)
    c.emit(A.ldst("P0", "R3", store=True))   # +0x00 = 0: not struck yet
    c.emit(A.ldst("P0", "R1", store=True))   # +0x04 the note, bookkeeping only
    c.emit(A.rts())

    # ---------------------------------------------------------- onNoteOff(a1, ctx)
    c.label("onNoteOff")
    c.emit(A.regmv("P0", "R1"))              # ctx is argument 2 (see doc 11 section 11.16)
    c.ins("ldimm7", "R2", 1)
    c.emit(A.ldst("P0", "R2", store=True))   # +0x00 = 1: struck, so render will not restart the note
    c.ins("ldimm7", "R2", 0)
    for _ in range(15):                      # +0x04 .. +0x3f: zero the state, so the voice is silent
        c.emit(A.ldst("P0", "R2", store=True))
    c.emit(A.rts())

    # ---------------------------------------------------------- render(out, freq, off, ctx, params, env)
    c.label("render")
    c.emit(A.push_r7_p5())
    c.emit(A.regmv("P5", "R0"))              # out: interleaved stereo, 64 frames
    c.emit(A.logic32("R6", "R1", "R1", "|")) # R6 = arg2, the pitch in Q16 Hz (R1 is volatile-only)

    # Arguments 4 and 5 are stack arguments and only the arguments are on the stack - the OS pushes no
    # extra frame word, so arg4 sits exactly where the callee's SP starts. The seven saved registers above
    # are 28 bytes, so seven discarded post-increment loads land on arg4 and the next read takes arg5.
    c.emit(A.regmv("P0", "SP"))
    for _ in range(7):
        c.emit(A.ldst("P0", "R0"))
    c.emit(A.ldst("P0", "R2"))               # R2 = ctx
    c.emit(A.regmv("P3", "R2"))              # ctx in P3; the push saved it
    c.emit(A.ldst("P0", "R1"))               # R1 = params
    c.emit(A.ldst("P0", "R5"))               # R5 = the amp object; the decay block below reuses R2

    # ---- decay macro: params[PARAM_DECAY] -> one of eight per-block gain buckets
    c.ins("cmp_eq0", "R1")
    c.branch("no_params", cond=True)         # a null pointer must not fault the whole device
    c.emit(A.regmv("P0", "R1"))
    for _ in range(PARAM_DECAY):
        c.emit(A.ldst("P0", "R2"))
    c.emit(A.ldst("P0", "R2"))
    # The knob's unit is not settled in the sources: the plug presets store eighteen values in 0..255, the
    # sibling port's parameter map records a byte baseline of 128, and its fixtures pass Q31 words. Reading
    # only the top bits is right for Q31 and permanently bucket 0 for a byte, i.e. a dead decay knob. So a
    # word below 256 is treated as a byte knob and normalised, and a Q31 word takes the old path unchanged.
    c.ins("ldimm32", "R4", 256)
    c.emit(A.comp_lt("R2", "R4"))            # CC = value < 256, unsigned
    c.branch("p_q31", cond=False)            # 256 and above: Q31, leave it alone
    c.emit(A.shr("R2", "R2", 5))             # byte knob 0..255 -> bucket 0..7, exact
    c.jump("p_bucket")
    c.label("p_q31")
    c.emit(A.shr("R2", "R2", 28))            # top four bits...
    c.ins("ldimm32", "R4", 7)
    c.emit(A.logic32("R2", "R2", "R4", "&")) # ...masked to three, or a negative word indexes past the table
    c.label("p_bucket")
    c.emit(A.shl("R3", "R2", 2))             # *4, the word stride of the gain table
    c.ins("ldimm32", "R4", D_GAINS)
    c.emit(A.addsub32("R4", "R4", "R3", "+"))
    c.emit(A.regmv("P0", "R4"))
    c.emit(A.ldst("P0", "R3"))
    c.jump("have_gain")
    c.label("no_params")
    c.ins("ldimm32", "R3", 0x7FFFFFFF)       # gain 1.0: apply no extra damping
    c.label("have_gain")
    c.ins("ldimm32", "R4", D_G)
    c.emit(A.regmv("P0", "R4"))
    c.emit(A.ldst("P0", "R3", store=True))

    # ---- amp object (argument 6). Every factory instrument render tests amp+0x10 first and returns when
    # it is zero (doc `11` §11.9), because the OS owns the voice: a released voice must cost nothing and
    # must not keep writing into the mix. A null pointer still renders, so a caller that passes only the
    # three register words behaves as it did before.
    c.ins("cmp_eq0", "R5")
    c.branch("amp_ok", cond=False)           # amp != 0 -> test its state word
    c.jump("vstart")
    c.label("amp_ok")
    c.emit(A.regmv("P0", "R5"))
    for _ in range(4):
        c.emit(A.ldst("P0", "R0"))
    c.emit(A.ldst("P0", "R0", aop=2))        # amp+0x10: the amp state machine, 0 = idle
    c.ins("cmp_eq0", "R0")
    c.branch("vstart", cond=False)           # active -> go and play
    # Idle means the OS released or has not yet started this voice. Clear "struck" so the next active
    # tick seeds the strike, then leave: an idle voice costs nothing and writes nothing.
    c.emit(A.regmv("P0", "P3"))
    c.ins("ldimm7", "R1", 0)
    c.emit(A.ldst("P0", "R1", store=True, aop=2))   # ctx+0x00 = 0
    c.jump("done")

    # ---- voice start. This is what makes the engine polyphonic: every voice record the OS renders has
    # its own context, its own pitch argument and its own amp object, and a strike is seeded from those
    # alone - so N records sound N notes without anything having to call onNoteOn per voice (doc 11
    # §11.9: the sequencer's note-start path calls init and render, not onNoteOn). The first build kept
    # the gate and the note in here and only onNoteOn ever set them, so a voice the OS started itself
    # stayed silent and the engine behaved monophonically.
    c.label("vstart")
    c.emit(A.regmv("P0", "P3"))
    c.emit(A.ldst("P0", "R0", aop=2))        # ctx+0x00: 0 = needs a strike
    c.ins("cmp_eq0", "R0")
    c.branch("playing", cond=False)          # already struck -> leave the ringing state alone
    c.emit(A.regmv("P0", "P3"))
    c.ins("ldimm7", "R1", 1)
    c.emit(A.ldst("P0", "R1", store=True))   # +0x00 = 1 (struck)
    for _ in range(3):                       # +0x04 note and +0x08 row are render's to fill, +0x0c reserved
        c.emit(A.ldst("P0", "R0"))           # P0 = ctx+0x10
    c.ins("ldimm32", "R0", D_STRIKE)         # the strike comb: a per-mode seed, not one seed for all
    c.emit(A.regmv("P1", "R0"))
    for _ in range(N_MODES):
        c.emit(A.ldst("P1", "R0"))           # seed for this mode
        c.emit(A.ldst("P0", "R0", store=True))   # y1 = seed
        c.emit(A.ldst("P0", "R1", store=True))   # y2 = 0
    c.label("playing")

    # ---- row pointer from the PITCH ARGUMENT, saved into the context so it can be rewound each frame.
    # A binary search over the 128 Q16-Hz thresholds: seven iterations whatever the note, no logarithm and
    # no state. The OS builds its pitch from its own semitone table, so the nearest row is the exact note
    # even though only the frequency is passed.
    # A zero pitch is "the OS has not set one yet", not "note 0": row 0 is 8.18 Hz, which would come out
    # as a sub-audio thump at full amplitude rather than as nothing.
    c.ins("cmp_eq0", "R6")
    c.branch("idle_pitch", cond=True)
    c.ins("ldimm7", "R5", 0)                 # lo
    c.ins("ldimm32", "R2", 127)              # hi
    c.ins("ldimm32", "R3", D_FREQ)           # base, untouched across the loop
    c.label("psearch")
    c.emit(A.addsub32("R0", "R2", "R5", "-"))    # hi - lo
    c.ins("ldimm7", "R1", 1)
    c.emit(A.addsub32("R0", "R0", "R1", "-"))    # 0 -> lo and hi are adjacent
    c.ins("cmp_eq0", "R0")
    c.branch("found", cond=True)
    c.emit(A.addsub32("R0", "R5", "R2", "+"))
    c.emit(A.shr("R0", "R0", 1))             # R0 = mid
    c.emit(A.shl("R1", "R0", 2))
    c.emit(A.addsub32("R4", "R3", "R1", "+"))    # &FREQ[mid]
    c.emit(A.regmv("P0", "R4"))
    c.emit(A.ldst("P0", "R1", aop=2))        # FREQ[mid]
    c.emit(A.comp_lt("R6", "R1"))            # CC = pitch < FREQ[mid], unsigned
    c.branch("ps_hi", cond=True)
    c.emit(A.logic32("R5", "R0", "R0", "|"))    # lo = mid
    c.jump("psearch")
    c.label("ps_hi")
    c.emit(A.logic32("R2", "R0", "R0", "|"))    # hi = mid
    c.jump("psearch")
    c.label("found")
    c.emit(A.shl("R2", "R5", 4))             # index * 16
    c.emit(A.shl("R3", "R5", 5))             # index * 32; together index * 48 without a multiply,
    c.emit(A.addsub32("R5", "R2", "R3", "+"))# since mul32 is a FRACTIONAL multiply
    c.ins("ldimm32", "R4", D_TABLE)
    c.emit(A.addsub32("R5", "R4", "R5", "+"))    # R5 = the coefficient row

    c.emit(A.regmv("P0", "P3"))
    c.emit(A.ldst("P0", "R0"))               # skip +0x00, P0 = ctx+0x04
    c.emit(A.ldst("P0", "R0"))               # skip +0x04 (the note), P0 = ctx+0x08
    c.emit(A.ldst("P0", "R5", store=True))   # ctx+0x08 = row, P0 = ctx+0x0c
    c.emit(A.ldst("P0", "R0"))               # skip reserved, P0 = ctx+0x10
    c.emit(A.regmv("P2", "P0"))              # writer trails the reader
    c.emit(A.regmv("P1", "R5"))              # P1 walks the coefficient row
    c.ins("ldimm32", "R6", 64)               # 64 frames per block

    c.label("frame")
    c.ins("ldimm7", "R7", 0)                 # accumulator
    for _ in range(N_MODES):
        c.emit(A.ldst("P0", "R0"))           # y1
        c.emit(A.ldst("P0", "R1"))           # y2
        c.emit(A.ldst("P1", "R2"))           # c
        c.emit(A.ldst("P1", "R3"))           # s
        c.emit(A.mul32("R4", "R2", "R0"))    # c*y1
        c.emit(A.mul32("R5", "R3", "R1"))    # s*y2
        c.emit(A.addsub32("R4", "R4", "R5", "-"))
        c.emit(A.addsub32("R4", "R4", "R4", "+"))   # >>32 extraction, doubled back into Q31
        c.emit(A.ldst("P2", "R4", store=True))
        c.emit(A.addsub32("R7", "R7", "R4", "+"))
        c.emit(A.mul32("R4", "R3", "R0"))    # s*y1
        c.emit(A.mul32("R5", "R2", "R1"))    # c*y2
        c.emit(A.addsub32("R4", "R4", "R5", "+"))
        c.emit(A.addsub32("R4", "R4", "R4", "+"))
        c.emit(A.ldst("P2", "R4", store=True))
    c.emit(A.ldst("P5", "R7", store=True))   # left
    c.emit(A.ldst("P5", "R7", store=True))   # right
    c.ins("ldimm7", "R0", 1)
    c.emit(A.addsub32("R6", "R6", "R0", "-"))

    # Rewind the per-frame walks. Order matters: reading the saved row pointer advances its pointer
    # by one word, so the state pointers must be set AFTER that read, not before it - getting this
    # backwards leaves P0 one word short of the state and the next frame reads the reserved word as
    # y1, which collapses the output within two blocks.
    c.emit(A.regmv("P0", "P3"))
    for _ in range(2):
        c.emit(A.ldst("P0", "R0"))           # skip gate and note, P0 = ctx+0x08
    c.emit(A.ldst("P0", "R1"))               # ctx+0x08 = the saved row pointer
    c.emit(A.regmv("P1", "R1"))
    c.emit(A.regmv("P0", "P3"))
    for _ in range(4):
        c.emit(A.ldst("P0", "R0"))           # P0 = ctx+0x10, the first state word
    c.emit(A.regmv("P2", "P0"))
    c.ins("cmp_eq0", "R6")
    c.branch("frame", cond=False)

    # The decay factor belongs to a BLOCK, not a sample: applying it inside the 64-sample loop made
    # it act 64 times per block (0.99885^64 = 0.929, a 7% collapse - measured, see doc 11 section 11.14).
    c.ins("ldimm32", "R0", D_G)
    c.emit(A.regmv("P4", "R0"))
    c.emit(A.ldst("P4", "R5"))               # R5 = gain
    c.emit(A.regmv("P0", "P3"))
    for _ in range(4):
        c.emit(A.ldst("P0", "R0"))
    c.emit(A.regmv("P2", "P0"))
    for _ in range(N_MODES * 2):
        c.emit(A.ldst("P0", "R0"))
        c.emit(A.mul32("R1", "R0", "R5"))
        c.emit(A.addsub32("R1", "R1", "R1", "+"))
        c.emit(A.ldst("P2", "R1", store=True))

    c.label("done")
    c.emit(A.pop_r7_p5())
    c.emit(A.rts())

    # After the epilogue, not before it: this block clears the struck flag, and falling into it on the way
    # to `done` would clear it every block - the voice would then re-strike from the same seeds forever
    # and its state would never advance (a constant per block, a 750 Hz block-rate spectrum).
    c.label("idle_pitch")
    c.emit(A.regmv("P0", "P3"))
    c.ins("ldimm7", "R1", 0)
    c.emit(A.ldst("P0", "R1", store=True, aop=2))   # ctx+0x00 = 0: a real note will strike
    c.jump("done")

    # names, in the code segment after the code
    names = {}
    for nm in ("initModule", "init", "render", "onNoteOn", "onNoteOff"):
        names[nm] = c.pos()
        c.emit(nm.encode() + b"\x00")
    code = c.finish()
    assert len(code) <= CODE_RESERVE, f"code grew past its reserved area: {len(code)} > {CODE_RESERVE}"

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
        gain = 0.42 ** m            # a marimba's fundamental dominates; 0.55^m was too bright
        seed = S.to_q31(0.125 * math.cos(math.pi * (m + 1) * STRIKE_POS) * gain)
        data[0x10 + 4 * m:0x14 + 4 * m] = (seed & 0xFFFFFFFF).to_bytes(4, "little")
    for cc, ss in coefficient_table():
        data += (cc & 0xFFFFFFFF).to_bytes(4, "little")
        data += (ss & 0xFFFFFFFF).to_bytes(4, "little")
    # eight buckets: per-block factor for a target T60, longest last so the top bucket barely damps
    for t60 in (0.1, 0.2, 0.4, 0.8, 1.6, 3.0, 5.0, T60_LONG):
        g = 10 ** (-3.0 * S.BLOCK / (t60 * FS))
        data += int(round(g * 2 ** 31)).to_bytes(4, "little")
    # The pitch argument is Q16 Hz (doc 11 §11.9), and the OS derives it from its own semitone table, so a
    # search over these thresholds lands exactly on a row for every real note. One row per semitone.
    for note in range(128):
        data += int(round(440.0 * 2 ** ((note - 69) / 12.0) * 65536)).to_bytes(4, "little")

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
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "marimba.engine")
    raw, c, hl, cl, dl = build()
    out.write_bytes(raw)
    print(f"wrote {out} ({len(raw)} B)")
    print(f"  header {hl} B @0x{MOD_BASE:08x}   code {cl} B @0x{CODE_BASE:08x}   data {dl} B @0x{DATA_BASE:08x}")
    print(f"  module span 0x{MOD_BASE:08x}..0x{MOD_BASE + hl + cl + dl:08x}  (memoryslot 63, three 0x1400 slots)")
    print("  exports: " + ", ".join(f"{k}=0x{v:08x}" for k, v in c.labels.items()))
    mod = E.read_module(raw)
    print("  container round-trip: " + ("parsed OK" if mod else "PARSE FAILED"))
    if mod:
        for name, addr in mod["exports"]:
            print(f"    {name:12s} 0x{addr:08x}")
