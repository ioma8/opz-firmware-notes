#!/usr/bin/env python3
"""opzenginetool.py - audition an OP-Z .engine on the desktop before flashing it.

Loads the REAL module bytes and runs them in the Blackfin interpreter from opzsim.py, so what you hear is
what the device will compute, not a model of it. Every knob in the window is written into the same `params`
array the OS passes to render().

The honest constraint: the interpreter runs at about a quarter of realtime (7,017 instructions per 64-frame
block), so a clip is rendered offline. Renders are cached on disk by content hash, so the first play of a
setting takes a few seconds and repeats are instant. Change a knob and it re-renders; that is the trade for
hearing the actual machine code.

Usage:
    python3 toolkit/opzenginetool.py                 # the window
    python3 toolkit/opzenginetool.py --selfcheck     # render one clip, print stats, no GUI

Engines that fail with "unsupported instruction" use an encoding opzsim does not implement yet - that is a
gap in the interpreter, not a broken engine file, and it is stated rather than hidden. Engines built by
toolkit/build_struck.py use only implemented forms and always render. Of the 21 factory engines, all currently
stop inside the first few instructions on one of these classes, which are catalogued here so the gap is a
to-do rather than a mystery:

  * the 0xE1xx family - a 16-bit immediate load into a register pair / half (instr32 LdImmHalf)
  * DSP sub-opcode 0x8 - a 32-bit DSP form other than the shift (0xD) and multiply (0x4)
  * arithmetic right shift (sop=3) - only logical (0) and arithmetic by a negated count (2) are covered
  * LdStAbs through a null pointer - reverb.engine reads address 0, which faults here as it would on silicon

Each is a small addition to opzsim.step(), and the way to add one is to read the matching file under
Ghidra/Extensions/Ghidra-BlackFinPlus/data/languages/includes - never to guess the fields.
"""
import hashlib, json, os, pathlib, queue, subprocess, sys, tempfile, threading, wave

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzengine as E
import opzsim as Z
import opzstruck as S

REPO = pathlib.Path(__file__).resolve().parent.parent
CACHE = pathlib.Path(os.path.expanduser("~/.cache/opzenginetool"))
FS = S.FS
BLOCK = S.BLOCK


# --------------------------------------------------------------------------- engine discovery

def find_engines():
    """Every .engine we can find, cheapest-to-most-useful first."""
    seen, out = set(), []
    for pat in ("engines-official/*.engine", "*.engine", "engines/*.engine", "build/*.engine"):
        for p in sorted(REPO.glob(pat)):
            if p.name not in seen:
                seen.add(p.name)
                out.append(p)
    return out


def describe(path):
    """(name, base, exports, kind, size) - read from the container, never guessed."""
    raw = pathlib.Path(path).read_bytes()
    mod = E.read_module(raw)
    ex = dict(mod["exports"])
    kind = "instrument" if "render" in ex else ("effect" if "renderFX" in ex else "?")
    return {"path": pathlib.Path(path), "raw": raw, "exports": ex, "kind": kind,
            "base": mod["base"], "segments": mod["segments"], "size": len(raw),
            "md5": hashlib.md5(raw).hexdigest()}


# --------------------------------------------------------------------------- rendering

def render_clip(info, note, seconds, params, progress=None):
    """Run the module and return interleaved stereo ints plus stats."""
    m = Z.Machine.for_module(info["raw"])
    ex = info["exports"]
    ctx = m.mem_base + Z.Machine.SCRATCH_OFF
    prm = m.mem_base + Z.Machine.PARAM_OFF
    out = m.mem_base + Z.Machine.OUT_OFF
    for i, v in enumerate(params[:8]):
        m.st32(prm + 4 * i, int(v) & 0xFFFFFFFF)
    if "initModule" in ex:
        Z.call(m, ex["initModule"], [0, 0x81003850, ctx])
    if "init" in ex:
        Z.call(m, ex["init"], [ctx, 0])
    if "onNoteOn" in ex:
        Z.call(m, ex["onNoteOn"], [0, note, ctx])
    freq_q16 = int(440.0 * 2 ** ((note - 69) / 12.0) * 65536) & 0xFFFFFFFF
    blocks = int(seconds * FS / BLOCK)
    samples, envelope = [], []
    for b in range(blocks):
        for j in range(2 * BLOCK):
            m.st32(out + 4 * j, 0)
        Z.call(m, ex["render"], [out, freq_q16, 0], stack=(ctx, prm, 0))
        blk = [m.ld32(out + 4 * j) for j in range(2 * BLOCK)]
        samples.extend(blk)
        envelope.append(max((abs(v) for v in blk), default=0) / 2 ** 31)
        if progress and b % 20 == 0:
            progress(b / max(1, blocks))
    peak = max((abs(v) for v in samples), default=0) / 2 ** 31
    return samples, {"peak": peak, "envelope": envelope, "blocks": blocks,
                     "base": info["base"], "name": info["path"].name}


def write_wav(samples, path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes(b"".join(
            int(max(-1.0, min(1.0, v / 2 ** 31)) * 32767).to_bytes(2, "little", signed=True)
            for v in samples))
    return path


def cached_wav(info, note, seconds, params, progress=None):
    """Render to the cache, keyed by everything that affects the sound."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(json.dumps([info["md5"], note, round(seconds, 3),
                                  [int(p) for p in params]]).encode()).hexdigest()[:16]
    dst = CACHE / f"{info['path'].stem}-{key}.wav"
    meta = dst.with_suffix(".json")
    if dst.exists() and meta.exists():
        stats = json.loads(meta.read_text())
        stats["cached"] = True
        return dst, stats                    # peak and envelope survive the cache hit
    samples, stats = render_clip(info, note, seconds, params, progress)
    write_wav(samples, dst)
    stats["cached"] = False
    meta.write_text(json.dumps(stats))
    return dst, stats


def play(path):
    subprocess.Popen(["afplay", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --------------------------------------------------------------------------- GUI

class App:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk, filedialog
        self.tk, self.ttk = tk, ttk
        self.root = root
        root.title("OP-Z engine audition")
        root.geometry("900x560")
        self.queue = queue.Queue()
        self.infos = {}
        self.current = None
        self.playing = False

        left = ttk.Frame(root, padding=8)
        left.pack(side="left", fill="y")
        ttk.Label(left, text="modules").pack(anchor="w")
        self.listbox = tk.Listbox(left, width=34, height=22, exportselection=False)
        self.listbox.pack(fill="y", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda e: self.on_pick())
        ttk.Button(left, text="Open .engine…", command=self.on_open).pack(fill="x", pady=4)

        right = ttk.Frame(root, padding=8)
        right.pack(side="left", fill="both", expand=True)
        self.info = ttk.Label(right, text="select a module", justify="left", font=("Monaco", 10))
        self.info.pack(anchor="w")

        row = ttk.Frame(right)
        row.pack(fill="x", pady=6)
        ttk.Label(row, text="note").pack(side="left")
        self.note = tk.IntVar(value=69)
        ttk.Spinbox(row, from_=0, to=127, width=5, textvariable=self.note).pack(side="left", padx=4)
        ttk.Label(row, text="seconds").pack(side="left", padx=(12, 0))
        self.secs = tk.DoubleVar(value=1.2)
        ttk.Spinbox(row, from_=0.2, to=6.0, increment=0.2, width=5,
                    textvariable=self.secs).pack(side="left", padx=4)
        self.btn_play = ttk.Button(row, text="Render & play", command=self.on_play)
        self.btn_play.pack(side="left", padx=8)
        ttk.Button(row, text="Save WAV…", command=self.on_save).pack(side="left")
        ttk.Button(row, text="Stop", command=self.on_stop).pack(side="left", padx=4)

        ttk.Label(right, text="params[] - the eight knob values the OS passes to render()"
                  ).pack(anchor="w", pady=(10, 0))
        self.params = []
        for i in range(8):
            f = ttk.Frame(right)
            f.pack(fill="x")
            ttk.Label(f, text=f"p{i}", width=3).pack(side="left")
            v = tk.DoubleVar(value=0.5 if i != 2 else 0.5)
            ttk.Scale(f, from_=0.0, to=1.0, variable=v,
                      command=lambda _v, idx=i: self.mark_dirty(idx)).pack(side="left", fill="x", expand=True)
            lab = ttk.Label(f, text="0.500", width=7)
            lab.pack(side="left")
            self.params.append((v, lab))

        self.canvas = tk.Canvas(right, height=120, background="#111118", highlightthickness=0)
        self.canvas.pack(fill="x", pady=10)
        self.status = ttk.Label(right, text="ready", font=("Monaco", 10))
        self.status.pack(anchor="w")

        for p in find_engines():
            self.add(p)
        self.root.after(120, self.poll)
        self.tick()

    # ---- list handling
    def add(self, path):
        try:
            info = describe(path)
        except Exception as e:
            self.listbox.insert("end", f"{path.name}  (unreadable: {e})")
            return
        self.infos[self.listbox.size()] = info
        self.listbox.insert("end", f"{path.name}  [{info['kind']}, {info['size']} B]")

    def on_open(self):
        from tkinter import filedialog
        f = filedialog.askopenfilename(filetypes=[("engine", "*.engine"), ("all", "*")])
        if f:
            self.add(pathlib.Path(f))

    def on_pick(self):
        sel = self.listbox.curselection()
        if not sel or sel[0] not in self.infos:
            return
        self.current = self.infos[sel[0]]
        i = self.current
        self.info.config(text=f"{i['path'].name}   {i['size']} B   base 0x{i['base']:08x}   "
                              f"{i['kind']}\n exports: " + ", ".join(
                                  f"{k}@0x{v:08x}" for k, v in i["exports"].items()))
        self.mark_dirty(0)

    def mark_dirty(self, _idx):
        for v, lab in self.params:
            lab.config(text=f"{v.get():.3f}")

    def param_word(self):
        """A slider 0..1 becomes the Q28 word the OS would hand the engine."""
        return [int(v.get() * (1 << 28)) & 0xFFFFFFFF for v, _ in self.params]

    # ---- actions
    def on_play(self):
        if not self.current:
            self.status.config(text="pick a module first")
            return
        if self.playing:
            return
        self.playing = True
        self.btn_play.config(state="disabled")
        info, note, secs, params = self.current, self.note.get(), self.secs.get(), self.param_word()

        def work():
            try:
                path, stats = cached_wav(info, note, secs, params,
                                         progress=lambda f: self.queue.put(("progress", f)))
                self.queue.put(("done", (path, stats)))
            except Exception as e:
                self.queue.put(("error", f"{type(e).__name__}: {e}"))

        threading.Thread(target=work, daemon=True).start()

    def on_save(self):
        from tkinter import filedialog
        if not self.current:
            return
        dst = filedialog.asksaveasfilename(defaultextension=".wav")
        if not dst:
            return
        info, note, secs, params = self.current, self.note.get(), self.secs.get(), self.param_word()
        path, _ = cached_wav(info, note, secs, params)
        pathlib.Path(dst).write_bytes(path.read_bytes())
        self.status.config(text=f"saved {dst}")

    def on_stop(self):
        subprocess.Popen(["killall", "afplay"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ---- async plumbing
    def poll(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    self.status.config(text=f"rendering… {payload*100:.0f}%  "
                                            f"(interpreter runs ~0.23x realtime)")
                elif kind == "done":
                    path, stats = payload
                    self.playing = False
                    self.btn_play.config(state="normal")
                    cached = "cached" if stats.get("cached") else "rendered"
                    self.status.config(text=f"{cached}: peak {stats['peak']:.3f} full scale, "
                                            f"base 0x{stats['base']:08x}  ->  {path.name}")
                    self.draw(stats.get("envelope", []))
                    play(path)
                elif kind == "error":
                    self.playing = False
                    self.btn_play.config(state="normal")
                    self.status.config(text=payload)
        except queue.Empty:
            pass
        self.root.after(120, self.poll)

    def tick(self):
        self.root.after(250, self.tick)

    def draw(self, env):
        c = self.canvas
        c.delete("all")
        w, h = max(c.winfo_width(), 300), max(c.winfo_height(), 120)
        if not env:
            return
        step = max(1, len(env) // w)
        pts = [(i / len(env) * w, h - min(1.0, env[i]) * (h - 6) - 3) for i in range(0, len(env), step)]
        c.create_line(*[coord for p in pts for coord in p], fill="#7fd1ff", width=1.6)


def main(argv):
    if "--selfcheck" in argv:
        engines = [p for p in find_engines() if p.name == "struck.engine"] or find_engines()[:1]
        if not engines:
            raise SystemExit("no .engine found")
        info = describe(engines[0])
        print(f"{info['path'].name}  {info['size']} B  base 0x{info['base']:08x}  {info['kind']}")
        import time
        t0 = time.time()
        path, stats = cached_wav(info, 69, 1.0, [int(0.5 * (1 << 28))] * 8)
        print(f"  rendered in {time.time()-t0:.2f} s  peak {stats['peak']:.3f}  "
              f"{'cached' if stats['cached'] else 'fresh'}  -> {path}")
        samples, _ = render_clip(info, 69, 1.0, [int(0.5 * (1 << 28))] * 8)
        print(f"  measured pitch {S.measure_freq(samples):.1f} Hz (expect ~440)")
        pathlib.Path(tempfile.gettempdir(), "opzenginetool-selftest.wav").write_bytes(path.read_bytes())
        print("  wav: " + str(pathlib.Path(tempfile.gettempdir(), "opzenginetool-selftest.wav")))
        return 0

    # Homebrew's python often ships without _tkinter while /usr/bin/python3 has it. Rather than making
    # the user discover that, re-exec into the first interpreter that can open a window.
    try:
        import tkinter  # noqa: F401
    except ImportError:
        if not os.environ.get("OPZENGINE_REEXEC"):
            import shutil
            for cand in ("/usr/bin/python3", shutil.which("python3.12"), shutil.which("python3.11")):
                if cand and pathlib.Path(cand).exists() and cand != sys.executable:
                    os.environ["OPZENGINE_REEXEC"] = "1"
                    os.execv(cand, [cand, str(pathlib.Path(__file__).resolve())] + argv)
        raise SystemExit("no tkinter available: install python-tk, or run with /usr/bin/python3")

    import tkinter as tk
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
