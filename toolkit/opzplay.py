#!/usr/bin/env python3
"""opzplay.py - play an OP-Z .engine live from the computer keyboard, at native speed.

The engine's own machine code is translated to C by opzjit.py and compiled once (cached), so a 64-frame
block costs microseconds: about 6.8 us against a 1333 us budget at 48 kHz. That leaves room for several
voices. Blocks are rendered in a thread and written as raw PCM to audiosink, a small CoreAudio helper
compiled on first use, which gives realtime output with no Python audio dependency.

Keys (terminal in raw mode, no Enter needed):

    a s d f g h j k l ;   notes of the current scale, low to high
    z / x                 octave down / up
    space                 all notes off
    q                     quit

Each key press triggers a voice; the note is released after --hold seconds, which suits struck and percussive
engines. Sustained playing is a matter of raising --hold.

Usage:
    python3 toolkit/opzplay.py                       # plays ./struck.engine
    python3 toolkit/opzplay.py --engine path.engine  # any translated module
    python3 toolkit/opzplay.py --selftest            # render + measure, no keyboard, no device
"""
import argparse, ctypes, os, pathlib, select, subprocess, sys, threading, time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzengine as E
import opzjit as J
import opzhost as H
import opzstruck as S

TOOLKIT = pathlib.Path(__file__).parent
SINK_C = TOOLKIT / "audiosink.c"
SINK_BIN = pathlib.Path.home() / ".cache" / "opzjit" / "audiosink"

FS, BLOCK = S.FS, S.BLOCK
SCALE = [0, 2, 4, 5, 7, 9, 11, 12, 14, 16]          # major scale, two octaves
KEYS = "asdfghjkl;"


# ------------------------------------------------------------------------------------------ engine wrapper

class Engine:
    """One .engine, translated to C, with as many voices as asked for."""

    def __init__(self, path, voices=4):
        raw = pathlib.Path(path).read_bytes()
        self.dylib, base, size, img, exports = J.build(raw, pathlib.Path(path).stem)
        self.lib = ctypes.CDLL(str(self.dylib))
        self.lib.opz_call.restype = ctypes.c_int32
        self.lib.opz_call.argtypes = [ctypes.c_void_p, ctypes.c_int64, ctypes.c_int64, ctypes.c_uint32] + \
                                     [ctypes.c_int32] * 6 + [ctypes.c_int32, ctypes.c_uint32]
        self.buf = (ctypes.c_char * size)()
        self.base, self.size, self.exports = base, size, dict(exports)
        mod = E.read_module(raw)
        ctypes.memmove(ctypes.addressof(self.buf) + (mod["base"] - base), bytes(img), len(img))
        self.sp = base + size - 0x100
        self.out = base + J.OUT_OFF
        self.prm = base + J.PARAM_OFF
        self.table = base + J.SCRATCH_OFF - 0x200
        # host memory: the OS table plus the shared wavetable region, if it has been extracted
        for hbase, blob in H.load():
            off = ctypes.addressof(self.buf) + (hbase - base)
            if 0 <= off - ctypes.addressof(self.buf) < size - len(blob):
                ctypes.memmove(off, blob, len(blob))
        for i, v in enumerate(H.host_table()):
            ctypes.c_uint32.from_address(self._host(self.table) + 4 * i).value = v
        self.params = [int(0.5 * (1 << 28))] * 8
        for i, v in enumerate(self.params):
            ctypes.c_uint32.from_address(self._host(self.prm) + 4 * i).value = v
        self.voices = []
        for v in range(voices):
            ctx = base + J.SCRATCH_OFF + 0x1000 + v * 0x200
            self.call("initModule", [0, self.table, ctx])
            self.call("init", [ctx, 0])
            self.voices.append({"ctx": ctx, "note": None, "off_at": 0.0})
        self.acc = (ctypes.c_int32 * (2 * BLOCK))()

    def _host(self, eaddr):
        return ctypes.addressof(self.buf) + (eaddr - self.base)

    def call(self, name, args, stack=()):
        st = list(stack) + [0] * (3 - len(stack))
        return self.lib.opz_call(ctypes.cast(self.buf, ctypes.c_void_p), self.base, self.size,
                                 self.exports[name],
                                 *[a & 0xFFFFFFFF for a in (list(args) + [0, 0, 0])[:3]],
                                 *[s & 0xFFFFFFFF for s in st[:3]], len(stack), self.sp)

    # ---- voice control
    def note_on(self, note, hold=1.0):
        free = next((v for v in self.voices if v["note"] is None), None)
        if free is None:
            free = min(self.voices, key=lambda v: v["off_at"])
            self.call("onNoteOff", [0, free["ctx"]])
        free["note"] = note
        free["off_at"] = time.monotonic() + hold
        self.call("onNoteOff", [0, free["ctx"]])
        self.call("onNoteOn", [0, note, free["ctx"]])

    def note_off(self, voice):
        if voice["note"] is not None:
            self.call("onNoteOff", [0, voice["ctx"]])
            voice["note"] = None

    def all_off(self):
        for v in self.voices:
            self.note_off(v)

    # ---- one audio block, summed over voices
    def render_block(self):
        acc = self.acc
        for i in range(2 * BLOCK):
            acc[i] = 0
        active = False
        for v in self.voices:
            if v["note"] is None:
                continue
            active = True
            freq = int(440.0 * 2 ** ((v["note"] - 69) / 12.0) * 65536) & 0xFFFFFFFF
            ctypes.memset(self._host(self.out), 0, 2 * BLOCK * 4)
            self.call("render", [self.out, freq, 0], (v["ctx"], self.prm, 0))
            src = ctypes.cast(self._host(self.out), ctypes.POINTER(ctypes.c_int32))
            for i in range(2 * BLOCK):
                acc[i] = max(-2 ** 31, min(2 ** 31 - 1, acc[i] + src[i]))
        return active, acc


# ------------------------------------------------------------------------------------------ output

def build_sink():
    if SINK_BIN.exists() and SINK_BIN.stat().st_mtime >= SINK_C.stat().st_mtime:
        return SINK_BIN
    SINK_BIN.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["clang", "-O2", "-o", str(SINK_BIN), str(SINK_C),
                        "-framework", "AudioToolbox", "-framework", "CoreAudio"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"audiosink build failed:\n{r.stderr[:1200]}")
    return SINK_BIN


def pcm_bytes(acc):
    out = bytearray(2 * BLOCK * 2)
    for i in range(2 * BLOCK):
        v = acc[i] >> 16
        struct_pack_into(out, i * 2, max(-32768, min(32767, v)))
    return bytes(out)


def struct_pack_into(buf, off, v):
    buf[off] = v & 0xFF
    buf[off + 1] = (v >> 8) & 0xFF


# ------------------------------------------------------------------------------------------ playing

def play(engine, hold):
    sink = subprocess.Popen([str(build_sink()), str(FS), "512"], stdin=subprocess.PIPE)
    stop = threading.Event()
    octave = {"n": 4}

    def audio_loop():
        while not stop.is_set():
            now = time.monotonic()
            for v in engine.voices:                       # release expired notes
                if v["note"] is not None and now >= v["off_at"]:
                    engine.note_off(v)
            _, acc = engine.render_block()
            try:
                sink.stdin.write(pcm_bytes(acc))
                sink.stdin.flush()
            except (BrokenPipeError, ValueError):
                break

    t = threading.Thread(target=audio_loop, daemon=True)
    t.start()
    import termios, tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    print(f"playing {pathlib.Path(engine.dylib).name}  |  keys {KEYS}  z/x octave  space off  q quit")
    try:
        tty.setcbreak(fd)
        while True:
            r, _, _ = select.select([sys.stdin], [], [], 0.05)
            if not r:
                continue
            ch = sys.stdin.read(1)
            if ch == "q":
                break
            if ch == "z":
                octave["n"] = max(1, octave["n"] - 1); print(f"octave {octave['n']}"); continue
            if ch == "x":
                octave["n"] = min(7, octave["n"] + 1); print(f"octave {octave['n']}"); continue
            if ch == " ":
                engine.all_off(); continue
            if ch in KEYS:
                semi = SCALE[KEYS.index(ch)]
                engine.note_on(12 * (octave["n"] + 1) + semi, hold)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        stop.set()
        engine.all_off()
        time.sleep(0.05)
        try:
            sink.stdin.close()
        except Exception:
            pass
        sink.wait(timeout=3)


def selftest(engine_path, seconds=1.0):
    eng = Engine(engine_path)
    blocks = int(seconds * FS / BLOCK)
    eng.note_on(69, hold=seconds)
    t0 = time.perf_counter()
    peak = 0
    for _ in range(blocks):
        active, acc = eng.render_block()
        peak = max(peak, max(abs(v) for v in acc) / 2 ** 31)
    dt = time.perf_counter() - t0
    print(f"engine      {pathlib.Path(engine_path).name}  voices {len(eng.voices)}")
    print(f"rendered    {seconds:.2f} s of audio in {dt*1000:.1f} ms  ->  {seconds/dt:.0f}x realtime")
    print(f"peak        {peak:.4f} full scale")
    print(f"block cost  {dt/blocks*1e6:.1f} us (budget {BLOCK/FS*1e6:.0f} us)")
    ok = peak > 0.001 and dt < seconds * 0.5
    print("RESULT:", "realtime and audible" if ok else "FAILED")
    return 0 if ok else 1


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default="struck.engine")
    ap.add_argument("--voices", type=int, default=4)
    ap.add_argument("--hold", type=float, default=1.0)
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest(a.engine)
    eng = Engine(a.engine, voices=a.voices)
    play(eng, a.hold)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
