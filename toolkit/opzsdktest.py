#!/usr/bin/env python3
"""opzsdktest.py - exercise every construct of the engine DSL and check the results in the interpreter.

Each export below computes something whose answer is known, so a wrong encoder, a wrong register
assignment or a wrong frame slot shows up as a wrong number rather than as an engine that "sounds fine".
Run: python3 toolkit/opzsdktest.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzsdk as S
import opzengine as E
import opzsim as Z
import opztime

TAB = None
CTX = None


def build(path):
    global TAB, CTX
    e = S.Engine("sdktest", slot=79)
    TAB = e.words("TAB", [10, 20, 30, 40, 50, 60])       # TAB[i] = 10*(i+1)
    CTX = e.reserve("CTX", 64)                           # scratch the module may use

    # ------------------------------------------------------------------ initModule(id, host, out)
    @e.fn("initModule", ["idv", "host", "out"])
    def initModule(idv, host, out):
        with S.if_(S.nz(idv)):
            S.ret(0)                                     # refuse a foreign id
        S.ptr(out)[0].set(1234)
        S.ret(1)

    # ------------------------------------------------------------------ init(ctx, variant)
    # fill 16 words with a ramp, using a cursor (post-increment store)
    @e.fn("init", ["ctx", "variant"])
    def init(ctx, variant):
        c = S.pin(S.ptr(ctx))
        i = S.var("i", hot=True)
        i.set(0)
        with S.repeat(16):
            c.put(i)
            i.set(i + 1)
        S.unpin(c)

    # ------------------------------------------------------------------ onNoteOn / onNoteOff
    @e.fn("onNoteOn", ["a1", "note", "ctx", "a4"])
    def onNoteOn(a1, note, ctx, a4):
        S.ptr(ctx)[0].set(note)

    @e.fn("onNoteOff", ["a1", "ctx"])
    def onNoteOff(a1, ctx):
        c = S.ptr(ctx)
        with S.if_(ctx < 0x10000000):                      # unsigned: pointer ranges are above 2^31
            S.ret()
        c[4].set(0xFFFF)
        c[8].set(0)

    # ------------------------------------------------------------------ render(out, pitch, bend, ctx, params, amp)
    @e.fn("render", ["out", "pitch", "bend", "ctx", "params", "amp"])
    def render(out, pitch, bend, ctx, params, amp):
        acc = S.var("acc", hot=True)
        k = S.var("k")                                    # a frame slot, loaded each use
        o = S.pin(S.ptr(out))
        c = S.pin(S.ptr(ctx))
        S.unpin(o)                                        # exercise unpin/reuse
        o = S.pin(S.ptr(out))

        acc.set(0)
        # every binary operator
        acc.set(pitch + bend)
        acc.set(acc - 8)                                  # + - literal
        acc.set(acc & 0xFF)
        acc.set(acc | 0x100)
        acc.set(acc ^ 0x40)
        acc.set(acc << 2)
        acc.set(acc >> 1)
        k.set(acc)
        acc.set(S.qmul(k, 0x40000000))                    # Q31: half of k
        # a conditional with an else branch
        with S.if_(S.lt_s(acc, 0)):
            acc.set(acc - 1)
        with S.else_():
            acc.set(acc + 1)
        # a while loop with continue and break
        k.set(0)
        with S.while_(k < 100):
            k.set(k + 1)
            with S.if_(k == 3):
                S.continue_()
            with S.if_(k == 10):
                S.break_()
            acc.set(acc + 1)                              # runs 8 times: 1,2,4..9
        # a table indexed by a runtime value, read twice
        acc.set(acc + TAB[k >> 1])                        # k == 10 -> TAB[5] = 60
        # a cursor writes, then a slot writes over the top of it
        with S.repeat(4):
            o.put(acc)
        o.put(acc)
        S.unpin(o)
        S.unpin(c)
        # args 4..6 are stack words: prove they arrive
        S.ptr(ctx)[0x3C].set(amp)

    return e.build()


if __name__ == "__main__":
    opztime.watch("SDK selftest")
    raw = build("/tmp/sdktest.engine")
    ex = dict(E.read_module(raw)["exports"])
    print("exports: " + ", ".join(f"{k}=0x{v:08x}" for k, v in sorted(ex.items())))
    m = Z.Machine.for_module(raw)
    scratch = m.mem_base + Z.Machine.SCRATCH_OFF
    params = m.mem_base + Z.Machine.PARAM_OFF
    out = m.mem_base + Z.Machine.OUT_OFF
    amp = params + 0x40
    bad = []

    def checkok(name, ok, detail=""):
        print(f"  {'PASS' if ok else 'FAIL'}  {name:44s} {detail}")
        if not ok:
            bad.append(name)

    def check(name, got, want):
        ok = got == want
        if not ok:
            bad.append(name)
        print(f"  {'PASS' if ok else 'FAIL'}  {name:44s} got {got!r} want {want!r}")

    m.st32(scratch, 0)
    check("initModule(0) returns 1", Z.call(m, ex["initModule"], [0, 0x81003850, scratch]), 1)
    check("  ...and writes *out = 1234", m.ld32(scratch), 1234)
    check("initModule(1) returns 0", Z.call(m, ex["initModule"], [1, 0x81003850, scratch]), 0)

    Z.call(m, ex["init"], [scratch, 5])
    check("init fills 16 ramp words", [m.ld32(scratch + 4 * i) for i in range(16)],
          list(range(16)))

    Z.call(m, ex["onNoteOn"], [0, 69, scratch, 0])
    check("onNoteOn stores the note", m.ld32(scratch), 69)
    Z.call(m, ex["onNoteOff"], [0, 5])                    # not a pointer: must do nothing
    check("onNoteOff ignores a non-pointer", m.ld32(scratch + 4), 1)
    Z.call(m, ex["onNoteOff"], [0, scratch])
    check("onNoteOff writes through a pointer", m.ld32(scratch + 4), 0xFFFF)

    Z.call(m, ex["init"], [scratch, 5])
    m.st32(amp + 0x10, 0x5)
    Z.call(m, ex["render"], [out, 1000, 24, ], stack=(scratch, params, amp))
    got = [m.ld32(out + 4 * i) for i in range(5)]
    # hand calculation: pitch 1000 + bend 24 = 1024; -8 = 1016; &0xFF = 248; |0x100 = 504;
    # ^0x40 = 440; <<2 = 1760; >>1 = 880; qmul(880, 0.5) = 440; +1 (else branch) = 441;
    # +8 from the loop = 449; + TAB[5]=60 = 509.
    check("render computes 509 and walks the cursor", got, [509] * 5)
    check("a stack argument was readable", m.ld32(scratch + 0x3C) & 0xFFFFFFFF, amp & 0xFFFFFFFF)

    # ---- the declarative layer above the DSL: the three authored engines build, and the guards that stop
    # a silent or clipping engine from being built at all actually fire
    import opzsynth as K
    for name in ("marimba", "cathedral", "strings"):
        mod = __import__("build_" + name)
        raw = mod.build().build()
        checkok(f"declared engine builds: {name}", len(raw) > 512, f"{len(raw)} B")
    guards = {
        "clipping seeds": dict(partials=[(1.0, None)], levels=[1.5]),
        "all partials above Nyquist": dict(partials=[(60.0, None)], levels=[0.1]),
        "too many oscillators": dict(partials=[(1.0, None)] * 12, levels=[0.01] * 12, banks=2),
        "level count mismatch": dict(partials=[(1.0, None), (2.0, None)], levels=[0.1]),
    }
    for what, kw in guards.items():
        try:
            K.build("guard", slot=79, **kw)
            checkok(f"guard: {what}", False, "built an engine it should have refused")
        except ValueError:
            checkok(f"guard: {what}", True, "")

    print("\n" + ("all SDK checks pass" if not bad else f"{len(bad)} FAILED: {bad}"))
    sys.exit(1 if bad else 0)
