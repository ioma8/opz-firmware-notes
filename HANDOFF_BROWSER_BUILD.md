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

## Second pass: the panel now works the way the manual says (commit `a4c755b`)

The first version was a reasonable approximation; it is now the device's own control language, taken
from teenage engineering's [interface overview](https://teenage.engineering/guides/op-z/interface-overview),
[quick guide](https://teenage.engineering/guides/op-z/quick-guide) and chapter pages (`track`,
`tracks`, `parameter-pages`, `mixer`, `tempo`, `project`, `general-operation`). The page reads its
mapping from that documentation, and `docs/WEB.md` records each section's behaviour plus the list of
device features the clone does not have — each of those answers a gesture with one status line rather
than doing something else.

What changed, in the manual's terms. Buttons **hold** to change context (§2.1), so one finger can
hold `track` while another taps a key. The top row is the track/pattern/step row: pressed alone it
places or clears a step (§3.4 — an empty step takes the last played note, a lit step clears, holding
a step copies it and a following empty step pastes), with `track` held it selects a track (§2.5),
with `mixer` held it mutes (§8.3), with `project` held it selects a pattern. The bottom row is the
**musical keyboard**: it plays the active track and, with `rec` held, records onto the step under the
playhead; the ten filled circles the drawing prints between the rows are the **value keys 1–0**
(projects with `project`, bpm digits with `tempo` — 1+2+0 is 120 — plug slots with `track`, mute
groups elsewhere). The dials are the **parameter pages** (§4.3's chart) over the clone's own
parameter table, `shift` toggles the page, a *held* `shift` makes a dial edit temporary (§2.11), and
`track`+dials reach note length, note style, quantize and portamento (§5.2). Transport is §3.2's:
play restarts, stop pauses, stop again is panic, `track`+stop clears the track. Step lights use the
device's language — programmed steps red, playhead white, cursor amber, microtiming purple.

It needed four engine commands, added to `opz-core`: `NoteOn`, `NoteOff`, `AllNotesOff` (panic) and
`SetOctave` (transpose, §2.10 — the sequencer's per-track octave already existed, only the setter was
missing). `opz-core`'s test `the_keyboard_plays_a_note_and_panic_releases_it` covers a played note
sounding with an empty pattern, panic releasing every track, and transpose shifting what the
sequencer plays without changing what the step stores. The workspace is green at 107 tests, and the
smoke test still reports 85 344 samples identical to the TUI's.

`tools/web-check.mjs` became 25 device gestures driven through synthetic pointers in a real Chrome
(hold-track select, hold-mixer mute, step programming, page toggle, tempo by dial and by value keys,
plug select, project select, transpose, play/restart/stop/panic). It caught two more bugs the smoke
test cannot see: the wasm called from a module-scope constant before `init()` resolved, and a global
`pointerup` that dropped a held modifier whenever another key was tapped — which breaks exactly the
two-handed gestures the device is built around.

## Third pass: 1:1 with the manual (commit `3a02c26`)

The gestures are now the manual's own, and a gesture the clone can back does the real thing instead
of reporting itself. What the second pass had approximated:

- **§3.2's panic ladder, all four rungs**: stop while stopped is panic, twice is super panic (kill
  every voice), `track`+stop is track panic (a release), twice is track super panic (a kill).
  `InstrumentManager::killAllNotes` and `killTrackNotes` were already ported in `opz-dsp` but had no
  caller, so these are the library's own functions now.
- **§3.4**: holding a *lit* step and pressing another step sets its **note length** (it used to paste),
  playing a note replaces the step memory, and holding a lit step while the sequencer is stopped
  previews it.
- **§5.2's note length** became an engine concept rather than the cursor step's duration:
  `TrackPattern` carries `note_length`, a newly entered note gets it, the dial moves only the notes
  still at the previous default, and the dial's far right is the manual's **drone mode**
  (`pattern::DRONE_DURATION`, a note the sequencer never releases).
- **§5.7 randomize preset** (`track`+`rec`) and **§7.10 bounce** (`project`+`rec`: ten seconds
  rendered by a second, silent `Engine`, handed to the page as a WAV download). The bounce is the
  device's own gesture, so `docs/WEB.md`'s earlier "no export in v1" line no longer describes it.
- **§9.3/§9.5**: tap tempo is the manual's — hold tempo and tap a white piano key; nudge is tempo
  with `–`/`+`, lock is tempo with shift. **§2.1's index lock** is a triple press that any index press
  releases.
- **§2.12's pitch bend** is real: the ported chain already had `Voice::pitchBend` and
  `InstrumentManager::pitchBend`, so a drag bends ±200 cents and springs back, and a held lit step
  turns the same drag into a velocity edit.
- **§1.1's volume knob** is the drawing's own left tab (SVG path 2), which also corrected the crop.
  **§2.10's transpose is "visualised by the value keys"**, so the current octave lights its value key.
- The rest of the manual's gestures exist and answer in one status line: §5.4 step length, §5.6
  presets, §5.10 track linking, §7.3-7.12 copy/chain/snapshot/autosave, §8.4-8.5 mute groups and
  mute-audio mode, §9.6-9.7 swing and metronome, §2.1's screen button and tempo+screen's MIDI
  settings, §3.4's per-step parameter locks.

Two bugs this pass found in the page: an index button's second press was swallowed as part of a
triple-press chain (so mute-then-unmute did nothing), and a stray pointer release on a second key
acted as a tap and erased a note — each top-row press is now paired with its own key.

`opz-core` gained `SetNoteLength`, `ClearBuffers`, `KillTrackNotes` and `PitchBend` with tests; the
workspace is green at 109 tests, the smoke test still reports 85 344 samples identical to the TUI's,
and `tools/web-check.mjs` is 53 checks of documented gestures, all passing in a real Chrome.

Two device behaviours remain approximations, both stated where used: the mixer's group gains move
every member of the group by the same amount (the clone has per-track levels, not a bus), and super
panic kills the notes while the master bus's own filter state keeps ringing for a few blocks (nothing
in `opz-core` clears it).

## Not verified, and what is out of scope

Nobody has **listened** to the browser build; the offline TUI render is also still unheard. Touch on a
phone is untested (the page is desktop-first with `pointerdown`, no reflow). Out of scope by decision:
offline WAV export in the browser, saving projects, the 18-parameter strip, preset browsing, FX tracks
and effect plugs, and hosting (which would only change where the packs come from, not the engine).

Two shared entry points moved into `opz-core` so the two frontends cannot disagree: `parse_aiff`
(the browser has no filesystem) and `drum_pack_name`.
