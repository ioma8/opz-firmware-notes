#!/usr/bin/env python3
"""
Software-only decryption of a Teenage Engineering OP-Z `.zfw` firmware file,
using the upgrade-mode USB serial console as an AES-CBC decryption oracle.

How it works
------------
In upgrade mode the OP-Z decrypts the 256-byte blob at file offset 0x300 (the
archive filename) with the secret AES key and the IV stored at 0x70, and prints
the result to the USB serial console.  That print is a readout of

    AES_dec(blob[i]) XOR blob[i-1]      (CBC, blob[-1] = IV@0x70)

CBC within the 0x300 region means we can feed *payload* ciphertext there and
read back payload plaintext.  For payload blocks Y_0..Y_n:

    place  blob = Y_j || Y_{j+1} || ... || Y_{j+15}   (256 bytes)
    set    IV@0x70 = Y_{j-1}                           (Y_-1 = original IV)
    read   back = X_j || X_{j+1} || ... || X_{j+15}    (payload plaintext)

because X_i = AES_dec(Y_i) XOR Y_{i-1}.  One device query yields 256 bytes, so a
~1.5 MB firmware needs ~5800 queries.  No key is recovered or required.

Usage
-----
    ./oracle_decrypt.py <firmware.zfw> <out.zip> [--serial PORT] [--baud N]
    ./oracle_decrypt.py --selftest

The `--serial` path needs `pyserial` and the OP-Z; the `--selftest` path proves
the crypto/logic against a simulated oracle and needs `pycryptodome`.
"""

import argparse
import sys
import time

BLOCK = 16
BLOB_OFF, BLOB_LEN = 0x300, 0x100
IV_OFF = 0x70
LEN_OFF = 0x80
PAYLOAD_OFF = 0x400


def parse(data):
    iv = data[IV_OFF:IV_OFF + BLOCK]
    length = int.from_bytes(data[LEN_OFF:LEN_OFF + 4], "little")
    ct_len = ((length + BLOCK - 1) // BLOCK) * BLOCK
    ct = data[PAYLOAD_OFF:PAYLOAD_OFF + ct_len]
    return iv, length, ct


def ciphertext_blocks(ct):
    return [ct[i:i + BLOCK] for i in range(0, len(ct), BLOCK)]


def decrypt_with_oracle(data, oracle, progress=False):
    """Return the decrypted payload given oracle(crafted_zfw) -> 256 bytes."""
    iv, length, ct = parse(data)
    blocks = ciphertext_blocks(ct)
    out = bytearray()
    total = len(blocks)
    for start in range(0, total, BLOB_LEN // BLOCK):
        chunk = blocks[start:start + BLOB_LEN // BLOCK]
        prev = blocks[start - 1] if start > 0 else iv
        blob = b"".join(chunk).ljust(BLOB_LEN, b"\x00")
        crafted = bytearray(data)
        crafted[IV_OFF:IV_OFF + BLOCK] = prev
        crafted[BLOB_OFF:BLOB_OFF + BLOB_LEN] = blob
        readback = oracle(bytes(crafted))
        if len(readback) < BLOB_LEN:
            raise RuntimeError(f"oracle returned {len(readback)} bytes, expected {BLOB_LEN}")
        out += readback[:len(b"".join(chunk))]
        if progress:
            print(f"\r  block {start + len(chunk)}/{total}", end="", file=sys.stderr)
    if progress:
        print("", file=sys.stderr)
    return bytes(out[:length])


# --------------------------------------------------------------------------
# device oracle (needs the OP-Z + pyserial) -- adapt the trigger to your unit
# --------------------------------------------------------------------------

def make_device_oracle(port, baud=115200, mount=None, timeout=5.0):
    """
    Copy the crafted .zfw onto the OP-Z upgrade drive, capture the 256 bytes the
    console prints for the filename blob, return them.

    NOTE: the trigger differs by firmware/host. Common triggers observed in the
    community: the console prints as soon as the file lands; or it prints after
    the drive is ejected / the Play key is pressed. Adjust `_trigger` below.
    """
    import serial  # pyserial

    def _trigger(crafted_path, dev):
        # Replace with however your unit starts an upgrade, e.g.:
        #   - copy crafted_path to <mount>/z_firmware_oracle.zfw
        #   - os.sync(); wait for the drive to be ejected; press Play
        # Here we assume the console prints on file copy.
        return

    def oracle(crafted):
        tmp = "/tmp/_oracle.zfw"
        with open(tmp, "wb") as fh:
            fh.write(crafted)
        with serial.Serial(port, baud, timeout=timeout) as ser:
            ser.reset_input_buffer()
            if mount:
                import shutil, os
                shutil.copy(tmp, os.path.join(mount, "z_firmware_oracle.zfw"))
            _trigger(tmp, serial)
            buf = bytearray()
            deadline = time.time() + timeout
            while len(buf) < BLOB_LEN and time.time() < deadline:
                buf += ser.read(BLOB_LEN - len(buf))
        return bytes(buf[:BLOB_LEN])

    return oracle


# --------------------------------------------------------------------------
# self-test: prove the crypto/logic against a simulated oracle
# --------------------------------------------------------------------------

def _selftest():
    import os
    from Crypto.Cipher import AES  # pycryptodome, test-only

    rng = os.urandom
    key = rng(32)                       # AES-256
    iv = rng(16)
    plaintext = rng(4096 + 37)          # stand-in for the zip payload
    pad = BLOCK - (len(plaintext) % BLOCK) or BLOCK
    padded = plaintext + bytes([pad]) * pad
    ct = AES.new(key, AES.MODE_CBC, iv).encrypt(padded)

    # build a fake .zfw exactly like the real layout
    data = bytearray(PAYLOAD_OFF + len(ct))
    data[4] = 0xFF
    data[IV_OFF:IV_OFF + 16] = iv
    data[LEN_OFF:LEN_OFF + 4] = len(plaintext).to_bytes(4, "little")
    data[PAYLOAD_OFF:] = ct

    def sim_oracle(crafted):
        civ = crafted[IV_OFF:IV_OFF + 16]
        cblob = crafted[BLOB_OFF:BLOB_OFF + BLOB_LEN]
        return AES.new(key, AES.MODE_CBC, civ).decrypt(cblob)

    got = decrypt_with_oracle(bytes(data), sim_oracle)
    assert got == plaintext, "FAIL: decrypted payload != original"
    print(f"selftest OK: recovered {len(got)} bytes of {len(plaintext)} with no key")


def main():
    ap = argparse.ArgumentParser(description="OP-Z .zfw oracle decryption")
    ap.add_argument("zfw", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--serial")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--mount")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return
    if not (args.zfw and args.out and args.serial):
        ap.error("need <firmware.zfw> <out.zip> --serial PORT (or --selftest)")

    data = open(args.zfw, "rb").read()
    oracle = make_device_oracle(args.serial, args.baud, args.mount)
    pt = decrypt_with_oracle(data, oracle, progress=True)
    with open(args.out, "wb") as fh:
        fh.write(pt)
    print(f"wrote {args.out} ({len(pt)} bytes)")
    if pt[:2] == b"PK":
        print("payload starts with PK -> valid zip")
    else:
        print("WARNING: no PK header; oracle framing/trigger likely needs tuning")


if __name__ == "__main__":
    main()
