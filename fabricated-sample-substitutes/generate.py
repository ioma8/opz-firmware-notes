#!/usr/bin/env python3
"""Build OP-Z-format packs from public-domain/free TR-707/TR-808 recordings.

Requires Python 3, ffmpeg, and MIT-licensed github.com/schollz/teoperator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import subprocess
import tempfile
from pathlib import Path

RATE = 44_100
SLICES = 24
DURATION = 0.42
SOURCES = Path(__file__).parent / "sources"


def paths(folder: str, pattern: str = "*.WAV") -> list[Path]:
    return sorted((SOURCES / "TR808" / folder).glob(pattern))


def source_pools() -> dict[str, list[Path]]:
    t707 = SOURCES / "TR707"
    kicks = paths("BD") + [t707 / "BassDrum1.wav", t707 / "BassDrum2.wav"]
    snares = paths("SD") + [t707 / "Snare1.wav", t707 / "Snare2.wav", t707 / "HandClap.wav"]
    percussion = sum((paths(d) for d in ("LT", "MT", "HT", "LC", "MC", "HC")), [])
    percussion += paths("CB") + paths("CL") + paths("MA") + paths("RS")
    percussion += [t707 / n for n in ("CowBell.wav", "HiTom.wav", "MedTom.wav", "LowTom.wav", "RimShot.wav", "Tamb.wav", "HandClap.wav")]
    fx = paths("CY") + paths("OH") + [t707 / n for n in ("Crash.wav", "Ride.wav", "HhO.wav", "Tamb.wav")]
    keypawn = paths("HC") + paths("MC") + paths("LC") + paths("CB") + paths("CL")
    keypawn += [t707 / n for n in ("CowBell.wav", "HiTom.wav", "MedTom.wav", "LowTom.wav", "Tamb.wav")]
    return {"kick": kicks, "snare": snares, "perc": percussion, "fx": fx, "keypawn": keypawn}


def pack_specs() -> dict[str, tuple[str, float]]:
    specs = {}
    for name in ("AlainKicks.aif", "CuckooKicks.aif", "SebaKicks.aif", "TeKicks.aif"):
        specs[name] = ("kick", 0.92)
    for name in ("AlainSnares.aif", "CuckooSnares.aif", "SebaSnares.aif", "TeSnares.aif"):
        specs[name] = ("snare", 0.78)
    for name in ("AlainPerc.aif", "CuckooPerc.aif", "SebaPerc.aif", "TePercs.aif", "zVinyl.aif"):
        specs[name] = ("perc" if name != "zVinyl.aif" else "fx", 0.78)
    for name in ("AlainFX.aif", "CuckooFX.aif", "SebaFX.aif", "TeFX.aif", "GrantFX.aif"):
        specs[name] = ("fx", 0.76)
    specs["CuckooC_keypawn.aif"] = ("keypawn", 0.80)
    return specs


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def make_slice(source: Path, target: Path, kind: str, index: int, gain: float) -> None:
    seed = hashlib.sha256(f"{source.name}:{target.name}".encode()).digest()
    rng = random.Random(int.from_bytes(seed[:8], "big"))
    pitch = (0.92, 0.96, 1.0, 1.04, 1.08)[index % 5]
    filters = [f"asetrate={RATE * pitch:.1f}", f"aresample={RATE}"]
    if kind == "kick":
        filters += ["highpass=f=28", "lowpass=f=11000"]
    elif kind == "snare":
        filters += ["highpass=f=90", "lowpass=f=15000"]
    elif kind == "keypawn":
        # A recorded TR-808/707 conga, cowbell or tom, tuned across the slices.
        semitones = (index % 12) - 5
        pitch = 2 ** (semitones / 12)
        filters = [f"asetrate={RATE * pitch:.1f}", f"aresample={RATE}", "highpass=f=45", "lowpass=f=15000"]
    elif kind == "fx":
        filters += ["highpass=f=150", "lowpass=f=16000"]
        if index % 4 == 3:
            filters.append("areverse")
        if index % 6 == 5:
            filters.append("aecho=0.7:0.35:55:0.18")
    else:
        filters += ["highpass=f=55", "lowpass=f=15000"]
    filters += [f"volume={gain * rng.uniform(0.82, 1.12):.5f}", "alimiter=limit=0.94",
                f"afade=t=out:st={DURATION - 0.045}:d=0.045", f"apad=whole_dur={DURATION}",
                f"atrim=duration={DURATION}"]
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
         "-af", ",".join(filters), "-ar", str(RATE), "-ac", "1", "-c:a", "pcm_s16le", str(target)])


def rewrite_aiff_name(path: Path) -> dict:
    data = path.read_bytes()
    if data[:4] != b"FORM" or data[8:12] != b"AIFF":
        raise ValueError(f"not an AIFF: {path}")
    chunks, metadata, offset = [], None, 12
    while offset + 8 <= len(data):
        ident = data[offset:offset + 4]
        size = int.from_bytes(data[offset + 4:offset + 8], "big")
        body = data[offset + 8:offset + 8 + size]
        if len(body) != size:
            raise ValueError(f"truncated {ident!r} chunk in {path}")
        if ident == b"APPL" and body[:4] == b"op-1":
            metadata, _ = json.JSONDecoder().raw_decode(body[4:].decode("utf-8"))
            metadata["name"] = "recorded substitute"
            body = b"op-1" + json.dumps(metadata, separators=(",", ":")).encode()
            body += b" " * (len(body) & 1)
        chunks.append((ident, body))
        offset += 8 + size + (size & 1)
    if metadata is None:
        raise ValueError(f"missing APPL/op-1 metadata in {path}")
    form = b"AIFF" + b"".join(i + len(b).to_bytes(4, "big") + b + (b"\0" if len(b) & 1 else b"") for i, b in chunks)
    path.write_bytes(b"FORM" + len(form).to_bytes(4, "big") + form)
    return metadata


def validate(path: Path) -> dict:
    data, offset, chunks = path.read_bytes(), 12, {}
    assert data[:4] == b"FORM" and data[8:12] == b"AIFF" and int.from_bytes(data[4:8], "big") == len(data) - 8
    while offset + 8 <= len(data):
        ident = data[offset:offset + 4]
        size = int.from_bytes(data[offset + 4:offset + 8], "big")
        body = data[offset + 8:offset + 8 + size]
        assert len(body) == size
        chunks.setdefault(ident, []).append(body)
        offset += 8 + size + (size & 1)
    comm = chunks[b"COMM"][0]
    assert int.from_bytes(comm[:2], "big") == 1 and int.from_bytes(comm[6:8], "big") == 16
    frames = int.from_bytes(comm[2:6], "big")
    meta_body = next(b for b in chunks[b"APPL"] if b[:4] == b"op-1")
    meta, _ = json.JSONDecoder().raw_decode(meta_body[4:].decode("utf-8"))
    assert meta["type"] == "drum" and meta["name"] == "recorded substitute"
    assert len(meta["start"]) == len(meta["end"]) == SLICES
    assert all(a < b for a, b in zip(meta["start"], meta["end"]))
    snd = chunks[b"SSND"][0][8:]
    assert any(snd), f"silent audio: {path}"
    return {"bytes": len(data), "frames": frames, "duration_seconds": round(frames / RATE, 3),
            "channels": 1, "sample_rate_hz": RATE, "bits": 16,
            "sha256": hashlib.sha256(data).hexdigest(), "metadata_type": "drum",
            "sources": []}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tool", default="teoperator")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    tool = shutil.which(args.tool) or (str(Path(args.tool).resolve()) if Path(args.tool).exists() else None)
    if not tool:
        parser.error("teoperator not found; install github.com/schollz/teoperator")
    pools, outdir = source_pools(), args.output.resolve()
    specs, manifest = pack_specs(), {"description": "Recorded TR-707/TR-808 audio; not original OP-Z factory recordings.",
        "sources": [{"repo": "https://github.com/fluid-music/open-drums", "commit": "475cc3314fe06f6d1af02e9790ad9707c1f2b26b",
                     "tr707_license": "TR707WAV/README.txt states samples are public domain",
                     "tr808_terms": "tr-808/README.md says the original files have no licensing restrictions; TR808.TXT identifies Michael Fischer and says the set is free"}],
        "formatter": "https://github.com/schollz/teoperator (MIT, commit ddc6ef3)", "files": {}}
    outdir.mkdir(parents=True, exist_ok=True)
    for pool in pools.values():
        missing = [p for p in pool if not p.is_file()]
        if missing:
            parser.error(f"missing source recording: {missing[0]}")
    with tempfile.TemporaryDirectory(prefix="opz-recorded-") as temp:
        tempdir = Path(temp)
        for filename, (kind, gain) in specs.items():
            pool = pools[kind].copy()
            seed = int.from_bytes(hashlib.sha256(filename.encode()).digest()[:8], "big")
            random.Random(seed).shuffle(pool)
            selected = [pool[i % len(pool)] for i in range(SLICES)]
            inputs = []
            for i, source in enumerate(selected):
                clip = tempdir / f"{Path(filename).stem}-{i:02d}.wav"
                make_slice(source, clip, kind, i, gain)
                inputs.append(clip)
            subprocess.run([tool, "drum", *map(str, inputs)], cwd=tempdir, check=True, stdout=subprocess.DEVNULL)
            generated = tempdir / f"{inputs[0].stem}_patch.aif"
            target = outdir / filename
            shutil.copyfile(generated, target)
            rewrite_aiff_name(target)
            info = validate(target)
            info["sources"] = sorted({p.relative_to(SOURCES).as_posix() for p in selected})
            info["kind"] = kind
            manifest["files"][filename] = info
    (outdir / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Created and validated {len(manifest['files'])} recorded-sample AIFFs in {outdir}")


if __name__ == "__main__":
    main()
