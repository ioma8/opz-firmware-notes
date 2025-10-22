# Firmware Analysis Notes

## File Overview
- Sample analyzed: `z_firmware_1_2_45(1).zfw` (size 1,491,600 bytes).
- `file` reports generic data; high entropy throughout payload confirms encryption.
- First non-zero byte at offset `0x04` equals `0xFF` – documented as "key index".

## Header Layout (based on observations & community wiki)
| Offset | Length | Description | Observations |
| ------ | ------ | ----------- | ------------ |
| `0x00` | 4 bytes | Flags / header marker | Mostly zeros; byte 4 = key index (`0xFF`). |
| `0x10` | 0x60 | Reserved | All zeros in this sample. |
| `0x70` | 16 bytes | AES IV | Value: `32 93 C5 8E E8 43 EF 3A 7B 0B 5E C8 5D E8 30 ED`. |
| `0x80` | 4 bytes (LE) | Encrypted payload length | `0x0016BE8F` (=1,490,575); matches total payload size beginning at `0x400`. |
| `0x300` | 0x100 | Encrypted filename blob | Decrypts (with correct key) to `firmware_bin_only_with_bootloader.zip` per wiki / Reddit thread.
| `0x400` | `length` bytes | AES-encrypted firmware archive | All attempts to decode reveal uniformly high entropy.

## Encryption Characteristics
- Wiki confirms AES (CBC) with 256-bit key; IV stored at `0x70`.
- Actual AES key is *not* present in the file; only a key index is stored. All published firmware reportedly use the same secret key held inside the device.
- Attempted techniques:
  - Recovered repeating XOR masks from ciphertext assuming known plaintext headers (7z, gzip, MZ). Produced plausible-looking fragments but failed structural checks (invalid PE headers, corrupt archives) → confirms ciphertext remains encrypted.
  - AES-CTR/CBC/CFB/OFB trials with IV and ciphertext using the 16-byte value as key or IV → output still random; no valid signatures.
  - Header-derived AES ECB decryptions fail to reveal meaningful plaintext.
- Entropy measurements (`ent`) show 7.9998 bits/byte across payload → consistent with strong encryption.

## Known Plaintext / Metadata Clues
- Offsets flagged by signature scans for `7z`, `gzip`, `MZ`, `FAT` align with boundaries of encrypted sections but do not correspond to useful plaintext without key.
- Decrypted filename (from community references) indicates final payload is a zip archive containing sub-firmwares (`firmware_bin_only_with_bootloader.zip`).

## External Research (GitHub wiki & Reddit)
- GitHub `rez` wiki (`rez.wiki/Firmware.md`) documents same offsets and encryption scheme.
- Reddit thread `/r/OPZuser/comments/be1nl6/opz_firmware_analysis/` confirms:
  - OP-Z bootloader uses padding-oracle-resistant AES-CBC.
  - Device can output decrypted filename via serial console but does not expose the key.
  - All consumer firmware zfw files share the same AES key.

## Current Blockers
- Without the 256-bit AES key there is no feasible software-only path to decrypt the archive.
- Brute force or generic cryptanalysis is infeasible.

## Recommended Next Steps
1. Obtain AES key from hardware (e.g., instrument OP-Z secure boot, glitching, or leveraging `.engine` modules to dump keys) or from existing community dumps.
2. Once key is available:
   - Use IV at `0x70` and decrypt payload starting at `0x400` using AES-256-CBC.
   - Extract resulting `firmware_bin_only_with_bootloader.zip`, then expand contained binaries for further reverse engineering.

## Miscellaneous Artifacts
- `rez.wiki/` cloned locally for reference (`Firmware.md`, `Hardware.md`).
- Numerous “decoded” MZ/7z/gzip fragments stored under `extracted/`; these are artifacts from xor experiments and not valid binaries.

