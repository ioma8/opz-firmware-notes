#!/usr/bin/env python3
"""Mine local artifacts for the .zfw AES key.

The .zfw is one CBC stream: the 256-byte filename field at 0x300 decrypts (IV at
0x70) to the ASCII name the bootloader logs, "firmware_bin_only_with_bootloader.zip",
and the archive ciphertext at 0x400 chains straight off the field's last block.
So a candidate key can be checked with ONE AES block decrypt:

    P0 = D_k(C0) ^ IV   must equal  b"firmware_bin_onl..."

If the key is a literal sitting in the APK, its native libs, the metadata bundle or
the .engine blobs, the whole firmware decodes offline -- no device, no oracle.

Usage: opzkeymine.py [--sweep]   (--sweep also tries every 16-byte window of each
corpus file as a raw key, not just printable runs)
"""
import hashlib, re, sys, time
from pathlib import Path
from zipfile import ZipFile
from Crypto.Cipher import AES

REPO = Path(__file__).resolve().parent
APK = REPO / 'OP-Z_1.3.0_APKPure.apk'
ZWFS = sorted(REPO.glob('z_firmware_*.zfw'))

# ---- the oracle -------------------------------------------------------------
_z = (REPO / 'z_firmware_1_2_45.zfw').read_bytes()
IV, C0 = _z[0x70:0x80], _z[0x300:0x310]
WANT = b'firmware_bin_only_with_bootloader.zip'
# Hardware-verified pair: the leaked zip header chains off the filename field's
# last ciphertext block (this is what the bootloader oracle proved on the device).
IV2, C2 = _z[0x3F0:0x400], _z[0x400:0x410]
WANT2 = bytes([0x50, 0x4b, 0x03, 0x04, 0x14, 0x00, 0xc0, 0x1e, 0x04, 0x00,
               0x00, 0x00, 0x49, 0xfb, 0xbe, 0x94])


def check(key):
    """Return the decrypted filename prefix if `key` decrypts it, else None."""
    if len(key) not in (16, 24, 32):
        return None
    ecb = AES.new(key, AES.MODE_ECB)
    # (1) the hardware-verified zip header -- the strongest available check
    p2 = bytes(a ^ b for a, b in zip(ecb.decrypt(C2), IV2))
    if p2 == WANT2:
        return 'ZIPHEADER-VERIFIED'
    p0 = bytes(a ^ b for a, b in zip(ecb.decrypt(C0), IV))
    if p0[:16] == WANT[:16]:
        # confirm the rest of the known name too (only meaningful on the real file)
        rest = ecb.decrypt(_z[0x310:0x330])
        chain = bytes(a ^ b for a, b in zip(rest, _z[0x300:0x320]))
        full = (p0 + chain)[:len(WANT)]
        return full.decode('latin1') if full == WANT else 'PARTIAL:' + repr(p0)
    if p0.rstrip(b'\x00').endswith(b'.zip') and p0[:1].isalpha() and p0[:6].isalnum():
        return 'HEURISTIC:' + repr(p0)
    return None


def selftest():
    """The oracle must accept a key that really is the key, and reject others."""
    key = b'k' * 16
    global IV, C0, IV2, C2
    old = (IV, C0, IV2, C2)
    IV = bytes(16)
    C0 = AES.new(key, AES.MODE_ECB).encrypt(b'firmware_bin_onl')
    IV2 = bytes(16)
    C2 = AES.new(key, AES.MODE_ECB).encrypt(WANT2)
    r = check(key)
    assert r == 'ZIPHEADER-VERIFIED', r
    assert check(b'x' * 16) is None
    IV, C0, IV2, C2 = old
    print('  self-test: oracle accepts the true key and rejects a wrong one')


# ---- candidate sources ------------------------------------------------------
PRINT = re.compile(rb'[\x20-\x7e]{16,}')


def corpus():
    """Yield (label, bytes) for every local artifact worth mining."""
    names = ['lib/arm64-v8a/libSnakePlugin.so', 'lib/arm64-v8a/libil2cpp.so',
             'lib/armeabi-v7a/libSnakePlugin.so', 'classes.dex',
             'assets/bin/Data/Managed/Metadata/global-metadata.dat']
    with ZipFile(APK) as z:
        for n in names:
            yield n, z.read(n)
    for p in sorted((REPO / 'engines').glob('*.engine')):
        yield p.name, p.read_bytes()
    for p in ZWFS:
        yield p.name, p.read_bytes()[:0x400]
    for p in REPO.glob('*.json'):
        yield p.name, p.read_bytes()
    for extra in (Path('/tmp/opz-official-apk/lib/arm64-v8a/libSnakePlugin.so'),):
        if extra.is_file():
            yield str(extra), extra.read_bytes()


def candidates(data, sweep):
    """Raw keys from printable runs (and, with sweep, every byte window)."""
    if sweep:
        for ks in (16, 32):
            for i in range(len(data) - ks + 1):
                yield data[i:i + ks]
        return
    for m in PRINT.finditer(data):
        s = m.group(0)
        for ks in (16, 24, 32):
            for i in range(len(s) - ks + 1):
                yield s[i:i + ks]


def main():
    sweep = '--sweep' in sys.argv
    selftest()
    t0 = time.time()
    n = 0
    hits = []
    for label, data in corpus():
        # literal windows / strings
        for k in candidates(data, sweep):
            n += 1
            r = check(k)
            if r:
                hits.append((label, k.hex(), r))
                print(f'HIT {label} key={k!r} -> {r}')
        # derived keys: md5 / sha1 / sha256 of each printable run
        if not sweep:
            for m in PRINT.finditer(data):
                s = m.group(0)
                for h in (hashlib.md5(s).digest(), hashlib.sha1(s).digest()[:16],
                          hashlib.sha256(s).digest(), hashlib.sha256(s).digest()[:16],
                          hashlib.sha1(s).digest()[:32]):
                    n += 1
                    r = check(h)
                    if r:
                        hits.append((label, h.hex(), r))
                        print(f'HIT(derived) {label} from {s[:60]!r} -> {r}')
                if re.fullmatch(rb'[0-9a-fA-F]+', s) and len(s) in (32, 48, 64):
                    b = bytes.fromhex(s.decode())
                    n += 1
                    r = check(b)
                    if r:
                        hits.append((label, b.hex(), r))
                        print(f'HIT(hex) {label} from {s[:60]!r} -> {r}')
        print(f'  {label}: {n} keys tried, {len(hits)} hits, {time.time()-t0:.0f}s')
    print(f'RESULT: {"KEY FOUND" if hits else "no key in the local corpus"} '
          f'({n} candidates, {time.time()-t0:.0f}s)')
    return 0 if hits else 1


if __name__ == '__main__':
    sys.exit(main())
