#!/usr/bin/env bash
# Decrypt a Teenage Engineering OP-Z .zfw firmware file.
#
# Layout (verified across 7 firmware files):
#   0x04      1 byte   key index (0xFF = on-device key store)
#   0x70     16 bytes  AES IV (per file, random)
#   0x80      4 bytes  plaintext length, little-endian
#   0x300   256 bytes  encrypted archive filename (same key+IV)
#   0x400      rest    AES-CBC ciphertext, PKCS#7 padded
#
# Usage: ./decrypt_zfw.sh <firmware.zfw> <hexkey> [out.zip]
#   <hexkey> = 32/48/64 hex chars -> AES-128/192/256-CBC.
#
# This tool is useful the moment a key is obtained (e.g. via the BF703 debug
# port / on-chip AES engine). It also serves as a fast key tester.
set -euo pipefail

zfw=${1:?usage: decrypt_zfw.sh <firmware.zfw> <hexkey> [out.zip]}
key=${2:?need hex key}
out=${3:-${zfw%.zfw}.zip}

case ${#key} in
  32) alg=aes-128-cbc ;;
  48) alg=aes-192-cbc ;;
  64) alg=aes-256-cbc ;;
  *)  echo "key must be 32/48/64 hex chars" >&2; exit 1 ;;
esac

iv=$(xxd -p -s 0x70 -l 16 "$zfw")
len=$(od -An -tu4 -j 0x80 -N4 "$zfw" | tr -d ' ')

# payload: decrypt then drop PKCS#7 padding by truncating to the stated length
dd if="$zfw" bs=1 skip=$((0x400)) 2>/dev/null \
  | openssl enc -d -"$alg" -K "$key" -iv "$iv" -nopad \
  | head -c "$len" > "$out"

# sanity check: decrypt the filename blob and show it
name=$(dd if="$zfw" bs=1 skip=$((0x300)) count=256 2>/dev/null \
  | openssl enc -d -"$alg" -K "$key" -iv "$iv" -nopad \
  | LC_ALL=C tr -d '\0' || true)

echo "wrote $out ($len bytes)"
echo "embedded filename: ${name:-(key wrong / not printable)}"
case "$name" in
  firmware_bin_only_with_bootloader.zip*) echo "KEY OK"; command -v unzip >/dev/null && unzip -l "$out" | head ;;
  *) echo "filename mismatch -> key likely wrong (or use -nopad-aware extractor)" >&2 ;;
esac
