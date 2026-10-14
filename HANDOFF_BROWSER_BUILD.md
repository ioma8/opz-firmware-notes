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

## Fourth pass: one pointer (commit `32388e3`)

Reported from use: the `+` and `shift` keys seemed mapped onto step icons, and `track` was impossible
to use with a single mouse. Both were real.

**The one-pointer problem.** The device expects two hands — one holds `track` while the other presses
a key — and a mouse has one pointer. Every modifier now **latches on a click**: click `track`, click
the track, click `track` again (or `Escape`) to let go, with the button lit while latched. §2.1's
index lock (a triple press) was the device's own version of this and now lands in the same state. A
long press on a step likewise *keeps* it held, which is what makes §3.4's gestures reachable with one
pointer — its length from another step, its velocity from the pitch bend, its note from the keyboard,
its microtiming from `−`/`+`. `shift` keeps the manual's distinction (§2.11: "there is a difference
between holding and momentarily pressing shift"): a momentary press toggles the parameter page, a
held press latches so a dial edit reverts when shift is released.

**The unreadable left column.** The drawing's left column is three circles whose glyphs (`工`, `●`,
`—`) sit in the track, middle and step rows; unlabelled, they read as step functions. They are now the
keys their glyphs name — `track`, `rec`, `−` — each labelled, and the schematic's two omissions,
`shift` and `+` (the manual's transpose up, §2.10), sit left of that column, also labelled. The volume
knob and the pitch-bend strip are labelled too, and the header says "click a button to latch it · esc
releases".

**Three more bugs, all found by driving it**: an index button's second press was swallowed by the
triple-press chain (so mute-then-unmute did nothing); a stray pointer release on a second key acted as
a tap and erased a note; and shift's press state was assigned *after* the branches that return early,
so a shift used with the tempo dial stayed latched and never toggled the page again. The check now
prints the page's status tail on failure, which is how the last one was found.

`tools/web-check.mjs` is 57 checks (four new: the `−`/`+` panel keys, the latch and `Escape`); the
workspace stays green at 109 tests and the smoke test still reports 85 344 samples identical to the
TUI's.

## Fifth pass: the panel's layout (commit `d8e73e5`)

Reported once more from use: `shift`, `+` and `−` still did not look right. Two real problems, plus
the checks that now prevent them.

- The two keys the schematic does not draw (`shift`, `+`) were styled with the *drawn* keys' colours —
  dark text, meant for the light inverted panel — while sitting on the dark page, so their labels were
  invisible; and their boxes overlapped the column they sat beside. They are dark chips with light
  labels now, off the panel, with §2.10's transpose pair (`+` next to `−`) in the bottom row and
  `shift` beside `track`, all three labelled the way the drawn column already was.
- The **value keys were placed one column pair too early**, so pill 1 sat *on top of* the play and stop
  keys. They now start at the third pair, which is where the drawing prints them.
- The momentary transpose keys flash when pressed: a key that leaves no state behind showed nothing at
  all before.

Four of `tools/web-check.mjs`'s checks are **layout invariants** rather than gestures, because this is
the second time the panel's geometry shipped wrong: no two keys may overlap, every key with a name must
show it, `−` and `+` must be one row and adjacent (§2.10), and the keys the drawing lacks must sit off
the panel. The overlap invariant found the value-key bug on its first run.

`tools/web-check.mjs` is 61 checks, all passing in a real Chrome; the workspace stays green at 109
tests and the smoke test still reports 85 344 samples identical to the TUI's.

## Sixth pass: mapped to the drawing (commit `b2ca9d8`)

Reported from use: the controls worked but were not on the keys the SVG draws. Measuring the SVG
properly — every ellipse, the glyph inside it, and the printed marks around it — showed the drawing
names five dedicated keys that had been mapped elsewhere:

| drawn key | glyph | button |
|---|---|---|
| left column, top | `工` | track select (§2.5) |
| left column, middle | `●` | record (§2.7) |
| left column, bottom | `−` | transpose down (§2.10) |
| bottom row, 2nd column | `+` | transpose up (§2.10) |
| bottom row, 3rd column | `↑` | shift (§2.11) |
| middle row, columns 2 and 3 | `▷` `□` | play, stop (§2.8) |

So `+` and `shift` were drawn all along; keyboard keys had been sitting on them while shift and `+`
floated in the margin. The keyboard is that bottom row *from its third column on* — **14 white keys**,
which is exactly the manual's fourteen step components — playing C major over two octaves. The value
keys are the **black keys**, at boundaries 0,1,3,4,5,7,8,10,11,12 of those fourteen, which is why the
drawing prints ten of them.

Everything else moved to where the drawing has it: the parameter LEDs sit at each dial's lower-left
(from the path bounding boxes), the pitch bend is the pad at the bottom edge under the transport
(path 10 — the teardown puts the real one at the bottom left of the frame), the volume knob is path 2,
and the read-out lights the drawn 8-dot matrix's dot for the transport's position.

Two invariants were added, and they are what make this a measurement rather than a claim: every key
must sit within 3 SVG units of one of the drawing's 37 circles, and every value key must sit between
two white keys. Both pass, and the previous three (no overlap, every named key labelled, `−` and `+`
one key apart) still hold. `tools/web-check.mjs` is 62 checks; 109 tests; the smoke test still reports
85 344 samples identical to the TUI's.

## Seventh pass: the row means one thing at a time (commit `985d45d`)

Two reports from use, both correct and both mine:

- **the steps belong on the top row.** They had been lit and tapped on the *bottom* row, which is the
  musical keyboard. The top row is the device's track **and** step row: with `track`, `mixer` or
  `project` latched it is the track row (select, mute, pattern, the clone's six live and 7–16 dimmed),
  and on its own it is the active track's sixteen steps. The LED is the dot the drawing already prints
  inside each circle — red programmed, white playhead, amber cursor, purple microtiming — and it is
  where a step is tapped, held and cleared.
- **the eight dots are the speaker grille**, not a display. They had been lit as a playhead read-out;
  they are now drawn and inert, and the read-out text (the page's own element, since the clone has no
  screen) sits beside them.

The keyboard's keys lost their LEDs: a piano key lights only while it is played. Three browser checks
followed the move — the empty-step and step-light helpers were reading the keyboard, and the
hold-track+stop clear had to let go of `track` before its step lights could be counted, since the row
means "tracks" while it is latched. `docs/WEB.md`'s control-mapping table was also rebuilt: it still
carried browser v1's mapping (top row tracks, bottom row steps), which the device rewrite had already
contradicted in prose.

62 checks, 109 tests, the smoke test still reports 85 344 samples identical to the TUI's render.

## Eighth pass: the kit's slices, and the black keys as piano keys (`3df37d4`)

Two reports from use:

- **on a sample-based track, every piano key plays the same sound** — correct, and it was the port's.
  A drum track spreads its pack's 24 slices over two octaves of notes, and the note selects one
  through `SampleLoader::getSampleData`, whose rule the module header already documents as
  `(note + 19) % 24` clamped to the slice count. The code implemented the *golden harness's* stand-in
  instead, `note - 36` clamped, and the difference that matters is the wrap: two octaves above the drum
  base it runs off the end and every key lands on the pack's last slice. Measured on the old build,
  notes 36..59 gave distinct output and every note from 60 up gave peak 234 — one sound for the whole
  keyboard. Now the same keys give 106, 238, 298, 290, 300, 207, and a transposition walks on through
  the kit (four octaves returns to the start, since 48 semitones is two pack cycles).
- **the black keys should be piano keys too.** §2.9's ten black keys now play the semitone above the
  white key they sit on when no modifier is held (37, 39, 42, 44 for the first four — C major's
  sharps); with `project`, `tempo`, `track` or `mixer` held they are the value keys 1–0 as before, and
  with `shift` they report §2.11's punch-in effects as unavailable, like the white keys.

Two verification notes worth keeping:

- The **golden fixtures could never have caught this**, and no longer pretend to. This harness renders
  the original *silent for any slice but the first* — measured directly: slice 0 peaks at 8.9e8 and
  slices 2 and 7 come out at 0 — so a fixture generated with the device's rule would be silent. The
  fixture cases therefore play **note 29**, the one note where the device's rule and the harness's
  stand-in agree (both give slice 0), which keeps them valid whichever mapping the port implements,
  and regenerating them still passes byte for byte against the original. The stand-in and
  `FIRST_NOTE` both say why. The mapping is pinned by the port's own
  `note_maps_to_the_24_slice_pad_layout` unit test instead, which fails against the old rule.
- The **substitute packs** (`fabricated-sample-substitutes/`) are what `drum_pack_name` loads, and
  their slices are evenly cut rather than at hit boundaries: with the device's window (measured from
  the descriptor's length) the audio of a later slice can fall outside the window. That is a property
  of the fabricated data, not of the engine — the real packs symlinked into `samplepacks/`
  (`redmountKicks.aif`, …) are cut at hit boundaries and sound throughout.

65 browser checks, 109 tests, smoke test still byte-identical to the TUI's render.

## Not verified, and what is out of scope

Nobody has **listened** to the browser build; the offline TUI render is also still unheard. Touch on a
phone is untested (the page is desktop-first with `pointerdown`, no reflow). Out of scope by decision:
offline WAV export in the browser, saving projects, the 18-parameter strip, preset browsing, FX tracks
and effect plugs, and hosting (which would only change where the packs come from, not the engine).

Two shared entry points moved into `opz-core` so the two frontends cannot disagree: `parse_aiff`
(the browser has no filesystem) and `drum_pack_name`.
