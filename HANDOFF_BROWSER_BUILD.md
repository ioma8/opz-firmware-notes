# Handoff: the clone plays in a browser

`opz-clone` commit `cf3c595` adds a **browser build of the same ported engine** — the request was
"make it run in the browser with a minimalist GUI, and quickly, but with the good final visuals".
Nothing in `opz-dsp` changed to get there: `crates/opz-web` is a `wasm-bindgen` shell over
`opz-core`/`opz-dsp`, and `web/` is the page. The point is a build that can be opened in a browser
and checked against the terminal, not a second product.

## How to run it

```
tools/web.sh          # wasm-pack build → node tools/web-smoke.mjs → serve the repo root
                      # open http://localhost:8137/web/   (Ctrl-C to stop)
```

Serving the **repo root** is what makes `/web/`, `/samplepacks/*.aif` and `/projects/sample.json` all
resolve with nothing copied. Audio needs a click first (WebAudio's autoplay policy).

## What was decided, and why

The six decisions worth knowing are in `opz-clone/docs/WEB.md`; the two a reader would otherwise
question are ADRs. **ADR-0001**: the engine lives on the main thread behind a `ScriptProcessorNode`
and renders whole 4096-frame buffers (`Engine::render` keeps its own 64-frame staging), *not* in an
`AudioWorklet` — a worklet would put the engine behind a `postMessage` mirror for latency this demo
does not need, and a browser-only DSP shortcut must never be added to `opz-dsp` because that is a
fork in disguise. **ADR-0002**: the page fetches the real drum packs over HTTP and commits the
vendor's interface drawing as `web/op-z.svg` (`op-z-interface.txt` is the control map's source),
a deliberate deviation from the no-blobs/outside-git-asset rule, which is why the page is local-only
and a clone without the packs plays four silent drum tracks and says so.

The GUI is the device's own panel. The drawing is inlined at load, its keypad grid is read out of the
drawing's circles, and every control is an overlay in the drawing's coordinate space, so changing the
drawing moves the GUI. Top row of 16 keys = track slots (t1–t6 live), bottom row = the cursor track's
16 steps, the drawn ▷/□ = transport, the four dials = master/tempo/level/pan with the drawing's own
parameter LEDs in the documented colours, the four index buttons = project/mixer/tempo/log. Dark
theme by inverting the panel layer, so the LEDs keep their true colours.

## Verified

- **The browser plays what the terminal plays.** `tools/web-smoke.mjs` renders a bar of the sample
  project in the wasm build and compares it **sample for sample** with
  `opz-tui --project projects/sample.json --render … --bars 1`: **85 344 samples identical**, peak
  389 411 329 Q31 (−14.8 dBFS). Byte-identity is the right bar here because the load-time tables hash
  the same on `wasm32-unknown-unknown` and on this host (`sin`/`exp2`/`exp`/`sqrt`/`log2` over the
  wavetable and tuning tables → `90b728fac7f9efe5`), measured with a throwaway `/tmp` program.
- **The page runs in a real browser.** `tools/web-check.mjs` drives Chrome over the DevTools protocol
  (no npm dependency) and reports the drawing inlined, 16 step keys, 6 track keys, 4 dials, the packs
  and the 73-command project loaded, the **transport advancing** — which is what proves the audio
  callback is driving the engine — and no console errors, plus a screenshot. It is not part of the
  gate because it needs Chrome, and it earned its place: it caught the wasm module being used before
  `init()` resolved, a play button with no handler, the engine's status lines never displayed, and a
  read-out that showed the cursor but not the transport.
- `cargo test --workspace` stays green (100 tests) with `opz-web` as a workspace member, so an
  incompatible `opz-core` edit breaks the native build too.

## Not verified, and what is out of scope

Nobody has **listened** to the browser build; the offline TUI render is also still unheard. Touch on a
phone is untested (the page is desktop-first with `pointerdown`, no reflow). Out of scope by decision:
offline WAV export in the browser, saving projects, the 18-parameter strip, preset browsing, FX tracks
and effect plugs, and hosting (which would only change where the packs come from, not the engine).

Two shared entry points moved into `opz-core` so the two frontends cannot disagree: `parse_aiff`
(the browser has no filesystem) and `drum_pack_name`.
