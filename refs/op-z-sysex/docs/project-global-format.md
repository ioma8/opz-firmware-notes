# OP-Z Project-Global `$0C` Format

Status: all eight named scalar writes device-proven on 2026-07-27 with
firmware `1.2.45+`. Saved-chain storage and writes were proven separately.

## Wire Form

StateSync message `$0C` carries one standard zlib stream inside the OP-Z
manufacturer SysEx envelope:

```text
F0 00 20 76 01 0C <7-bit-packed zlib data> F7
```

The stream must inflate to exactly 568 bytes (`0x238`). The installed official
`SnakePlugin` implementation:

- compresses exactly `0x238` bytes in `StateSync::sendGlobalData`;
- inflates directly into the active project's `GlobalData` object in
  `StateSync::applyGlobalData`;
- reads and writes exactly `0x238` bytes in project-file versions 70 through
  73; and
- constructs `GlobalData` as a 568-byte object.

This makes `$0C` a direct serialized runtime/project structure, not an app-only
wrapper.

## Byte Layout

All multibyte integers are little-endian.

| Offset | Size | Meaning | Evidence |
| ---: | ---: | --- | --- |
| `0` | 480 | Saved-chain slots 1...15, 32 bytes each | Device-proven |
| `480` | 32 | Live active-chain buffer | Device-proven |
| `512` | 1 | Drum group level | Native setter and device write |
| `513` | 1 | Synth group level | Native setter and device write |
| `514` | 1 | Punch group level | Native setter and device write |
| `515` | 1 | Master group level | Native setter and device write |
| `516` | 2 | Tempo, unsigned 16-bit BPM, clamped `40...200` | Native getter/setter and device write |
| `518` | 43 | Opaque retained bytes | No current desktop-runtime references; preserve |
| `561` | 1 | Drum swing | Native setter and device write |
| `562` | 1 | Metronome level | Native setter and device write |
| `563` | 1 | Metronome sound/type | Native setter and device write |
| `564` | 1 | Selected saved-chain slot, signed zero-based; `FF` means none | Native select/save/UI paths |
| `565` | 3 | Opaque retained bytes | No current desktop-runtime references; preserve |

Each chain record is terminated by the first `FF`. Slots 1...15 are saved
chains; record 16 is the current live buffer. Firmware `1.2.45+` executes at
most 31 chain entries even though each record occupies 32 bytes.

Byte `564` does not describe the live cursor. Selecting saved-chain slot `n`
copies record `n` into record 16 and stores zero-based `n` at byte `564`.
Saving the live buffer into a slot stores the same value. Pattern-chain
position during playback is reported by `$07`.

## Constructor Defaults

The native `GlobalData::GlobalData` constructor establishes:

```text
0...511   FF
512       80
513       80
514       00
515       00
516...517 78 00  (120 BPM)
518...560 00
561       7F
562       64
563       00
564       FF
565...567 00
```

The 46 opaque bytes are not safe scratch space. The attached device had one
nonzero opaque byte at offset `525` (`A0`) even though the constructor starts
that region at zero. They may be retained legacy state or accessed through
indirect code not visible as fixed-address references. A host editor must
preserve them from a fresh device baseline.

An audit of current `z-po-project`, `libopz`, and `opzdoc` did not resolve
these bytes. Their older community structure treats tempo as one byte followed
by 44 unknown bytes, while the current official ABI and hardware proof establish
tempo as a two-byte little-endian value. Historical local captures also show
project-specific nonzero values at offsets `518`, `519`, `525`, and `560`.
Treat the region as retained opaque state, not padding.

### Native Reference Audit

The installed x86-64 `SnakePlugin` was disassembled and every fixed reference
into the 568-byte `GlobalData` member was enumerated. Current code references:

- chain bytes `0...511`;
- group levels `512...515`;
- tempo `516...517`;
- swing and metronome bytes `561...563`; and
- selected-chain byte `564`.

No instruction references offsets `518...560` or `565...567`. The constructor
zeros them, and project-file versions 70 through 73 load and save them only as
part of the complete 568-byte structure. This closes the current desktop-app
side: those bytes have no named behavior in the shipped companion runtime.

It does not prove that OP-Z firmware never reads them. Firmware `1.2.45` is
stored in an encrypted ZFW container, and real device captures retain nonzero
values. A clean editor must therefore continue preserving all 46 bytes.

## Reversible Device Proofs

Project 1 initially reported 124 BPM (`7C 00`). The clean proof tool:

1. captured a fresh 568-byte `$0C` block;
2. changed only offset `516` from `7C` to `7D`;
3. uploaded the recompressed block;
4. reconnected and received a byte-exact copy of the intended block;
5. uploaded the original block; and
6. reconnected and received the byte-exact original.

`written-global.bin` and `readback-global.bin` share SHA-256
`8fa8170d41d699c1ba68f176463d26e5363c624e8c7b418a2b319eeb5c3809f7`.
`before-global.bin` and `restored-global.bin` share SHA-256
`bd235be0b39654f63319dd10a6c22a71f5ce58c136242a7665bfd918f2011942`.
The captures are in
the private evidence ledger (private evidence; not distributed).

A second suite independently changed every mapped scalar. Each intended block
matched fresh readback, each exact baseline was restored, and the suite's
initial and final blocks shared SHA-256
`bd235be0b39654f63319dd10a6c22a71f5ce58c136242a7665bfd918f2011942`.
See the
all-scalar proof (private evidence; not distributed).

Build the tool:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Run the complete unattended suite:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Run one reversible field proof with:

> The historical live harness is not distributed. Use the Python APIs for offline framing and validation.

Supported field names are `drum`, `synth`, `punch`, `master`, `tempo`,
`swing`, `metronome-level`, and `metronome-sound`.

## Editor Safety

`OPZProjectGlobalEditor` edits only the mapped offsets above. The app's Project
workspace performs one atomic transaction:

1. force a fresh `$0C` snapshot;
2. derive the edit from those exact 568 bytes;
3. change only requested mapped fields;
4. upload one `$0C` frame;
5. force another full snapshot and require byte-exact readback; and
6. restore the original block and verify it if confirmation fails.

This proves immediate runtime readback. It does not by itself prove
power-cycle persistence. Saved `$0C` data has separately survived
`debug-save` plus project reload, but a physical power-cycle test remains.

## External References

- [`lrk/z-po-project`](https://github.com/lrk/z-po-project) documents the
  community project structure.
- [`leddy231/libopz`](https://github.com/leddy231/libopz) implements OP-Z
  StateSync and project decoding.
- [`MarkRdgOx/opzdoc`](https://github.com/MarkRdgOx/opzdoc) documents the
  manufacturer SysEx envelope, 7-bit packing, and message inventory.

The exact scalar types, constructor defaults, selector semantics, and native
setter names above come from local clean-room analysis of the official
companion protocol and are not claimed by those repositories.
