#!/usr/bin/env python3
"""opzenginetool.py - audition an OP-Z .engine on the desktop before flashing it.

Loads the REAL module bytes and runs them in the Blackfin interpreter from opzsim.py, so what you hear is
what the device will compute, not a model of it. Every slider in the page is written into the same `params`
array the OS passes to render(), so a slider is a knob.

The interface is a local web page rather than a desktop toolkit window: Apple's system Tk is 8.5, which
renders a blank white window on current macOS, and stdlib HTTP needs nothing at all. The browser also brings
its own audio path, so playback needs no extra dependency.

Usage:
    python3 toolkit/opzenginetool.py                 # serve the page and open a browser
    python3 toolkit/opzenginetool.py --port 8800
    python3 toolkit/opzenginetool.py --selfcheck     # render one clip and print stats, no browser

What works, measured rather than assumed:

  * every one of the 21 factory engines now LOADS AND EXECUTES with no interpreter error - the opcodes
    they use were all recovered from the Ghidra SLEIGH sources (LINK/UNLINK, LdStAbs, LdStIdxI, LdStPmod,
    the displacement and frame-relative load/store forms, CallA, LSETUP hardware loops, the CCFlag/CCMV/
    CC2Dreg/CC2Stat conditional machinery, PushPopMult and single-register push/pop, the Dsp32 Mac/Alu/
    Shift families including pack/extract/signbits/popcount/divide-step, ALU2op, Logi2Op, Ptr2op, NOP32);
  * modules built by toolkit/build_struck.py render audio through this harness, and are the intended use:
    a change to the engine is audible in seconds instead of a flash cycle;
  * factory engines are SILENT here. They run to completion but write nothing to the output buffer,
    because they read voice and envelope state that the operating system maintains - the amp object's
    state machine, per-voice parameters, and results of host-service calls into opz.ldr. This harness maps
    unmapped memory to zero and stubs host calls to a zero return, which is enough to execute them but not
    enough to give them a signal to shape. Making them audible needs the host-services table at 0x81003850
    characterised entry by entry, which is a separate piece of reverse engineering.

Rendering speed depends on the path: the interpreter runs at about 0.2x realtime, while toolkit/opzplay.py
translates the module to C (opzjit.py) and runs it at roughly 200x realtime, which is what makes live
keyboard playing possible - see opzplay.py for that. This page uses the interpreter because it renders any
module the interpreter can run, including ones the translator does not cover yet.
"""
import hashlib, json, math, os, pathlib, sys, threading, urllib.parse, wave, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzengine as E
import opzsim as Z
import opzstruck as S

REPO = pathlib.Path(__file__).resolve().parent.parent
CACHE = pathlib.Path(os.path.expanduser("~/.cache/opzenginetool"))
FS, BLOCK = S.FS, S.BLOCK
DEFAULT_PORT = 8765


# --------------------------------------------------------------------------- modules

def find_engines():
    seen, out = set(), []
    for pat in ("engines-official/*.engine", "*.engine", "engines/*.engine", "build/*.engine"):
        for p in sorted(REPO.glob(pat)):
            if p.name not in seen:
                seen.add(p.name)
                out.append(p)
    return out


def resolve(spec):
    """Accept a repo-relative name, an absolute path, or a bare file name."""
    p = pathlib.Path(spec).expanduser()
    if not p.is_absolute():
        for cand in (REPO / p, REPO / "engines-official" / p, pathlib.Path.cwd() / p):
            if cand.is_file():
                return cand.resolve()
        raise FileNotFoundError(f"no such engine: {spec}")
    if not p.is_file():
        raise FileNotFoundError(f"no such file: {spec}")
    return p


def describe(path):
    raw = pathlib.Path(path).read_bytes()
    mod = E.read_module(raw)
    ex = dict(mod["exports"])
    kind = "instrument" if "render" in ex else ("effect" if "renderFX" in ex else "?")
    return {"path": str(path), "name": pathlib.Path(path).name, "raw": raw, "exports": ex,
            "kind": kind, "base": mod["base"], "size": len(raw),
            "md5": hashlib.md5(raw).hexdigest()}


# --------------------------------------------------------------------------- rendering

def render_clip(info, note, seconds, params):
    m = Z.Machine.for_module(info["raw"])
    # a factory engine touches OS memory this harness does not map (the host table, its own globals);
    # auditioning reads zeros there instead of failing, while the validation gates stay strict
    m.allow_external = True
    ex = info["exports"]
    fx = "render" not in ex and "renderFX" in ex
    if "render" not in ex and not fx:
        raise RuntimeError("this module exports neither render nor renderFX")
    ctx, prm = m.mem_base + Z.Machine.SCRATCH_OFF, m.mem_base + Z.Machine.PARAM_OFF
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
    samples, envelope = [], []
    # an effect has nothing to process without an input: feed it a short burst of a decaying sine at the
    # note's frequency, so the effect's own character comes through instead of silence
    # the input buffer must NOT land on SCRATCH_OFF, which is where an instrument's context lives:
    # writing there silenced struck.engine until this was spotted (measured pitch fell to the search floor)
    inp = m.mem_base + Z.Machine.PARAM_OFF + 0x8000
    state = m.mem_base + Z.Machine.PARAM_OFF + 0x9000
    if fx:
        for i in range(2 * BLOCK):
            t = i
            env = max(0.0, 1.0 - t / (FS * 0.25))
            v = int(0.5 * env * math.sin(2 * math.pi * 440.0 * t / FS) * 2 ** 31)
            m.st32(inp + 4 * i, v)
            m.st32(inp + 4 * i + 4 * BLOCK * 2, v)
    for _ in range(int(seconds * FS / BLOCK)):
        for j in range(2 * BLOCK):
            m.st32(out + 4 * j, 0)
        if fx:
            Z.call(m, ex["renderFX"], [ctx, freq_q16, state, inp, out])
        else:
            Z.call(m, ex["render"], [out, freq_q16, 0], stack=(ctx, prm, 0))
        blk = [m.ld32(out + 4 * j) for j in range(2 * BLOCK)]
        samples.extend(blk)
        envelope.append(max((abs(v) for v in blk), default=0) / 2 ** 31)
    peak = max((abs(v) for v in samples), default=0) / 2 ** 31
    # 60-point envelope is plenty for a thumbnail and fits in a header comfortably
    step = max(1, len(envelope) // 60)
    return samples, {"peak": round(peak, 4), "envelope": [round(e, 4) for e in envelope[::step]][:60]}


def write_wav(samples, path):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(FS)
        w.writeframes(b"".join(
            int(max(-1.0, min(1.0, v / 2 ** 31)) * 32767).to_bytes(2, "little", signed=True)
            for v in samples))
    return path


def cached_wav(info, note, seconds, params):
    CACHE.mkdir(parents=True, exist_ok=True)
    key = hashlib.md5(json.dumps([info["md5"], note, round(seconds, 3),
                                 [int(p) for p in params]]).encode()).hexdigest()[:16]
    dst = CACHE / f"{pathlib.Path(info['path']).stem}-{key}.wav"
    meta = dst.with_suffix(".json")
    if dst.exists() and meta.exists():
        return dst, json.loads(meta.read_text()), True
    samples, stats = render_clip(info, note, seconds, params)
    write_wav(samples, dst)
    meta.write_text(json.dumps(stats))
    return dst, stats, False


# --------------------------------------------------------------------------- page

PAGE = """<!doctype html>
<meta charset="utf-8"><title>OP-Z engine audition</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; font:13px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
         background:#0e0e14; color:#d8dae5; }
  header { padding:14px 20px; border-bottom:1px solid #22222e; }
  h1 { margin:0; font-size:15px; font-weight:600; letter-spacing:.2px; }
  header small { color:#7c8090; }
  main { display:grid; grid-template-columns: 300px 1fr; gap:0; height:calc(100vh - 58px); }
  aside { border-right:1px solid #22222e; overflow:auto; padding:10px; }
  section { padding:16px 20px; overflow:auto; }
  .eng { padding:6px 8px; border-radius:5px; cursor:pointer; display:flex; justify-content:space-between; }
  .eng:hover { background:#181824; } .eng.on { background:#1d2b3a; color:#a9d8ff; }
  .eng span:last-child { color:#6f7484; font-size:11px; }
  .bad { color:#e0a0a0; }
  .row { display:flex; align-items:center; gap:10px; margin:8px 0; flex-wrap:wrap; }
  label.k { width:26px; color:#8f94a6; font-variant-numeric:tabular-nums; }
  input[type=range] { flex:1; min-width:120px; accent-color:#5aa9e6; }
  input[type=number], input[type=text] { background:#15151f; color:#d8dae5; border:1px solid #2a2a38;
         border-radius:5px; padding:4px 6px; font:inherit; }
  input[type=text] { flex:1; }
  button { background:#24405c; color:#dceaf8; border:1px solid #33587a; border-radius:6px;
           padding:7px 14px; font:inherit; cursor:pointer; }
  button:hover { background:#2c4f70; } button:disabled { opacity:.45; cursor:default; }
  .val { width:52px; text-align:right; color:#9aa0b2; font-variant-numeric:tabular-nums; }
  canvas { width:100%; height:130px; background:#0a0a10; border:1px solid #1c1c28; border-radius:6px; }
  #meta { color:#8f94a6; white-space:pre-wrap; font-family:ui-monospace,Menlo,monospace; font-size:11.5px; }
  #status { margin-top:8px; color:#9aa0b2; min-height:20px; }
  audio { width:100%; margin-top:10px; }
  .hint { color:#6b7080; font-size:11.5px; margin-top:10px; }
</style>
<header><h1>OP-Z engine audition</h1>
<small>runs the real module bytes in the Blackfin interpreter &middot; offline render, cached</small></header>
<main>
  <aside>
    <div class="row"><input type="text" id="pathbox" placeholder="path to any .engine, then Open">
      <button onclick="openPath()">Open</button></div>
    <div id="list"></div>
  </aside>
  <section>
    <div id="meta">select a module</div>
    <div class="row" style="margin-top:14px">
      <span>note</span><input type="number" id="note" min="0" max="127" value="69" style="width:70px">
      <span>seconds</span><input type="number" id="secs" min="0.2" max="6" step="0.2" value="1.2" style="width:80px">
      <button id="go" onclick="play()">Render &amp; play</button>
      <a id="dl" style="display:none"><button>Save WAV</button></a>
    </div>
    <div id="params"></div>
    <canvas id="plot" width="1200" height="260"></canvas>
    <audio id="au" controls></audio>
    <div id="status">ready</div>
    <div class="hint">params[] are the eight knob values the OS passes to render(). For struck, p2 is the
      decay macro. Rendering takes a few seconds the first time (the interpreter is ~0.23x realtime); repeat
      plays of the same setting come from the cache instantly.</div>
  </section>
</main>
<script>
let engines = [], cur = null;
const P = [...Array(8)].map(() => 0.5);
const $ = id => document.getElementById(id);

async function init() {
  engines = await (await fetch('/api/engines')).json();
  const list = $('list');
  list.innerHTML = '';
  engines.forEach(e => {
    const d = document.createElement('div');
    d.className = 'eng';
    d.innerHTML = `<span>${e.name}</span><span>${e.kind}, ${e.size} B</span>`;
    if (!e.ok) d.classList.add('bad');
    d.onclick = () => { document.querySelectorAll('.eng').forEach(x => x.classList.remove('on'));
                        d.classList.add('on'); select(e.name); };
    list.appendChild(d);
  });
  drawParams();
  const struck = engines.find(e => e.name === 'struck.engine');
  if (struck) [...document.querySelectorAll('.eng')][engines.indexOf(struck)].click();
}

function drawParams() {
  $('params').innerHTML = '';
  P.forEach((v, i) => {
    const row = document.createElement('div');
    row.className = 'row';
    row.innerHTML = `<label class="k">p${i}</label>
      <input type="range" min="0" max="1" step="0.01" value="${v}">
      <span class="val" id="v${i}">${v.toFixed(3)}</span>`;
    row.querySelector('input').oninput = ev => { P[i] = +ev.target.value;
                                                $('v' + i).textContent = P[i].toFixed(3); };
    $('params').appendChild(row);
  });
}

async function select(name) {
  const r = await fetch('/api/info?engine=' + encodeURIComponent(name));
  const j = await r.json();
  if (j.error) { $('meta').textContent = j.error; return; }
  cur = j;
  $('meta').textContent = `${j.name}   ${j.size} B   base 0x${j.base.toString(16)}   ${j.kind}\\n` +
    'exports: ' + Object.entries(j.exports).map(([k, v]) =>
      `${k}@0x${v.toString(16)}`).join('  ');
  $('status').textContent = 'ready';
}

async function openPath() {
  const p = $('pathbox').value.trim();
  if (!p) return;
  const r = await fetch('/api/info?engine=' + encodeURIComponent(p));
  const j = await r.json();
  if (j.error) { $('meta').textContent = j.error; return; }
  engines.push({name: j.name, kind: j.kind, size: j.size, ok: true});
  const d = document.createElement('div');
  d.className = 'eng on';
  d.innerHTML = `<span>${j.name}</span><span>${j.kind}, ${j.size} B</span>`;
  d.onclick = () => { document.querySelectorAll('.eng').forEach(x => x.classList.remove('on'));
                      d.classList.add('on'); select(j.path); };
  $('list').prepend(d);
  select(j.path);
}

async function play() {
  if (!cur) return;
  const q = new URLSearchParams({engine: cur.path, note: $('note').value, seconds: $('secs').value});
  P.forEach((v, i) => q.set('p' + i, v));
  $('go').disabled = true;
  $('status').textContent = 'rendering…  (interpreter ~0.23x realtime)';
  try {
    const t0 = performance.now();
    const r = await fetch('/api/render?' + q.toString());
    if (!r.ok) { $('status').textContent = await r.text(); $('go').disabled = false; return; }
    const peak = r.headers.get('X-Peak'), env = JSON.parse(r.headers.get('X-Envelope') || '[]');
    const cached = r.headers.get('X-Cached') === '1';
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    $('au').src = url; $('au').play();
    $('dl').style.display = 'inline'; $('dl').href = url; $('dl').download = cur.name + '.wav';
    plot(env);
    $('status').textContent = `${cached ? 'cached' : 'rendered'} in ` +
      `${((performance.now() - t0) / 1000).toFixed(1)} s   peak ${peak} full scale`;
  } catch (e) { $('status').textContent = 'failed: ' + e; }
  $('go').disabled = false;
}

function plot(env) {
  const c = $('plot'), x = c.getContext('2d');
  x.fillStyle = '#0a0a10'; x.fillRect(0, 0, c.width, c.height);
  if (!env.length) return;
  x.strokeStyle = '#7fd1ff'; x.lineWidth = 2; x.beginPath();
  env.forEach((v, i) => {
    const px = i / (env.length - 1) * c.width;
    const py = c.height - Math.min(1, v) * (c.height - 12) - 6;
    i ? x.lineTo(px, py) : x.moveTo(px, py);
  });
  x.stroke();
}

init();
</script>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass                                     # a quiet console is a usable console

    def _send(self, code, body, ctype="text/plain", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self._send(200, PAGE, "text/html; charset=utf-8")
            if u.path == "/api/engines":
                out = []
                for p in find_engines():
                    try:
                        i = describe(p)
                        out.append({"name": i["name"], "kind": i["kind"], "size": i["size"], "ok": True})
                    except Exception as e:
                        out.append({"name": p.name, "kind": "unreadable", "size": p.stat().st_size,
                                    "ok": False})
                return self._send(200, json.dumps(out), "application/json")
            if u.path == "/api/info":
                i = describe(resolve(q["engine"]))
                return self._send(200, json.dumps({"name": i["name"], "path": i["path"], "size": i["size"],
                                                   "base": i["base"], "kind": i["kind"],
                                                   "exports": i["exports"]}), "application/json")
            if u.path == "/api/render":
                info = describe(resolve(q["engine"]))
                params = [int(float(q.get(f"p{i}", 0.5)) * (1 << 28)) & 0xFFFFFFFF for i in range(8)]
                path, stats, cached = cached_wav(info, int(q.get("note", 69)),
                                                 float(q.get("seconds", 1.2)), params)
                return self._send(200, path.read_bytes(), "audio/wav",
                                  {"X-Peak": str(stats.get("peak", 0)),
                                   "X-Envelope": json.dumps(stats.get("envelope", []))[:4000],
                                   "X-Cached": "1" if cached else "0"})
            return self._send(404, "not found")
        except Exception as e:
            return self._send(500, f"{type(e).__name__}: {e}")


def serve(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"opzenginetool: {url}   (ctrl-c to stop)")
    print(f"  {len(find_engines())} modules discovered; renders cached in {CACHE}")
    if sys.stdout.isatty():
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


def main(argv):
    if "--selfcheck" in argv:
        engines = [p for p in find_engines() if p.name == "struck.engine"] or find_engines()[:1]
        if not engines:
            raise SystemExit("no .engine found")
        info = describe(engines[0])
        print(f"{info['name']}  {info['size']} B  base 0x{info['base']:08x}  {info['kind']}")
        import time
        t0 = time.time()
        path, stats, cached = cached_wav(info, 69, 1.0, [int(0.5 * (1 << 28))] * 8)
        print(f"  {'cached' if cached else 'rendered'} in {time.time()-t0:.2f} s  peak {stats['peak']}")
        samples, _ = render_clip(info, 69, 0.3, [int(0.5 * (1 << 28))] * 8)
        print(f"  measured pitch {S.measure_freq(samples, window=4096):.1f} Hz (expect ~440)")
        return 0
    port = int(argv[argv.index("--port") + 1]) if "--port" in argv else DEFAULT_PORT
    serve(port)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
