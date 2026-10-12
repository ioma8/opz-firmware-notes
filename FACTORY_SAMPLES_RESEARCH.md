# Original OP-Z factory samples — renewed research (2026-10-11)

## Result

**No additional original factory audio was recovered in this research pass.** The four previously
saved redmount packs are real audio, but do not satisfy the request for the missing factory packs.
No device files were changed, and the newly installed Mac app was not launched by the agent.

The strongest new lead is an **older iOS app**, not the current Mac/Android app. Do not repeat the
older blanket claim that the samples cannot exist on the internet or in any companion app.

## Older iOS app: promising, not yet obtained

[Lrk's first-hand reverse-engineering report, 2019-01-03](https://lrk.github.io/z-po-project/default_sample_packs/)
says the iPhone app's files contained actual samples, and lists:

- `AlainFX/Kicks/Perc/Snares.aif`
- `CuckooFX/Kicks/Perc/Snares.aif`, `CuckooC_keypawn.aif`, `CuckooC_open.aif`
- `SebaFX/Kicks/Perc/Snares.aif`
- `TeFX/Kicks/Percs/Snares.aif`
- `GrantFX.aif`, `zVinyl.aif`, `UserSampler.aif`, `sfx.aif`
- `redFX/Kicks/Perc/Snares.aif`

The author describes listening to `UserSampler.aif` ("Hello, this is OP-ZED") and `sfx.aif`
(metronome sounds). This is a substantially stronger lead than a directory listing of filenames.
However, the report does **not** supply an IPA, AIFF download, app version, hashes, or an extraction
procedure. Its public `gh-pages` repository tree contains the article, not these audio files.
An early iOS application package or application-container backup is still needed to verify it.

### Exact early-release target established

The [official Apple page captured on 2019-07-18](https://web.archive.org/web/20190718041017id_/https://apps.apple.com/us/app/op-z/id1088232296)
contains this release history in its embedded JSON:

| Version | Released |
|---|---|
| `1.0` | 2018-10-17 |
| `1.0.4` | 2018-10-24 |
| **`1.0.5`** | **2018-11-13** |
| `1.1` | 2019-02-22 |
| `1.1.1` | 2019-05-03 |
| `1.2` | 2019-07-01 |

Thus **1.0.5** is the latest published version preceding the 2019-01-03 article. Prefer that
package, then `1.0.4`/`1.0`; not an arbitrary 2019 release. This dates the target, but does not
prove which version the author inspected or that Apple still serves its binary.

## Actual iOS IPA obtained online — wrong release

A bounded filename search of **200 Internet Archive collection manifests / 76,023 file entries**
found a real [OP-Z.rar download](https://archive.org/download/Dark_IOS_Archive_A3_3/OP-Z.rar)
in [Dark IOS Archive 3](https://archive.org/details/Dark_IOS_Archive_A3_3).

Downloaded and saved under `~/.opz-decode/ios-apps/`:

| File | Bytes | SHA-256 |
|---|---:|---|
| `OP-Z-Dark_IOS_Archive_A3_3.rar` | 95,505,606 | `65cf37ee11d1b329a17ab6e4c91ba62c49abdb15ce413bdd5e0ff9d0bcb3d6af` |
| `OP-Z-archived.ipa` | 63,112,490 | `8be1231ada716389cdfd885d64dd411680adfe8ffffacffa8f23d9ffc2ef9103` |

RAR size and MD5 match the archive's published file metadata. 7-Zip reported a RAR header error;
`bsdtar -xOf` nevertheless extracted the contained IPA, and **all IPA ZIP member CRCs passed**.
Do not confuse successful IPA validation with validation of every RAR recovery/header structure.

The actual `Payload/OP-Z.app/Info.plist` identifies **iOS 1.3.1, build 194**, bundle
`com.teenageengineering.te012`, minimum iOS `12.0`. This is a third-party package, not an
Apple-authenticated download; it was **not installed or executed**.

- No `.aif`, `.aiff`, `.wav`, or `.mp3` entries.
- Scanning ZIP-member bytes found no complete `FORM`/`AIFF` or `AIFC` candidates.
- All four top-level Unity `.assets` inventories contain zero `AudioClip` and `TextAsset` objects.
- Sample names occurred in factory metadata, not demonstrated audio bodies.

`OP-Z-archived.audit.json`, `OP-Z-archived.inventory.json`, and `archive-search-summary.json`
record the checks and bounded search scope. Nested archives with unrelated names, excluded
collections, unqueried items, and other sites remain outside that scope. **This download is not
completion of the early-IPA or factory-audio request.**

### Authenticated Apple historical-download route prepared

Installed [ipatool](https://github.com/majd/ipatool) **2.6.0** using Homebrew. Its available commands
include `list-versions`, `get-version-metadata`, and `download --external-version-id`.
The implementation obtains Apple's `softwareVersionExternalIdentifiers` through an authenticated
App Store download-product response; no raw App Store password is required in chat.

The read-only attempt:

```sh
ipatool --non-interactive --format json list-versions --app-id 1088232296 --platform iphone
```

stopped with `failed to get account ... item could not be found in the keyring`.
An existing macOS App Store login is **not** automatically an ipatool session.
The one human-only step is local interactive authentication:

```sh
ipatool auth login
```

Source inspection of `cmd/auth.go` confirms this prompts for email, hides password input,
and prompts for 2FA if required. Do not put passwords in shell flags or chat. After authentication,
list Apple's version IDs, resolve them to version metadata, and request a verified `1.0.5` ID.
A free app license may also be required. **Historical binary availability remains unverified**;
a successful login alone is not a promise of recovery.

## Installed Mac app: no factory audio found

User installed the official [Mac App Store OP-Z app](https://apps.apple.com/app/op-z/id1098190457).
Inspected `/Applications/OP-Z.app`, version **1.3.1**, build **494**,
bundle ID `com.teenageengineering.te012.osx`.

Checks performed without running the app:

1. Recursively enumerated package files: no `.aif`, `.aiff`, or `.wav` files.
2. Scanned package-file bytes (100 B–180 MB) for complete `FORM`/`AIFF` or `AIFC` headers:
   none found. Factory pack names occurred in `StreamingAssets/factory-plug-cache/*/metadata.json`.
3. Parsed all four top-level Unity `.assets` files with UnityPy, including their external `.resS`
   resources. Object inventories contained **zero `AudioClip` and zero `TextAsset` objects**.
   The large resources hold textures and other UI/visual assets; their size alone is not audio evidence.
4. Decompiled the relevant managed classes to examine the actual download path, rather than
   assuming another endpoint exists.

These are bounded checks of **Mac 1.3.1**, not proof about early iOS releases, encrypted payloads,
all Unity object fields, or every possible custom encoding.

### Current app's sample download path

Primary source: `Contents/Resources/Data/Managed/Assembly-CSharp.dll`, SHA-256
`3310b22baea472da96580d5ae6392467c6c7f13a732bc1c8c5ee2da6a890598b`.

- `TE.PlugManager.sendSlotConfigurationToSynth`: uses the DLC item's `files` collection to find
  a pack matching `plug.samples`, then passes that file's `api_path` to `downloadContentFile`.
- `TE.DLCItem.GetTEIDFileByName`: searches only that item's `files` array and returns `default`
  if no entry matches. It does not discover a factory-audio URL from a pack name.
- `TE.PlugManager.downloadContentFile`: GETs `https://teenage.engineering` plus the supplied
  nonempty `api_path`; successful bodies are placed in the host outbox for subsequent sync.
- `TE.TEIDFileHelper._downloadBlob`: appends `?serial=<client serial>&device=<host identifier>`.
  The request helper may attach the account access token. No separate factory-audio download
  endpoint appeared in these inspected methods.

Kuna 1.130 enumerated only two `_CorDllMain` native stubs in this managed DLL; ILSpy 11.1 was
used for C# IL instead. Decompiled output is evidence for the relevant methods, not original source.

## TE public API and archive checks

The [live DLC catalogue](https://teenage.engineering/_api/id/products/597caf1a-f7e1-4d86-8881-7b17a79adfb1/dlcs)
continues to advertise just four downloadable `opz-sample` entries: the redmount packs.
Factory `samples` names are metadata, not additional downloadable `files` entries.

- GETs of the seven sampler DLC detail paths and their `/files` collection paths returned 404.
  These guessed collection routes are not documented download URLs.
- Product `/assets?category=opz-sample` and `/assets?include_factory=true` still returned the
  same 21 engine assets. `/dlcs?factory=true` returned the existing catalogue, not extra sample files.
- A [Wayback CDX prefix query](https://web.archive.org/cdx/search/cdx?url=teenage.engineering%2F_software%2F%2A&output=json&collapse=urlkey&filter=statuscode%3A200)
  returned 103 archived successful URLs under `teenage.engineering/_software/`; the OP-Z entries
  were firmware archives, not a sample-content or app download. This is only that indexed prefix.

## Public community sources

- [OP Forums: native sample export discussion](https://op-forums.com/t/live-beat-on-keyboard-with-op-z/13518/5):
  a user reports original `AlainKicks.aif` entries as zero-byte links, not exportable audio.
- [OP Forums: built-in sample packs for download](https://op-forums.com/t/op-z-built-in-sample-packs-for-download/20784):
  the only reply describes recording them over USB; no original AIFF download is linked.
- Public trees of [OP-1Z Sample Manager](https://github.com/romangarms/OP-1Z-Sample-Manager)
  and [m0nkmaster's sound-samples](https://github.com/m0nkmaster/sound-samples) contain factory
  `~<pack>.aif` markers of **0 bytes**. The latter also has real user samples, which are not factory packs.
- Authenticated GitHub exact-phrase searches for `TeKicks.aif`, `CuckooKicks.aif`, and
  `AlainKicks.aif` found the requester's own APK metadata, not a downloadable original sample.
  Code search coverage does not establish absence of binary files or unindexed repositories.
- OP1.fun's actual filters are `q[name_cont]` and `q[description_cont]`, not `search=`.
  Searches and relevant two-page patch results identified custom kits and recordings, not
  an authenticated original factory pack. Similarly named vinyl kits remain unverified.

Search engines were unreliable: several responses were CAPTCHA, JavaScript challenges, throttling,
or unrelated results. Those responses are **not negative evidence** about available mirrors.
Android build-55 download from the published APKPure file ID returned 403; no old APK was obtained.
The initial public iOS mirror/API attempts yielded no IPA; the later Internet Archive pass did
obtain iOS 1.3.1 as documented above. Current appdb OpenAPI uses POST `/search_index/`, not the
old query-string API: unauthenticated `OP-Z`, `OPZ`, and developer-name searches returned empty
results. Its v1.6 API explicitly reports `ERROR_MUST_UPGRADE`; legacy `/get_links/` is no longer
listed in the current specification. ARM Store's inspected frontend requires login and uses the
current iTunes lookup, not a demonstrated early-version picker. No authentication or challenge
was bypassed.

## No-login follow-up (Apple authentication declined)

The user declined the authenticated Apple route; do not keep requesting Apple login.
A further bounded pass checked **46 additional valid archive manifests / 6,575 file entries**
(one other requested item returned no valid manifest). No matching early OP-Z IPA filename was
found there. The nested `IPA Collection.zip` in `ipa-collection_small` was inspected through
Internet Archive's archive viewer rather than downloading 3 GB; its 34 members were unrelated games.

Also checked the original research project's public releases, all four issue/PR records, five
forks' default-branch trees, and the author's public gist listing. The forks include useful engine
and plug documentation, but the inspected trees expose no IPA/AIFF files or download links.
GitHub commit-message searches for `OP-Z.ipa` and `CuckooKicks` returned no matches; these are
not searches of all binary file contents.

[Issue 4](https://github.com/lrk/z-po-project/issues/4) led to
[Tolsi's physical flash-dump work](https://github.com/Tolsi/op1dumps), but its published dump is
explicitly **OP-1**, with empty/formatted firmware. It is not OP-Z factory content and was not
downloaded as a substitute. Uptodown's exposed OP-Z Android history starts with recent 1.3.x
versions; the checked early Android mirror routes still provided no usable old package.

A normal isolated Chrome search reached Google's CAPTCHA page. No CAPTCHA bypass, stealth
browser settings, proxy rotation, account extraction, app installation, or device probe was used.
Search-engine failures still do not prove the app is unavailable elsewhere.

**Result remains incomplete:** only the previously obtained iOS 1.3.1 IPA is on disk; no early
IPA or original factory pack has been recovered. Evidence for this pass is under
`~/.opz-decode/ios-apps/no-login-evidence/`.

The user explicitly requested no communication with people. No issue, email, forum post,
or other contact was made. Remaining no-contact routes are limited to finding a mirror not yet
indexed in the checked archives, locating public individual AIFF copies, or recovering the audio
from local OP-Z firmware/device data. Search failures are not proof that no such source exists.

## Further no-contact search (2026-10-11)

- Checked the full **274-result OPZ pack listing** on OP1.fun and fetched all 274 pack pages.
  No factory-pack basename or factory-audio claim appeared. The plausible `OPZ SAMPLE BANKS`
  result is a curated list of unrelated OP-1 user patches; its public page links to files such as
  `Perc_MV2.aif`, not OP-Z stock audio. This is a bounded check of that site and its OPZ-name filter.
- Searched Internet Archive's `ipaarchive` collection by sample names, bundle ID, and OP-Z terms;
  no matching records. Then enumerated and checked filenames in all **491** `ipaarchive` software
  records dated 2018–2020. None referenced OP-Z, `te012`, the stock pack names, or app ID
  `1088232296`. This does not cover every upload date or other Archive collections.
- Checked public Hugging Face dataset/model search, GitLab project search, and DataCite/Zenodo
  search for OP-Z and exact stock filenames; no candidate audio or early IPA resulted. The only
  superficially matching Hugging Face result, `Brian-Wang117/OPZOzip`, is an unrelated 21.6-GB
  machine-learning archive: an 8-MiB HTTP range read of its ZIP central directory shows paths for
  spiking neural-network code and CIFAR/CIFAR10-DVS data, not OP-Z assets. The large archive was
  not downloaded.
- Rechecked public app mirror URLs; decrypt.day returned 403, several other routes were missing
  or unavailable, and no access controls were bypassed. Ordinary Google requests returned an
  interstitial, not search results.

These checks yielded **no new audio and no historical iOS package**. The investigation remains
open; no person was contacted, no Apple login requested, and no device touched.

## Follow-up: live USB retrieval and additional indexes (2026-10-11)

The OP-Z USB MIDI port was present, so I made another **read-only** pull attempt with the verified
protocol (StateSync v6 hello, `$51`, `$34`, `$52(active=0)`, then `$35` file requests). The device
answered as client 26851. I requested 85 candidate paths covering the 19 unpublished drum-pack
names, their known content-disk slot locations, `samplepacks/`, `content/samplepacks/`,
`system/content/samplepacks/`, the 2019-listed `CuckooC_keypawn`, `CuckooC_open`, `UserSampler`,
`sfx`, and `settings/plugPresets.dat`. None returned part 0. Immediately afterward, both known
control files (`settings/plugs.json` and `settings/slotConfiguration.json`) were freshly retrieved
with verified final flags and their established SHA-256 hashes, confirming that the transport was
live; this shows only that these candidate paths are **not served by this file-transfer view**, not
that the audio is absent from the device. Raw output: `/tmp/opz-factory-research/usb-factory-probe.log`.

A full filename sweep across `/Users/jakubkolcar` found only the four already-held redmount AIFFs,
three user-created samples in the working backup, empty factory marker files, and unrelated audio
fixtures; there is no other local IPA or named factory sample. The inventory is
`/tmp/opz-factory-research/local-audio-ipa-inventory.txt`.

Additional ordinary public-index checks:

- Internet Archive advanced search returned no results for exact factory pack names or a factory
  sample/OP-Z query. The few broad OP-Z/OPZ audio results were unrelated (search token collisions).
- Sourcegraph global code search, including archived and forked repositories, returned no exact-name
  hits for the factory packs.
- Bing HTML search returned unrelated results for the exact filenames; Mojeek/Yahoo and several
  SearX instances returned 403/429 errors. These are failed searches, not negative evidence.

No original audio or early app package was obtained in this follow-up.

## Recorded sample substitutes created (2026-10-11)

Replaced the earlier synthetic tones with 19 packs built from **real TR-707/TR-808 recordings**
from [`fluid-music/open-drums`](https://github.com/fluid-music/open-drums), pinned at commit
`475cc3314fe06f6d1af02e9790ad9707c1f2b26b`. The repository's TR-707 README says its samples are
public domain; its TR-808 README says the source files have no licensing restrictions, and
`TR808.TXT` credits Michael Fischer/Technopolis and describes the set as free. Source WAVs and those
source notes are included in `fabricated-sample-substitutes/sources/`.

Each output uses 24 recorded hits, modest pitch/EQ/gain/limiter/fade processing, and MIT
[`schollz/teoperator`](https://github.com/schollz/teoperator) at commit `ddc6ef3` to write the
AIFF `APPL`/`op-1` slice metadata. `CuckooC_keypawn.aif` uses tuned conga/cowbell/tom recordings;
`zVinyl.aif` uses processed cymbal/percussion recordings. The deterministic `generate.py` validates
the AIFF chunks, slice metadata, and non-silent PCM; hashes and per-pack source filenames are in
`MANIFEST.json`. All 19 files passed macOS `afinfo` checks.

The names are only slot-matching labels: these are **not authentic OP-Z factory recordings**.
They have not been imported or playback-tested on the OP-Z. Nothing was written to the device.
See the directory README for sources and regeneration.

## Evidence and remaining blocker

Small primary-response captures and Mac audit/decompilation outputs are preserved at
`~/.opz-decode/te-assets/factory-research/`. Larger exploratory captures remain in
`/tmp/opz-factory-research/`; they are not durable downloads of the requested audio.

Concrete inputs that would unblock the original-audio recovery:

- an early OP-Z iOS IPA or app-container backup corresponding to the 2019 report;
- an actual original factory-content archive supplied by TE;
- a readable system-content dump from a healthy unit, **not** its content-mode marker backup.

The installed current Mac app does not supply the missing pack bodies through the inspected paths.
Success still requires real nonempty audio bodies, format validation, provenance, and saved hashes.
