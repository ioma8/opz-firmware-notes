# OP-Z asset pull — status (single canonical page)

Objective: retrieve the required device data read-only; distinguish downloaded from outstanding files.

## Current state (2026-10-16): the unit is recovered and plays

21 official engines in `/yaffs2/user/engines/`, 24 factory packs in `/yaffs2/user/samplepacks/`, the 8 donor
engines in `/yaffs2/system/content/engines/` and the merged plug table in `settings/plugs.json` (50 plugs, 0
slot-referenced ids undefined) are all verified by **reading them off the device** over the console `0x19` route —
see `FIRMWARE_ANALYSIS.md` §71.2 and `FW_SUCCESS.md` §31.

Before writing any console tool, read the framing trap in `SERIAL-COMMANDS-SET.md`: escaping the frame's leading
`C0` silences the device completely and mimics a dead console (`FIRMWARE_ANALYSIS.md` §71.1). Use
`toolkit/opzcopyprobe.py::encode` or `sergey-extraction/opzget.py::encode`.

The SysEx pull described below is a **separate channel** and matches registered file IDs, **not** paths: a
"missing" from it is not evidence of absence, and it cannot see the bootloader's own state files (§71.4).

## USB file pull works (2026-10-11)

The missing step was the protocol-version-6 StateSync hello before file advertisement.
Sequence: `$00(clientId, version=6)` → `$51` → device `$34` → `$52(active=0)` → `$35`/device `$53`.
Both `$00` and `$52(active=0)` must be refreshed during longer sessions. `$52` alone did not keep
USB replies alive through a long batch. No master claim, upload manifest or file data was sent.

Device: OP-Z, firmware `1.2.45+`; device/session identifiers omitted.

## Retrieved from the device

Saved under `~/.opz-decode/pulled/`:

| File | Bytes | Parts | SHA-256 |
|---|---:|---:|---|
| `settings/plugs.json` | 4,423 | 23 | `07a38b2894c3caa918bd391b3b871114216765c51ffa4f39ae7b681b930c868f` |
| `settings/slotConfiguration.json` | 759 | 4 | `2a9e27fe7efd397398da1ad35b639e4b79a290bbfff24e6518e6cfde83d4ede0` |

Fresh repeated USB pulls matched byte-for-byte; both files parse as JSON. The final-part flags were
verified, including a fresh read of both documents after 50 unserved-path requests in one session.
`usb-pull-latest.log` contains that batch, including successful end-of-session controls.

## Already obtained elsewhere

`te-assets/`: 49 files / 13,775,000 B: 21 official engines, 4 redmount AIFFs and 24 hero images.
The pre-brick content backup also holds configs and ten genuine projects.
The catalogue and file ledger are in [te-assets/MANIFEST.json](te-assets/MANIFEST.json).

## Outstanding

Original factory audio is still required; redmount is not a substitute. On request, 19 recorded
sample substitutes were generated under
`~/projects/customs/opz-firmware-notes/fabricated-sample-substitutes/` from public-domain/free
TR-707/TR-808 source recordings, processed with MIT `teoperator` (commit ddc6ef3) into mono
44.1-kHz/16-bit AIFFs with 24-slice metadata. Source audio and provenance notes are included;
outputs are hash-listed and passed format/non-silence checks. These are not OP-Z factory recordings
and have not been device-tested.
Renewed research found a
2019 first-hand report that an older iOS app contained the AIFFs, but that package has not been obtained.
An actual public iOS IPA was downloaded to `ios-apps/OP-Z-archived.ipa`, but its Info.plist says
1.3.1/build 194 and its resource audit yielded no factory audio. Archived official Apple history
identifies 1.0.5 (2018-11-13) as the best early-version target. ipatool 2.6.0 is installed;
listing historical versions is blocked on local `ipatool auth login` (no account in its keyring).
Historical download availability is not yet verified. The user need not have an old backup.
Apple authentication was declined; it is not the selected route. An additional no-login pass
checked 46 valid archive manifests / 6,575 entries, a nested ZIP index, and the 2019 author's
public repository/forks/issues/gist listing, without recovering an early IPA or original audio.
No contact with people is authorized or planned. Further no-contact checks scanned all 274 OP1.fun
OPZ-tagged pack pages, 491 Internet Archive IPA records from 2018–2020, and public Hugging Face,
GitLab, DataCite/Zenodo indices. No original audio or early IPA found; one 21.6-GB Hugging Face
`OPZO.zip` false lead was identified from its ranged ZIP directory as CIFAR/DVS ML data, without
downloading it. Continue only with public mirrors, individual public audio files, or device/firmware
recovery routes; archive/search gaps do not prove global absence. A fresh live USB read-only sweep (85 factory-audio path variants plus preset bank) received a valid
$34 but no file part for any target; the two known-readable settings files were freshly retrieved
immediately afterward with their established hashes. This confirms the paths are unserved by the file
transfer view, not that their files are absent. Log: `/tmp/opz-factory-research/usb-factory-probe.log`.
Internet Archive exact-name searches and Sourcegraph global code search also produced no candidates;
ordinary web search attempts were blocked or irrelevant. A full filename sweep of the local home directory
found no additional local IPA or factory audio. Details in FACTORY_SAMPLES_RESEARCH.md.
The user-installed Mac app 1.3.1/build 494 yielded metadata only in the inspected paths: no audio files,
AIFF bodies or Unity AudioClip/TextAsset objects. Its managed download code uses the existing DLC file
`api_path`; no additional factory route was found in those methods. Details and preserved evidence:
[factory-sample research](../projects/customs/opz-firmware-notes/FACTORY_SAMPLES_RESEARCH.md).

- `settings/plugPresets.dat`: no part 0 in the working USB session.
- `system/content/samplepacks/sfx.aif`, redmount and the 19 unpublished factory-pack names tested under
  `samplepacks/` and `system/content/samplepacks/`: no part 0. This does not prove the audio is absent;
  the reference documents a whitelist/virtual-table service, not arbitrary filesystem export.
- Tested config and engine paths also returned no part 0; copies already exist elsewhere.

The whole-data objective is not complete. Do not repeat BLE scans or interpret unserved paths as deleted files.
No automatic watcher or probe is running.

## Tooling

[Runbook](PULL_RUNBOOK.md): `toolkit/opzpull.py` performs the verified USB handshake, refreshes both
sessions, checks sender/file IDs and final flags, retries incomplete cursors, saves atomically and prints SHA-256.
Exit 3 means at least one requested path was unserved/incomplete; successful files remain saved.
`test_pull_paths.py` passes startup, keepalive, assembly, truncated-transfer and foreign-sender checks.
BLE tools and the old `opzfetch.py`/`opzadv.py` are not the verified current USB procedure.
