#!/usr/bin/env python3
"""Drive every factory *instrument* from the vendor library and report which play.

Mirror of opzfxcheck.py for the instrument half. Engines are the 13 factory
instrument classes in ~/.opz-decode/opzso/libSnakePlugin.so, executed under
Unicorn through the loader in ~/projects/customs/opz-clone/tools/unicorn-harness.

Host data (this is the part that took longest to get right): engine globals must
be written at the addresses the loader uses, which are the Ghidra decompile's
addresses **minus 0x100000**. Writing at the Ghidra address silently does
nothing, and every engine then renders zeros.

usage: opzinstcheck.py [--blocks N] [--only NAME ...]
exits nonzero unless every instrument renders audio.
"""
import argparse, json, math, struct, sys
from pathlib import Path
from unicorn import UC_PROT_ALL
from unicorn.arm64_const import UC_ARM64_REG_X0

CLONE = Path.home() / "projects/customs/opz-clone"
sys.path.insert(0, str(CLONE / "tools/unicorn-harness"))
SO = Path.home() / ".opz-decode/opzso"
SYMS = SO / "syms.json"

INSTRUMENTS = ("AnalogA", "Chord", "Cluster", "Digital", "EP", "Electric", "Fm003b",
               "MiniStringShort", "Organ", "SamplePlayerGain", "Saw013a",
               "SynthSampler", "Volt")
FRAMES = 64
# Ghidra address - 0x100000. Gains and tables the instrument classes read.
GAINS = (0x124A5CC, 0x124A5D0, 0x124A5D4, 0x124A5D8, 0x124A5DC, 0x124A5E0,
         0x124A6F0, 0x124A718, 0x124A71C, 0x124A720, 0x124A724)
OCTAVE_TABLE = 0x124A658
CLUSTER_BANDS = (0x124A900, 0x124AA00)
# The whole host-data region these classes read: envelope-rate curves, octave and
# per-band gain tables. Left zero, every engine renders silence; filled with the
# i16 unity 0x7FFF they play. This is the single most load-bearing supply.
HOST_DATA = (0x124A500, 0x124C400)
# Data globals each class's render reads, taken from its decompile and corrected by
# -0x100000. The four consecutive dwords at the top of each block are the variant
# gain table, exactly as Digital's 0x124A5D0..0x124A5DC.
ENGINE_GLOBALS = {
    "SynthSampler":   (0x124A5CC, 0x124A6C0),
    "Volt":           (0x124A6F0, 0x124A718, 0x124A71C, 0x124A720, 0x124A724),
    "Electric":       (0x124A808, 0x124A830, 0x124A834, 0x124A838, 0x124A83C),
    "MiniStringShort": (0x124A8C0, 0x124A8DC, 0x124A8E0, 0x124A8E4, 0x124A8E8),
    "Organ":          (0x124AFD0, 0x124B310, 0x124B314, 0x124B318, 0x124B31C),
    "EP":             (0x124BEA0, 0x124C030, 0x124C064, 0x124C0A0, 0x124C120,
                       0x124C1A0, 0x124C1A4, 0x124C1A8, 0x124C1AC, 0x124C200),
}


def symbols():
    return json.loads(SYMS.read_text())["symbols"]


def find(syms, cls, frag):
    prefix = f"_ZN{len(cls)}{cls}"
    for s in syms:
        n = s.get("name", "")
        if n.startswith(prefix) and frag in n:
            return n
    return None


def supply(so, cls=""):
    """Host data every instrument gets: gains, gain tables and a wavetable."""
    for a in range(*HOST_DATA, 2):
        so.write(a, struct.pack("<h", 0x7FFF))
    # after the fill, so the i16 writes do not clobber the u32 globals inside it
    for g in GAINS + tuple(ENGINE_GLOBALS.get(cls, ())):
        so.write_u32(g, 0x7FFFFFFF)
    wav = so.alloc(8192 * 4)
    so.write_u32_array(wav, [int(math.sin(2 * math.pi * i / 8192) * 0x7FFFFFFF) & 0xFFFFFFFF
                             for i in range(8192)])
    so.write(so.interface + 0x18, struct.pack("<Q", wav))
    # AnalogAHost's contract: interface+0x28 points at FIVE pointers, each to a 16x65
    # fract32_t table (4160 bytes per bank, not one row). Zeroed buffers make every
    # filtered engine's signal path zero: with them AnalogA peaks at 1359, with Q31
    # sine tables at 303161490.
    banks = []
    for bank in range(5):
        b = so.alloc(16 * 65 * 4)
        scale = 0x7FFFFFFF >> (bank * 2)
        tbl = []
        for row in range(16):
            for i in range(65):
                ph = 2 * math.pi * (i + row * 65) / (16 * 65)
                tbl.append(int(math.sin(ph) * scale) & 0xFFFFFFFF)
        so.write_u32_array(b, tbl)
        banks.append(b)
    ptrs = so.alloc(5 * 8)
    for i, b in enumerate(banks):
        so.write_u64(ptrs + 8 * i, b)
    so.write(so.interface + 0x28, struct.pack("<Q", ptrs))
    # The samplers fetch their sample through interface+0x48: a 40-byte record whose
    # +0x00 is the data pointer, +0x08 the readable frame count, +0x0c pitch and
    # +0x10 rate. Without a record they log "sample player lost it's samples".
    # The sample must be recorded at the root pitch the record declares, or a sampler transposes from the
    # wrong rate: this is a 261.63 Hz sine (note 60 at 48 kHz) and the record's pitch field carries note 60
    # in the same unit the render argument uses. A period-64-table sample declared at the old unit played
    # 750 Hz and could never reach the requested note.
    root = 440.0 * 2 ** ((60 - 69) / 12.0)
    data = so.alloc(8192 * 4)
    so.write_u32_array(data, [int(math.sin(2 * math.pi * root * i / 48000.0) * 0x7FFFFFFF) & 0xFFFFFFFF
                              for i in range(8192)])
    rec = so.alloc(0x28)
    so.write(rec + 0x00, struct.pack("<Q", data))
    so.write_u32(rec + 0x08, 8192)
    so.write_u32(rec + 0x0C, increment_for(60))
    so.write_u32(rec + 0x10, 1 << 12)
    so.rec = rec                              # probes can vary the record's fields
    so.stub("samp", lambda s, n: s.reg_write(UC_ARM64_REG_X0, rec))
    so.write(so.interface + 0x48, struct.pack("<Q", so.stub_address("samp")))


from opzso import OpzSo, phase_increment  # noqa: E402  (needs CLONE on sys.path)


# The render's second argument is a phase increment for a 32-bit phase accumulator: one full cycle per
# 2**32, at the sample rate the render is being read at. The clone's `phase_increment()` returns a Q31
# increment computed for 44.1 kHz, which is low by 2 * 48000/44100 = 2.177 and made every engine play
# roughly half the requested frequency (Digital measured 140.6 Hz for a 261.6 Hz request, exactly the
# 2**32 reading of the argument it was given). So the increment is computed here from the request and the
# 48 kHz read rate instead, and no per-engine scale is needed.
# EP and Electric are the exception: with the 2**32 unit they play 2.177x sharp, i.e. their oscillator takes
# the older Q31-at-44.1-kHz unit that `phase_increment()` returns, so they keep that scale (48000/(2*44100)
# of the corrected increment = 0.5442). Measured, not assumed: at that scale EP scores 7.90 against
# neighbours 0.71/0.69 and Electric 25.05 against 1.24/0.83, while at the corrected unit they score 0.61 and
# 1.73 and lose.
PHASE_SCALE = {"EP": 0.5442, "Electric": 0.5442}


def increment_for(note, fs=48000.0):
    freq = 440.0 * 2 ** ((note - 69) / 12.0)
    return int(round(freq / fs * (1 << 32))) & 0xFFFFFFFF


def play(so, syms, cls, blocks, note=60):
    state, temp = so.alloc(0x1000), so.alloc(0x1000)
    params, adsr = so.alloc(0x100), so.alloc(0x40)
    out = so.alloc(FRAMES * 2 * 4)
    so.write_u32_array(params, [0] + [0x40404040] * 17)
    so.write_u32(adsr + 0x04, 0x7FFFFFFF)
    so.write_u32(adsr + 0x08, 0x7FFFFFFF)
    so.write_u32(adsr + 0x10, 3)                 # the state index Digital's host arms
    so.call(find(syms, cls, "initModule"), [0, so.interface, so.flags])
    so.call(find(syms, cls, "4init"), [state, 5, 0, 0, temp])
    on_note = find(syms, cls, "8onNoteOn")
    if on_note:
        so.call(on_note, [note, 100, state, params])
    total = peak = 0
    mono, inter = [], []
    for _ in range(blocks):
        so.write(out, b"\0" * (FRAMES * 8))
        so.call(find(syms, cls, "6render"),
                [out, int(increment_for(note) * PHASE_SCALE.get(cls, 1.0)), 0, state, params, adsr])
        v = so.read_i32_array(out, FRAMES * 2)
        total += sum(1 for x in v if x)
        peak = max(peak, max((abs(x) for x in v), default=0))
        mono += v[0::2]                       # left channel: some engines write only one
        inter += v                            # interleaved, for the neighbour test below
    return total, peak, mono, inter


def pitch(samples, fs=48000.0, lo=80.0, hi=3000.0):
    """Dominant frequency by DFT scan, then a fine pass around the best bin.

    Non-zero samples only prove an engine emits something; "plays correctly" needs the note. Chord
    deliberately puts energy a fifth above the root, so the caller compares the result with the requested
    frequency and its harmonics rather than demanding equality.
    """
    import cmath
    if not samples or not any(samples):
        return 0.0
    # the tail of the run is the steady state; the attack and any DC or envelope offset would otherwise
    # dominate the scan (an unwindowed whole-run scan reported 55 Hz for every engine, which is the
    # envelope rate, not the note)
    tail = samples[len(samples) // 2:]
    mean = sum(tail) / len(tail)
    n = len(tail)
    windowed = [(s - mean) * (0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1))) for i, s in enumerate(tail)]
    def mag(f):
        return abs(sum(s * cmath.exp(-2j * math.pi * f * i / fs) for i, s in enumerate(windowed)))
    best = max((mag(lo + 0.5 * k), lo + 0.5 * k) for k in range(int((hi - lo) / 0.5)))
    centre = best[1]
    fine = max((mag(centre - 5 + 0.25 * k), centre - 5 + 0.25 * k) for k in range(41))
    return fine[1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--blocks", type=int, default=40)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--note", type=int, default=60, help="MIDI note to play and judge (default 60)")
    ap.add_argument("--note-check", action="store_true",
                    help="also ask whether the tone stands above its 0.75x and 1.5x neighbours, the same "
                         "test opzfactorycheck applies to the Blackfin engines (needs ~140 blocks)")
    a = ap.parse_args(argv)

    syms = symbols()
    names = a.only or INSTRUMENTS
    if a.note_check:
        a.blocks = max(a.blocks, 140)          # 8192 samples per channel, the window contrast() needs
    want = 440.0 * 2 ** ((a.note - 69) / 12.0)
    tracks = 0
    working = 0
    for cls in names:
        so = OpzSo()
        for base, size in ((0x1E0000, 0x200000 - 0x1E0000), (0x200000, 0x1800000)):
            try:
                so.uc.mem_map(base, size, UC_PROT_ALL)
            except Exception:
                pass
        so.stub("noop", lambda s, n: None)
        stub = so.stub_address("noop")
        so.interface = so.alloc(0x80)
        for off in range(0, 0x80, 8):
            so.write(so.interface + off, struct.pack("<Q", stub))
        so.flags = so.alloc(8)
        supply(so, cls)
        try:
            nz, peak, mono, inter = play(so, syms, cls, a.blocks, a.note)
        except Exception as e:
            print(f"  {cls:18s} {type(e).__name__}")
            continue
        ok = nz > 0
        working += ok
        want = 440.0 * 2 ** ((a.note - 69) / 12.0)
        hz = pitch(mono)
        n = round(hz / want) if hz else 0
        cents = 1200 * math.log2(hz / (want * n)) if hz and n else float("nan")
        # informational: a dominant-bin scan is not a pitch tracker on an engine with several partials
        verdict = "" if not ok else (f"  dominant ~{hz:6.1f} Hz ({n}x{want:.1f}, {cents:+.0f} cents)"
                                     if n >= 1 else f"  dominant ~{hz:6.1f} Hz, not near {want:.1f}")
        note = ""
        if a.note_check and ok:
            from opzfactorycheck import contrast
            at = contrast(inter, want)
            lo, hi = contrast(inter, want * 0.75), contrast(inter, want * 1.5)
            plays = at > max(lo, hi)
            tracks += plays
            note = f"  request contrast {at:6.2f} (neighbours {lo:5.2f}/{hi:5.2f}){' PLAYS' if plays else ''}"
        print(f"  {cls:18s} {nz}/{a.blocks * FRAMES * 2} nonzero, peak {peak}{verdict}{note}"
              f"{'' if ok else '   SILENT'}")
    print(f"\n{working} of {len(names)} factory instruments render audio")
    if a.note_check:
        print(f"\nplays the requested note (beats both neighbours): {tracks} of {len(names)}")
    print("the dominant-bin column is informational: the strongest partial is often not the note, so it")
    print("only means the run is not silence near the request. The meaningful column is the request against")
    print("its 0.75x and 1.5x neighbours. Two caveats are measured, not assumed: a sampler plays a fixed")
    print("sample, so it shows strong energy at the request whatever note it is given (Cluster and")
    print("SamplePlayerGain lose only because their 0.75x neighbour is louder, which says nothing about")
    print("whether they track) and AnalogA and Organ have almost no energy at the request at all.")
    return 0 if working == len(names) else 1


if __name__ == "__main__":
    sys.exit(main())
