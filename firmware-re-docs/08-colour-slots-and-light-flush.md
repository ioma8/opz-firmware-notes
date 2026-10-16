# 08 — The colour-slot engine, its palette, and the change-only light flush

Doc `05` §5.8b/§5.8c ended on two named next steps: `FUN_8003d56e` (the "16-slot writer") and the block at
`0x801fa74`. This document is the first of those. It turned out to be a complete **lighting engine**: a per-slot
RGBA-plus-mode record, a two-variant colour palette with an interpolating lookup, three parallel buffers, a
**change-only** packet builder with a **60-tick blink phase**, and a transport that hands the packet to a
**companion chip** — a receiver inferred from the payload's shape, since the sender turned out to be shared
(§8.5). The most likely one is the PSoC, whose own image contains `..\PSOCCommon\leddriver.c` (doc `07` §7.4).

Everything here is `[FW]` — statically recovered from `opz.ldr` — except where a sentence says otherwise.

## 8.1 The slot record is five bytes, and four routines write it

One global array, addressed **absolutely** by every writer, so there is no ambiguity about which structure it
belongs to:

```
0x802d3a4   the slot table
```

| routine | effect on the 5-byte record at `0x802d3a4 + slot*5` |
|---|---|
| `FUN_8003d3be(slot, r, g, b, w)` | the raw setter — copies the four arguments in and writes mode tag `0` |
| `FUN_8003d56e(slot, value, level)` | `[ index, blend(idx,1,level), blend(idx,2,level), pal3[idx] * (level+1) >> 8, 0 ]` where `idx = value >> 4` |
| `FUN_8003d352(slot, value, level)` | the same palette colour into **all four** components, each scaled by `(level+1) >> 8`, and mode tag `1` |
| `FUN_8003d3f0(slot, value, level)` | a third variant of the same arithmetic |

The mode tag is what matters later: `FUN_8003d352` writes **`1`** into byte 4, the other two writers write `0`.
A tag of 1 is treated as **"blinking"** by the flush in §8.4, so the split is *steady* versus *blinking* slots,
not a current/previous marker.

Two routines clear parts of the same block, and **they disagree about its extent**, which is how the internal
layout was found:

```c
void FUN_8003d5e0(void) { memset(0x802d3a4, 0, 0x109); }   /* 265 bytes */
void FUN_8003d600(void) { memset(0x802d3f4, 0, 0x078); }   /* 120 bytes, starting 0x50 in */
```

`0x109` = 265 = **53 × 5**, so the allocation is 53 slot records wide, and the second clearer starts at offset
`0x50` = 80 = **16 × 5** and covers 24 records. That gives three regions rather than one:

| region | offset | size | reading |
|---|---|---|---|
| `0x802d3a4`–`0x802d3f3` | `+0x00` | 80 B | the **16 slots** the callers actually address (`slot` 0–`0xf`) |
| `0x802d3f4`–`0x802d46b` | `+0x50` | 120 B | cleared separately by `FUN_8003d600`; 24 further records by stride |
| `0x802d46c`–`0x802d4ac` | `+0xc8` | 65 B | the tail, including the two bytes §8.5 keys its GPIO lines on |

65 bytes of tail is not a round number, so the *third* region is stated as "whatever follows the two cleared
ranges" rather than as a record array. What is certain is that the two clearers treat the allocation as
**more than one array**, which resolves an ambiguity doc `05` §5.8c flagged: offsets like the frame sender's
`+0xc8` and the fade counter's `+0xcc` land inside *a* 5-byte-stride array, so they can only be separate fields
if the caller's base is not `0x802d3a4`. Both readings are still live; see §8.6.

**Three parallel copies of the whole allocation exist, 268 bytes apart**, which is what makes a diffing flush
possible at all:

```
0x802d3a4   current
0x802d4b0   previous            (0x802d3a4 + 0x10c)
0x802d5bc   the outgoing packet (0x802d4b0 + 0x10c)
```

## 8.2 The palette: ten colours in two variants

`FUN_8003d56e`/`FUN_8003d352`/`FUN_8003d3f0` all index **one** 4-byte-per-entry table at **`0x81015fec`**, and
`FUN_8003d48a` reads a **second** base at **`0x81016014`** — which the disassembly materialises as the split
immediate `-0x7efe9fec`, i.e. `0x81015fec + 0x28` = **ten entries further on**. So it is not two tables: it is
one 20-entry array read at `i` and at `i + 10`. The image bytes:

```
81015fec  ff 00 00 00  00 ff 00 00  00 00 ff 00  3a f0 00 00
81015ffc  00 00 00 ff  8c f5 00 00  00 d9 ff 00  7f 00 ff 00
8101600c  14 00 d7 00  a0 be 00 00  ff 00 00 00  00 ff 00 00
8101601c  00 00 ff 00  3a f0 00 00  00 00 00 ff  b4 dc 00 00
8101602c  00 d9 ff 00  7f 00 ff 00  28 00 d7 00  a0 be 00 00
```

| idx | RGB | colour | idx | RGB | colour |
|---|---|---|---|---|---|
| 0 | `ff 00 00` | red | 10 | `ff 00 00` | red |
| 1 | `00 ff 00` | green | 11 | `00 ff 00` | green |
| 2 | `00 00 ff` | blue | 12 | `00 00 ff` | blue |
| 3 | `3a f0 00` | yellow-green | 13 | `3a f0 00` | yellow-green |
| 4 | `00 00 00` | black | 14 | `00 00 00` | black |
| 5 | `8c f5 00` | lime | 15 | **`b4 dc 00`** | **brighter lime** |
| 6 | `00 d9 ff` | cyan | 16 | `00 d9 ff` | cyan |
| 7 | `7f 00 ff` | violet | 17 | `7f 00 ff` | violet |
| 8 | `14 00 d7` | blue-violet | 18 | **`28 00 d7`** | **brighter blue-violet** |
| 9 | `a0 be 00` | olive | 19 | `a0 be 00` | olive |

**The two halves are identical except at entries 5 and 8** — the two *interpolated* hues — where the second
half is brighter (`8c f5 00` → `b4 dc 00`, `14 00 d7` → `28 00 d7`). That is the design of a ten-colour
palette whose mixed hues need a second, brighter variant so they do not read as muddy at high intensity.
Entry 4 is `00 00 00 ff`: black in the RGB components with the **fourth** component at full scale, which is
why `0x4f` (`value >> 4` = 4) is the "off" value the callers use.

## 8.3 The lookup interpolates between the two halves

`FUN_8003d48a(index, component, level)` is the palette lookup every slot writer goes through, and its blend
factor is a **piecewise ramp on the level**:

```c
int FUN_8003d48a(int index, int component, int level)
{
  int k;                                   /* 0..0xff, weight of the BRIGHT half */
  if      (level < 0x40) k = 0xff;                     /* 0..0x3f : pure bright   */
  else if (level < 0xc0) k = (level - 0x40) * -2 + 0xff;/* 0x40..0xbf : ramp to 0 */
  else                   k = 0;                        /* 0xc0..0xff : pure dim   */

  v = k * pal[index + 10][component] + (0xff - k) * pal[index][component];
  v = (v * 0x80808081) >> 32;              /* / 255, 0x80808081 being the reciprocal */
  return (v * level) >> 8;                 /* then scale by the level itself */
}
```

So the level does two things at once: below `0x40` the colour is taken from the **bright variant** and scaled
down (a bright hue that is barely on), above `0xc0` from the **dim variant** scaled up (a full-intensity dim
hue), and in between the two variants cross-fade. That is the standard trick for "keep the hue readable across
the whole brightness range", and it is why the palette needed two variants rather than one.

## 8.4 The flush: change-only packets, with a blink phase

`FUN_8003d1e0(phase, &length)` builds the outgoing packet by diffing the current table against the previous
one. It is the routine that makes the three parallel buffers make sense:

```c
char *FUN_8003d1e0(int phase, int *outLen)
{
  int last = B[0x81015fe8];                 /* the previous phase */
  B[0x81015fe8] = phase;
  char *cur = (char *)0x802d3a4;
  char *prev= (char *)0x802d4b0;
  char *out = (char *)0x802d5bc;
  int len = 0;
  for (int i = 0; i < 0x35; i++, cur += 5, prev += 5) {   /* 53 records */
    if (i == 0x33) continue;                 /* record 51 is skipped outright */
    int changed = !(cur[0]==prev[0] && cur[1]==prev[1] &&
                    cur[2]==prev[2] && cur[3]==prev[3]) || cur[4] != prev[4];
    int blink   = cur[4] != 0;               /* the mode tag of §8.1 */
    if (changed || (blink && phase != last)) {
      int c  = (blink && phase != last && phase == 0) ? 0 : cur[0];
      int c2 = (!blink || phase == last || phase != 0) ? cur[3] : 0;
      out[len+0] = 0x00; out[len+1] = i; out[len+2] = c;
      out[len+3] = 0x00; out[len+4] = 0x00; out[len+5] = c2;
      memcpy(prev, cur, 5);                  /* accept it as the new baseline */
      len += 6;
      if (len + 6 > 0xa0) { *outLen = len; return out; }
    }
  }
  *outLen = len; return out;
}
```

Four things are worth stating plainly.

**The packet is a stream of 6-byte records `00 <index> <c> 00 00 <c2>`.** Three of the six bytes are
**constants** in the code (`out[0]`, `out[3]`, `out[4]` are always zero), so this is a fixed-width record with
reserved fields rather than a packed channel triple. What the receiver makes of the three zero bytes is not
read here and is **not guessed at**.

**Only changes are sent, and the "previous" buffer is updated as each record is emitted** — so the diff
re-baselines per record and a record that is flushed is never flushed twice for the same change.

**Mode-tag `1` means blinking, and blinking entries are re-sent whenever the phase flips** — which is why the
phase is an argument and why `0x81015fe8` caches the last one. A blink therefore costs one packet per
half-cycle, and steady entries cost one packet per actual colour change.

**The packet is capped.** The loop stops once the next record would take the length past `0xa0` (160) bytes. At
6 bytes per record the largest packet it can emit is **`0x9a` (154) bytes**, i.e. 25 records.

## 8.5 The 60-tick blink tick, and the two GPIO lines

`FUN_801313f4(ctx, table)` is the ticker. It derives the phase from a counter that is kept modulo **60**, and
calls the flush with it:

```c
void FUN_801313f4(int ctx, int table)
{
  counter = (counter + 1) % 0x3c;            /* the counter lives at 0x815c94b0 */
  int phase = counter < 0x1e;                /* first half of the cycle */
  int len;
  int packet = FUN_8003d1e0(phase, &len);
  if (len != 0) {
    FUN_11a01d24(ctx + 4, 0x10, packet, len, 0xffffffff, 0, 0xff, 0xff);   /* see below */
  } else {
    /* nothing to send: service two GPIO direction lines instead */
    if (B[table + 0xff] != B[0x815c94b4]) { B[0x815c94b4] = B[table + 0xff];
      if (B[table + 0xff] == 0) FUN_8002b388(DAT_0801ed7c, DAT_0801ed80);
      else                      FUN_8002b3b6(); }
    if (B[table + 0x100] != B[0x815c94b5]) { B[0x815c94b5] = B[table + 0x100];
      if (B[table + 0x100] != 0) FUN_8002b3b6();
      else                       FUN_8002b388(DAT_0801ed84, DAT_0801ed88); }
  }
}
```

**The `% 60` is confirmed from the arithmetic, not from the decompiler's loop.** `counter + 1` is multiplied by
`0x88888889` with the high word taken, shifted right by 5 (the `/32` step of the divide-by-60 reciprocal) and
multiplied back by `0x3c`, and the product subtracted — the compiler's divide-by-constant, so the counter really
is a 0–59 tick and the phase really is "first half".

**The transport is the shared companion sender, and its receiver is read from a sibling message.** `FUN_11a01d24`
is the **L1-overlay sender** already documented as the Blackfin→companion channel (doc `04` §4.6, where the
`Set button debounce` setter calls `FUN_11a01d24(ctx+4, 0x14, buf, 2, 0xffffffff, 0, 0xff, 0xff)` for a
two-byte message). The call here matches that signature argument for argument — the context as the first
argument, the same `0xffffffff, 0, 0xff, 0xff` tail, the second argument as the message type — so the light
flush is a companion message of type **`0x10`** carrying up to 154 bytes, against `0x14` for the debounce
setter.

**The sender is shared, so the call site alone would not say which chip receives it** — doc `04` §4.6b found
the same sender in `command_handler_ble.cpp` sending a one-byte type `0x13` message, i.e. the **Nordic BLE**
handler, not the PSoC. What *does* settle it is the **context object**: `FUN_801313f4` is called as
`FUN_801313f4(&DAT_0801fb90, &DAT_0802d3a4)` from `FUN_8003d620`, and inside it the sender is handed
`0x0801fb90 + 4` — while the one companion message in the image whose own log string names its destination,
`send debug flags to psoc: %d`, sends from `&DAT_0801fb94` (`FUN_80123828`, doc `04` §4.6b). **The same context.**
So the light flush and the PSoC debug-flag message travel on one channel, and the flush's receiver is the
**PSoC** — which is also the chip whose image carries `..\PSOCCommon\leddriver.c` and a 256-entry brightness
curve fed by a 144-field register set (doc `07` §7.4), the receiver an RGBA-and-blinking slot table implies.

The two fallback lines are unambiguous *because their callees are*: `FUN_8002b388` and `FUN_8002b3b6` write
**GPIO direction registers** —

```c
void FUN_8002b388(int port, int mask) {                       /* release / tristate */
  if (mask != -1) { REG_PORTA_DIR_CLR[port * 0x20] = mask;
                    REG_PORTA_INEN_SET[port * 0x20] = mask; } }
void FUN_8002b3b6(int port, int mask) {                       /* drive */
  if (mask != -1) { REG_PORTA_DIR_SET[port * 0x20] = mask;
                    *(int *)(REG_PORTA_INEN_CLR + port * 0x80) = mask; } }
```

— with the `0x20`/`0x80` stride that indexes a GPIO port block. So two bytes of the tail region
(`table + 0xff` and `table + 0x100`, cached at `0x815c94b4`/`0x815c94b5`) each flip a **pin between input and
output**. A pin that is driven or released, not a pin that is set high or low, is a **handshake or reset line**
rather than a data line — the shape you expect for the enable/reset line of the companion that receives the
packet. This is stated as the mechanical fact plus the reading it supports; the *purpose* of the two pins is
not established here.

## 8.6 What this does and does not settle about the DMX path of doc 05

Doc `05` §5.8c left `FUN_8003d56e` and the block at `0x801fa74` as open items. One of them is now closed and
one has moved.

**Closed: `FUN_8003d56e` is a light-slot setter, and its colour comes from a palette, not from a channel
number.** The arithmetic is decisive: the second argument is used as `value >> 4` to index a palette, which is
a **colour-wheel** encoding, and the caller in `FUN_80123568` passes the two literal values `0x4f` and `0x1f`
that select palette entries 4 (black — off) and 1 (green). Nothing in the routine consumes a raw channel byte.

**Moved: the DMX controller's address is now read from its initialiser instead of inferred.** `FUN_8003c5a4`
ends with an explicit publication of its own argument —

```c
  ...
  param_1[0xe] = 0;
  *puVar1 = 0;                 /* param_1[0xf] */
  DAT_81015e9c = param_1;      /* <-- the global the DMX call sites all load */
  FUN_04022ea8(param_1 + 0x28, 0, 0x12);
  for (iVar2 = 0x18; iVar2 != 0; iVar2--) *++puVar1 = 0;
```

— and its only caller in the image passes a literal: `0x8003d1c8` loads `R0 = 0x802d2f0` and calls it. So the
DMX controller singleton lives at **`0x802d2f0`**, and its initial field values are exactly as doc `05` §5.8
describes them (index 7 = `0x4f`, index 8 = `0x1f`, sentinels elsewhere, an 18-byte zeroed run at `+0xa0`, then
24 more zeroed dwords). That turns a previous "publishes its pointer at `DAT_81015e9c`" into a read fact with a
concrete base address.

**Still open, and now precisely bounded.** `0x802d3a4` is `0x802d2f0 + 0xb4`, and the lighting-track call sites
use `param_1 + 0xb4`/`+0xb8`/`+0xbc`, `+0xc8` and `+0xcc` — offsets that would land **inside** a 5-byte-stride
slot record if `param_1` were the controller. `+0xcc` is the clearest case: doc `05` §5.8 reads it as a fade
counter decremented by `0x14` per call, which cannot be a slot's mode tag. So exactly one of these is true, and
this round did not settle which:

1. the three lighting callers are handed a **different** base (their own structure, adjacent in the same
   allocation area) and only chance puts it `0xb4` bytes from the controller; or
2. the slot table **is** a field of the controller and the offsets `+0xc8`/`+0xcc` mean something other than
   what doc `05` §5.8b/§5.8c read them as.

What can be said without resolving it: the enclosing rodata window for the whole `0x8003c6xx`–`0x8003d6xx`
cluster contains **one** source path, `C:\snake-software\src\sequencer\DmxController.cpp` at `0x81015be0`, and
no other `C:\snake-software` string between `0x81015a00` and `0x81015e78` — so the cluster sits with
`DmxController.cpp` even though no log call inside the colour-engine functions was found to bind them
individually. A one-line experiment for a future session: find a log call inside `FUN_8003d1e0`'s or
`FUN_8003d56e`'s neighbourhood and decode its file-path immediate.

**One consequence for doc `05` worth naming.** If the slot table is the DMX controller's and the packet reaches a
companion that drives the unit's own lights, then the "OP-Z DMX preview" the vendor readme describes is realised
as **the OP-Z's own LEDs being driven from the DMX fixture state** — which is what §5.8c already concluded from
the other direction, when it found that the twelve "ignored" notes own preview slots 1–12. The two readings
agree; only the ownership of the table's base address is unsettled.

## 8.7 Method notes

- **`FindXImm` finds materialised addresses, never calls.** All of `FUN_8003d48a`, `FUN_8003d56e`,
  `FUN_8003d352`, `FUN_8003d1e0` and `FUN_8003d3be` return **zero** hits for their own addresses, because the
  Blackfin `CALL` encodes a PC-relative displacement. `CallersOf` (Ghidra's reference database) is the tool for
  call sites, and it works only where the call site is already disassembled: `FUN_8003d56e` reports **200**
  recorded call sites (its query page limit, so that is a **lower bound**) across `0x8003c7xx`–`0x8003d1xx`,
  `0x8011dxxx`, `0x80120xxx`–`0x80126xxx` and `0x80031c6c`/`0x800427b8`, while `FUN_8003d1e0`, `FUN_8003d620`
  and `FUN_801313f4` have one or two. `FUN_8003c5a4` reports exactly **one** (the wrapper at `0x8003d1c8`), which
  is what makes the `0x802d2f0` base in §8.6 a read fact rather than a sample.
- **The `0x8003d1xx`–`0x8003d6xx` region has no Ghidra functions at all** — every routine in this document had
  to be created from a prologue. `FnAt2` reports `(none)` for addresses that plainly are function entries, so
  the absence of a function is not evidence about reachability, only about coverage.
- **A decompiler "unreachable block" can hide the interesting half.** `FUN_801313f4`'s send path was dropped as
  *Removing unreachable block (ram,0x801314b2)*; the send is **at** `0x801314b2`, and it only exists in the
  disassembly. Reading the raw range was what produced §8.5's transport finding.
- **Register-carried arguments look like missing parameters.** Several calls decompile as
  `FUN_8003d48a(idx, 1)` with the third argument gone; the third argument is still in `R2` from the caller and
  is the level. Count the arguments in the disassembly before concluding a callee takes fewer.

## 8.8 Method: binding a function to its source file

Two attempts are worth recording, because one of them works and the other is a trap.

**It works to resolve the log call sites.** Every `(file, line, format)` log in the image goes through
`FUN_8012f1e4`, and all three arguments are materialised addresses or literals at the call site. A short script
(`LogMap.java`) that walks a code range, finds every `CALL FUN_8012f1e4`, and then walks **backwards** over the
preceding instructions resolving address-shaped scalars yields a `function → file:line → format` map for a whole
region without decompiling anything. Applied to `0x8003a000`–`0x8003d800` it finds exactly **six** log call
sites, all of them `DmxController.cpp`, and the table is in doc `05` §5.8.

Two details make the difference between a usable map and a wrong one:

- **The line number is the value loaded into `R1` immediately before the call**, not the nearest small scalar.
  A "nearest small scalar" heuristic reported `3`, `12` and `24` for call sites whose real lines are `620`, `316`,
  `353`, `358` and `480` — it was picking up loop bounds. Anchoring on `LdImmToReg R1 = …` reproduces the one
  line that had already been decoded by hand (`620`), which is what makes the rest trustworthy.
- **The raw hi/lo byte-pair fallback produces false positives.** Resolving a path from the two 16-bit halves in
  the preceding bytes is needed for instructions the analyser did not pattern-match, but it also matches
  unrelated encodings and yields empty or single-character strings; only the fused-immediate lines should be
  quoted.

**It does *not* work to assume a translation unit's globals sit next to its own `__FILE__` string.** That was
worth testing, because it would have bound both open questions in this document outright — the palette's owner
and the ticker's file. It half-holds and then fails:

- *consistent with it:* the DMX controller's state words (`0x810159d4`–`0x810159e5`), its `__FILE__` string
  (`0x81015be0`), its log format strings (`0x81015ccc`–`0x81015e78`) and the light palette (`0x81015fec`) all
  fall inside one contiguous `0x810159d4`–`0x8101603b` region.
- *contradicts it:* the light ticker's state (`0x815c94b0`–`0x815c94b5`) and the PSoC power-mode byte
  `DAT_815c94ac` sit **between** `command_handler_ble.cpp`'s path string (`0x815c90d8`) and
  `command_handler_kb.cpp`'s (`0x815c9514`) — so by the hypothesis those bytes belong to the BLE handler, yet
  `DAT_815c94ac` is written by the **PSoC** (`kb`) power handlers of doc `07` §7.4c.

So proximity to a `__FILE__` string is a **hint about which file to check first**, not a binding, and the open
item in §8.6 stays open — which is the more important half of the result, because the hint is exactly the kind
of thing a later session would over-trust.

**One consequence that *is* firm.** The colour cluster `0x8003d1xx`–`0x8003d6xx` contains **no log call at all**,
so the log map cannot bind it — but the *absent* binding is not evidence of a different file either. Its transport
(§8.5) rests on two things that do not depend on the source file: the argument **shape** (the context as the first
argument plus the literal tail `0xffffffff, 0, 0xff, 0xff`, which is the signature the documented
`Set button debounce` PSoC message uses, doc `04` §4.6) and the **context identity** (`0x0801fb94`, shared with
the one message in the image that names its destination as the PSoC).
