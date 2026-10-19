#!/usr/bin/env python3
"""Build a sustained, multi-rank cathedral-organ OP-Z engine.

Six phase-coherent pipe ranks (16′, 8′, 4′, 2 2/3′, 2′ and 1 1/3′) are mixed per voice.
Each voice is independent and sustains while the OS amp gate is active. Add the OP-Z's reverb
track effect for the cathedral tail; this engine itself stays a compact, dry organ source.
"""
import math, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzasm as A
import opzengine as E
import opzmarimba as S

# Slots 74-76 are free in the factory map; this placement avoids both custom modules and factory engines.
MOD_BASE   = 0x81BE4C00 + (74 - 61) * 0x1400  # memoryslot 74
CODE_BASE  = MOD_BASE + 0x38
CODE_RESERVE = 0x1000                    # code area kept fixed so the data address never moves
SLOT_SPAN  = 0x1400 * 3                  # slots 74-76
DATA_BASE  = CODE_BASE + CODE_RESERVE
FS        = S.FS

D_STRIKE = DATA_BASE + 0x10         # six harmonic excitation levels
D_TABLE  = DATA_BASE + 0x60         # 128 notes x 6 pipe ranks x (c, s)
D_FREQ   = DATA_BASE + 0x1860       # 128 notes' frequencies in Q16 Hz
N_MODES = 6
def strike_seeds():
    """Balanced drawbar-like levels; the 16′ and 8′ ranks carry the body."""
    return [0.085, 0.145, 0.105, 0.070, 0.050, 0.035]


def coefficient_table():
    """Undamped pipe-rank partials across six organ stops."""
    ratios = (0.5, 1.0, 2.0, 3.0, 4.0, 6.0)
    rows = []
    for note in range(128):
        f0 = 440.0 * 2 ** ((note - 69) / 12.0)
        for ratio in ratios:
            f = f0 * ratio
            if f > FS * 0.45:
                rows.append((0, 0))
                continue
            w = 2.0 * math.pi * f / FS
            rows.append((S.to_q31(math.cos(w)), S.to_q31(math.sin(w))))
    return rows


def build():
    c = A.Code(CODE_BASE)

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
    c.emit(A.logic32("R6", "R1", "R1", "|")) # R6 = arg2, the pitch in Q16 Hz
    c.emit(A.logic32("R7", "R2", "R2", "|")) # retain arg3 glide delta until pitch interpolation

    # Arguments 4-6 are on the stack; the seven saved registers are 28 bytes, so seven loads reach arg4.
    c.emit(A.regmv("P0", "SP"))
    for _ in range(7):
        c.emit(A.ldst("P0", "R0"))
    c.emit(A.ldst("P0", "R2"))               # R2 = ctx
    c.emit(A.regmv("P3", "R2"))
    c.emit(A.ldst("P0", "R0"))               # params: the fixed rank mix has no macro controls
    c.emit(A.ldst("P0", "R5"))               # amp

    # The OS writes amp+0x08 as velocity gain and keeps the current envelope at
    # record+0x160 == ctx+0x118; apply both to the output, rather than treating amp as only a gate.
    c.ins("cmp_eq0", "R5")
    c.branch("amp_ok", cond=False)
    c.ins("ldimm32", "R4", 0x7FFFFFFF)       # null amp: unity velocity gain
    c.jump("save_velocity")
    c.label("amp_ok")
    c.emit(A.regmv("P0", "R5"))
    for _ in range(4):
        c.emit(A.ldst("P0", "R0"))
    c.emit(A.ldst("P0", "R0", aop=2))        # amp+0x10: the OS voice gate
    c.ins("cmp_eq0", "R0")
    c.branch("amp_active", cond=False)
    c.emit(A.regmv("P0", "P3"))
    c.ins("ldimm7", "R1", 0)
    c.emit(A.ldst("P0", "R1", store=True, aop=2))
    c.jump("done")
    c.label("amp_active")
    c.emit(A.regmv("P0", "R5"))
    for _ in range(2):
        c.emit(A.ldst("P0", "R0"))
    c.emit(A.ldst("P0", "R4"))               # amp+0x08: velocity gain, Q31
    c.label("save_velocity")
    c.emit(A.regmv("P0", "P3"))
    for _ in range(28):
        c.emit(A.ldst("P0", "R0"))           # ctx+0x70: this voice's velocity gain
    c.emit(A.ldst("P0", "R4", store=True, aop=2))
    c.jump("vstart")

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
    c.ins("ldimm7", "R1", 0)                 # y2 starts at rest
    for _ in range(N_MODES):
        c.emit(A.ldst("P1", "R0"))           # seed for this mode
        c.emit(A.ldst("P0", "R0", store=True))   # y1 = seed
        c.emit(A.ldst("P0", "R1", store=True))   # y2 = 0
    c.label("playing")

    # The OS supplies pitch plus a per-sample glide increment. Use the block midpoint and interpolate
    # between adjacent semitone coefficient rows, so pitch bend/glide is smooth rather than quantized.
    c.emit(A.shl("R4", "R7", 5))
    c.emit(A.addsub32("R6", "R6", "R4", "+"))
    c.ins("cmp_eq0", "R6")
    c.branch("zero_pitch", cond=True)
    c.jump("pitch_valid")
    c.label("zero_pitch")
    c.jump("idle_pitch")
    c.label("pitch_valid")

    # Clamp below/above the table explicitly; in particular note 127 must select its own row.
    c.ins("ldimm32", "P0", D_FREQ)
    c.emit(A.ldst("P0", "R1"))
    c.emit(A.comp_lt("R6", "R1"))
    c.branch("pitch_low", cond=True)
    c.ins("ldimm32", "P0", D_FREQ + 127 * 4)
    c.emit(A.ldst("P0", "R1", aop=2))
    c.emit(A.comp_lt("R6", "R1"))
    c.branch("pitch_high", cond=False)

    # Find adjacent frequency rows; then compute a Q16 interpolation fraction with restoring division.
    c.ins("ldimm7", "R5", 0)                 # lo
    c.ins("ldimm32", "R2", 127)              # hi
    c.ins("ldimm32", "R3", D_FREQ)
    c.label("psearch")
    c.emit(A.addsub32("R0", "R2", "R5", "-"))
    c.ins("ldimm7", "R1", 1)
    c.emit(A.addsub32("R0", "R0", "R1", "-"))
    c.ins("cmp_eq0", "R0")
    c.branch("found", cond=True)
    c.emit(A.addsub32("R0", "R5", "R2", "+"))
    c.emit(A.shr("R0", "R0", 1))
    c.emit(A.shl("R1", "R0", 2))
    c.emit(A.addsub32("R4", "R3", "R1", "+"))
    c.emit(A.regmv("P0", "R4"))
    c.emit(A.ldst("P0", "R1", aop=2))
    c.emit(A.comp_lt("R6", "R1"))
    c.branch("ps_hi", cond=True)
    c.emit(A.logic32("R5", "R0", "R0", "|"))
    c.jump("psearch")
    c.label("ps_hi")
    c.emit(A.logic32("R2", "R0", "R0", "|"))
    c.jump("psearch")
    c.label("found")
    c.emit(A.shl("R0", "R5", 2))
    c.emit(A.addsub32("R4", "R3", "R0", "+"))
    c.emit(A.regmv("P0", "R4"))
    c.emit(A.ldst("P0", "R0", aop=2))       # FREQ[lo]
    c.emit(A.shl("R1", "R2", 2))
    c.emit(A.addsub32("R4", "R3", "R1", "+"))
    c.emit(A.regmv("P0", "R4"))
    c.emit(A.ldst("P0", "R1", aop=2))       # FREQ[hi]
    c.emit(A.addsub32("R4", "R6", "R0", "-"))  # remainder = pitch - FREQ[lo]
    c.emit(A.addsub32("R1", "R1", "R0", "-"))  # divisor = FREQ[hi] - FREQ[lo]
    c.ins("ldimm7", "R3", 0)                 # 16-bit fractional quotient
    for bit in range(16):
        c.emit(A.shl("R4", "R4", 1))
        c.emit(A.shl("R3", "R3", 1))
        c.emit(A.comp_lt("R4", "R1"))
        c.branch(f"frac_skip_{bit}", cond=True)
        c.emit(A.addsub32("R4", "R4", "R1", "-"))
        c.ins("ldimm7", "R0", 1)
        c.emit(A.logic32("R3", "R3", "R0", "|"))
        c.label(f"frac_skip_{bit}")
    c.jump("coefficients")
    c.label("pitch_low")
    c.ins("ldimm7", "R5", 0)
    c.ins("ldimm7", "R2", 1)
    c.ins("ldimm7", "R3", 0)
    c.jump("coefficients")
    c.label("pitch_high")
    c.ins("ldimm32", "R5", 127)
    c.ins("ldimm32", "R2", 127)
    c.ins("ldimm7", "R3", 0)

    # Interpolate each rank's cosine/sine pair into per-voice scratch at ctx+0x40. The three pointers
    # must stay distinct: P1 reads the lower row, P2 the upper row, P0 writes the scratch. Reusing one of
    # the row pointers for the scratch made every interpolated coefficient zero (the scratch is zero on
    # entry), which collapsed the oscillator state to zero on the first frame - silence.
    c.label("coefficients")
    c.emit(A.shl("R3", "R3", 15))             # Q16 fraction -> Q31
    c.emit(A.shl("R0", "R5", 4))
    c.emit(A.shl("R1", "R5", 5))
    c.emit(A.addsub32("R0", "R0", "R1", "+"))
    c.ins("ldimm32", "R4", D_TABLE)
    c.emit(A.addsub32("R4", "R4", "R0", "+"))
    c.emit(A.regmv("P1", "R4"))               # lower coefficient row
    c.emit(A.shl("R0", "R2", 4))
    c.emit(A.shl("R1", "R2", 5))
    c.emit(A.addsub32("R0", "R0", "R1", "+"))
    c.ins("ldimm32", "R4", D_TABLE)
    c.emit(A.addsub32("R4", "R4", "R0", "+"))
    c.emit(A.regmv("P2", "R4"))               # upper coefficient row
    c.emit(A.regmv("P0", "P3"))
    for _ in range(16):
        c.emit(A.ldst("P0", "R0"))            # P0 = ctx+0x40 scratch
    for _ in range(N_MODES):
        c.emit(A.ldst("P1", "R0"))            # lower c
        c.emit(A.ldst("P1", "R1"))            # lower s
        c.emit(A.ldst("P2", "R2"))            # upper c
        c.emit(A.ldst("P2", "R4"))            # upper s
        c.emit(A.addsub32("R5", "R2", "R0", "-"))
        c.emit(A.mul32("R5", "R5", "R3"))
        c.emit(A.addsub32("R5", "R5", "R5", "+"))
        c.emit(A.addsub32("R0", "R0", "R5", "+"))
        c.emit(A.ldst("P0", "R0", store=True))
        c.emit(A.addsub32("R5", "R4", "R1", "-"))
        c.emit(A.mul32("R5", "R5", "R3"))
        c.emit(A.addsub32("R5", "R5", "R5", "+"))
        c.emit(A.addsub32("R1", "R1", "R5", "+"))
        c.emit(A.ldst("P0", "R1", store=True))

    # Combine the OS envelope level (record+0x160 == ctx+0x118) with the note velocity gain. Both live at
    # ctx+0x70, which sits just past the twelve interpolated coefficient words.
    c.emit(A.regmv("P0", "P3"))
    for _ in range(70):
        c.emit(A.ldst("P0", "R1"))
    c.emit(A.ldst("P0", "R0", aop=2))      # current envelope, Q31
    c.emit(A.regmv("P0", "P3"))
    for _ in range(28):
        c.emit(A.ldst("P0", "R1"))
    c.emit(A.ldst("P0", "R1", aop=2))      # saved amp+0x08 velocity gain
    c.emit(A.mul32("R0", "R0", "R1"))
    c.emit(A.addsub32("R0", "R0", "R0", "+"))
    c.emit(A.ldst("P0", "R0", store=True, aop=2))  # ctx+0x70 combined gain
    c.emit(A.regmv("P4", "P3"))            # stable gain pointer, per voice
    for _ in range(28):
        c.emit(A.ldst("P4", "R1"))         # ctx+0x70

    c.emit(A.regmv("P0", "P3"))
    for _ in range(4):
        c.emit(A.ldst("P0", "R1"))         # ctx+0x10 state
    c.emit(A.regmv("P2", "P0"))
    c.emit(A.regmv("P1", "P3"))
    for _ in range(16):
        c.emit(A.ldst("P1", "R1"))         # ctx+0x40 interpolated coefficients
    c.ins("ldimm32", "R6", 64)              # 64 frames per block

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
    c.emit(A.ldst("P4", "R5", aop=2))       # combined velocity/envelope gain
    c.emit(A.mul32("R5", "R7", "R5"))
    c.emit(A.addsub32("R7", "R5", "R5", "+"))
    c.emit(A.ldst("P5", "R7", store=True))   # left
    c.emit(A.ldst("P5", "R7", store=True))   # right
    c.ins("ldimm7", "R0", 1)
    c.emit(A.addsub32("R6", "R6", "R0", "-"))

    # Rewind state and interpolated coefficient pointers for the next sample.
    c.emit(A.regmv("P0", "P3"))
    for _ in range(16):
        c.emit(A.ldst("P0", "R0"))           # ctx+0x40 coefficient scratch
    c.emit(A.regmv("P1", "P0"))
    c.emit(A.regmv("P0", "P3"))
    for _ in range(4):
        c.emit(A.ldst("P0", "R0"))           # ctx+0x10 state
    c.emit(A.regmv("P2", "P0"))
    c.ins("cmp_eq0", "R6")
    c.branch("frame", cond=False)

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
    for m, seed in enumerate(strike_seeds()):
        data[0x10 + 4 * m:0x14 + 4 * m] = (S.to_q31(seed) & 0xFFFFFFFF).to_bytes(4, "little")
    for cc, ss in coefficient_table():
        data += (cc & 0xFFFFFFFF).to_bytes(4, "little")
        data += (ss & 0xFFFFFFFF).to_bytes(4, "little")
    # The pitch argument is Q16 Hz (doc 11 §11.9), and the OS derives it from its own semitone table, so a
    # search over these thresholds lands exactly on a row for every real note. One row per semitone.
    for note in range(128):
        data += int(round(440.0 * 2 ** ((note - 69) / 12.0) * 65536)).to_bytes(4, "little")

    payload = len(hdr) + len(code) + len(data)
    # Nothing else checks this: a table that grew past the slot would overwrite reverb's module at
    # 0x81beb000 instead of failing the build.
    assert payload <= SLOT_SPAN, f"module is {payload} B, past its {SLOT_SPAN} B slot span"
    segs = [
        (0x5000, 0x11A00000, 0, payload, b""),
        (0x0000, MOD_BASE,   len(hdr),  0, bytes(hdr)),
        (0x0000, CODE_BASE,  len(code), 0, code),
        (0x0000, DATA_BASE,  len(data), 0, bytes(data)),
        (0x8000, 0x11A00000, 0, 0, b""),
    ]
    return E.pack(segs), c, len(hdr), len(code), len(data)


if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "cathedral.engine")
    raw, c, hl, cl, dl = build()
    out.write_bytes(raw)
    print(f"wrote {out} ({len(raw)} B)")
    print(f"  header {hl} B @0x{MOD_BASE:08x}   code {cl} B @0x{CODE_BASE:08x}   data {dl} B @0x{DATA_BASE:08x}")
    print(f"  module span 0x{MOD_BASE:08x}..0x{MOD_BASE + hl + cl + dl:08x}  (memoryslot 74, three 0x1400 slots)")
    print("  exports: " + ", ".join(f"{k}=0x{v:08x}" for k, v in c.labels.items()))
    mod = E.read_module(raw)
    print("  container round-trip: " + ("parsed OK" if mod else "PARSE FAILED"))
    if mod:
        for name, addr in mod["exports"]:
            print(f"    {name:12s} 0x{addr:08x}")
