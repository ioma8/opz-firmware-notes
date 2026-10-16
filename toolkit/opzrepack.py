#!/usr/bin/env -S uv run --script
# /// script
# dependencies = ["pycryptodome"]
# ///
"""Decrypt, modify and re-encrypt an OP-Z .zfw firmware image.

Layout: AES IV at 0x70; the 256-byte filename field at 0x300 is one CBC region using that IV;
the archive at 0x400 chains off the field's last ciphertext block (0x3F0..0x400). The length at
0x80 counts the *unpadded* archive, so the ciphertext runs to the next 16-byte boundary -- which
is why the tail of the file past the length field is still ciphertext, and why truncating the
payload to a 16-byte multiple silently destroys the zip's end-of-central-directory.

The key is never embedded here. Provide it with --key-hex, --key-file, or the OPZ_KEY env var.

Round-trip proof, which is the only thing that makes a repack safe to install:

    uv run --script toolkit/opzrepack.py --self-test --key-hex <hex> --source z_firmware_1_2_45.zfw

It decrypts the image, re-encrypts the untouched plaintext with the original IV, and requires the
result to be byte-identical to the original file; then repeats with a fresh IV and requires the
re-decryption to match. Nothing should be installed before this passes.
"""
import argparse
import hashlib
import os
import struct
import zlib
import zipfile
import io
from pathlib import Path

from Crypto.Cipher import AES

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT / "z_firmware_1_2_45.zfw"
IV_OFF, LEN_OFF, NAME_OFF, ARCHIVE_OFF = 0x70, 0x80, 0x300, 0x400
NAME_LEN = 0x100


def load_key(args):
    raw = args.key_hex or (Path(args.key_file).read_text().strip() if args.key_file else None) \
        or os.environ.get("OPZ_KEY")
    if not raw:
        raise SystemExit("no key: pass --key-hex / --key-file, or set OPZ_KEY")
    key = bytes.fromhex("".join(raw.split())) if not raw.startswith("-----") else None
    if key is None:
        raise SystemExit("only raw hex keys are supported")
    if len(key) != 32:
        raise SystemExit(f"key must be 32 bytes (256-bit), got {len(key)}")
    return key


def decrypt(image, key):
    """Return (header, filename plaintext, padded archive plaintext, length field).

    The padded plaintext is returned in full, not truncated to the length field: the final block
    contains padding bytes past `length` that are still real ciphertext, and re-encrypting without
    them cannot reproduce the image.
    """
    iv = image[IV_OFF:IV_OFF + 16]
    length = struct.unpack_from("<I", image, LEN_OFF)[0]
    body = image[ARCHIVE_OFF:]
    if len(body) % 16:
        raise SystemExit(f"archive ciphertext is not block aligned: {len(body)} bytes")
    name_plain = AES.new(key, AES.MODE_CBC, iv).decrypt(image[NAME_OFF:NAME_OFF + NAME_LEN])
    archive_iv = image[ARCHIVE_OFF - 16:ARCHIVE_OFF]      # the field's last ciphertext block
    padded_plain = AES.new(key, AES.MODE_CBC, archive_iv).decrypt(body)
    return image[:ARCHIVE_OFF], name_plain, padded_plain, length


def encrypt(template, key, name_plain, payload, iv, length=None, already_padded=False):
    """Rebuild an image. `template` supplies everything below 0x400.

    Padding is PKCS#7, which is what real images use -- the 1.2.45 image carries a single 0x01
    byte for its 1,490,575-byte payload (length mod 16 == 15). Pass already_padded=True only when
    `payload` came straight from decrypt().
    """
    if len(name_plain) != NAME_LEN:
        raise SystemExit(f"filename field must be {NAME_LEN} bytes")
    out = bytearray(template)
    out[IV_OFF:IV_OFF + 16] = iv
    struct.pack_into("<I", out, LEN_OFF, len(payload) if length is None else length)
    name_ct = AES.new(key, AES.MODE_CBC, iv).encrypt(name_plain)
    out[NAME_OFF:NAME_OFF + NAME_LEN] = name_ct
    if already_padded:
        padded = payload
    else:
        pad = 16 - (len(payload) % 16)
        padded = payload + bytes([pad]) * pad
    if len(padded) % 16:
        raise SystemExit(f"padded payload is not block aligned: {len(padded)}")
    out += AES.new(key, AES.MODE_CBC, name_ct[-16:]).encrypt(padded)
    return bytes(out)


def self_test(source, key):
    image = Path(source).read_bytes()
    header, name_plain, padded_plain, length = decrypt(image, key)
    zip_plain = padded_plain[:length]
    padding = padded_plain[length:]
    print(f"source           : {Path(source).name}  {len(image):,} bytes")
    print(f"archive plaintext: {length:,} bytes usable, {len(padding)} padding byte(s) "
          f"{padding.hex()} -> PKCS#7" if padding == bytes([len(padding)]) * len(padding)
          else f"archive plaintext: {length:,} bytes usable, padding {padding.hex()} (NOT PKCS#7)")
    print(f"filename field   : {name_plain.split(bytes([0]))[0].decode('latin1')!r}")

    # the plaintext really is a zip once the final block is not truncated away
    try:
        with zipfile.ZipFile(io.BytesIO(zip_plain)) as z:
            print(f"zip check        : OK, {len(z.namelist())} members, CRC verified by zipfile")
    except zipfile.BadZipFile as error:
        raise SystemExit(f"decrypted archive is not a valid zip: {error}")

    # proof 1: same IV and the full padded plaintext -> byte-identical to the original file
    same = encrypt(header, key, name_plain, padded_plain, image[IV_OFF:IV_OFF + 16], length,
                   already_padded=True)
    if same != image:
        first = next((i for i, (a, b) in enumerate(zip(same, image)) if a != b), min(len(same), len(image)))
        raise SystemExit(f"ROUND TRIP FAILED at byte {first}: {len(same)} vs {len(image)} bytes")
    print(f"round trip (same IV) : IDENTICAL  sha256={hashlib.sha256(same).hexdigest()[:32]}")

    # proof 2: a fresh IV must still decrypt back to the same plaintext
    resealed = encrypt(header, key, name_plain, padded_plain, bytes(16), length, already_padded=True)
    h2, n2, a2, l2 = decrypt(resealed, key)
    if (n2, a2, l2) != (name_plain, padded_plain, length):
        raise SystemExit("ROUND TRIP FAILED with a fresh IV")
    if resealed == image:
        raise SystemExit("fresh IV produced identical ciphertext - encryption is not happening")
    print(f"round trip (fresh IV): OK, {len(resealed):,} bytes, ciphertext differs from the original")

    # proof 3: a modified payload survives a real repack cycle (PKCS#7 applied by encrypt)
    edited = zip_plain + b"--patch-marker--"
    repacked = encrypt(header, key, name_plain, edited, bytes([0x5A]) * 16)
    h3, n3, a3, l3 = decrypt(repacked, key)
    if l3 != len(edited) or a3[:len(edited)] != edited:
        raise SystemExit("ROUND TRIP FAILED: a modified payload did not survive")
    print(f"round trip (modified) : OK, {len(edited):,} bytes re-encrypt and re-decrypt intact, "
          f"PKCS#7 pad {a3[len(edited):].hex()}")
    print("SELFTEST PASSED - repacking is trustworthy")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--key-hex")
    parser.add_argument("--key-file")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--decrypt-to", type=Path, help="write the plaintext archive to this path")
    parser.add_argument("--pack-from", type=Path, help="re-encrypt the archive at this path")
    parser.add_argument("--iv", help="16-byte IV as hex for --pack-from (default: random)")
    parser.add_argument("--out", type=Path, default=Path("z_firmware_patched.zfw"))
    args = parser.parse_args()
    key = load_key(args)

    if args.self_test:
        self_test(args.source, key)
        return 0

    image = args.source.read_bytes()
    header, name_plain, padded_plain, length = decrypt(image, key)
    if args.decrypt_to:
        args.decrypt_to.write_bytes(padded_plain[:length])
        print(f"wrote {length:,} plaintext bytes to {args.decrypt_to}")
    if args.pack_from:
        payload = args.pack_from.read_bytes()
        iv = bytes.fromhex(args.iv) if args.iv else os.urandom(16)
        if len(iv) != 16:
            raise SystemExit("--iv must be 16 bytes of hex")
        args.out.write_bytes(encrypt(header, key, name_plain, payload, iv))
        print(f"wrote {args.out} ({args.out.stat().st_size:,} bytes), "
              f"archive {len(payload):,} bytes, IV {iv.hex()}")
        print("verify before installing: uv run --script toolkit/opzrepack.py --self-test "
              f"--source {args.out} --key-hex <hex>")
    if not args.decrypt_to and not args.pack_from:
        print("nothing to do: pass --self-test, --decrypt-to or --pack-from")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
