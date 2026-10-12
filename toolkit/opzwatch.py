#!/usr/bin/env python3
"""Watch a normal-mode boot and, the instant the OP-Z's MIDI endpoint appears, fetch files
from the device over the clean-room $35/$53 transport.

Why: the app now fully initialises (sequencer, audio, codec, MIDI) before it crashes, so for
the first time normal mode should expose USB-MIDI.  That is an OS-level, read-only file
service - the only host path to the device's own tree (settings/plugs.json, which the crash
log shows is missing, and anything else the OS can open).

Read-only by construction: it imports ~/.opz-decode/toolkit/opzfetch.py, which only ever sends
$51 (advertise) and $35 (file request) - never $52/$53 uploads.

usage: opzwatch.py [SECONDS]        logs to ~/.opz-decode/opzwatch.log
"""
import importlib.util, subprocess, sys, time
from pathlib import Path

H = Path.home() / '.opz-decode'
SECS = int(sys.argv[1]) if len(sys.argv) > 1 else 150
LOG = H / 'opzwatch.log'

# Ordered by value-per-second: the missing plug definitions first, then cheap probes of whether
# the file service reaches outside the user tree, then the rest of the expected user tree.
TARGETS = [
    'settings/plugs.json',            # reserved fileId 1 - the plug definition table the crash needs
    'settings/slotConfiguration.json',# reserved fileId 0
    'config/dmx.json',
    'config/general.json',
    'config/midi.json',
    'arpeggiators/00.txt',
    'engines/tapetwo.engine',         # a probe that should exist
    'versions.txt',                   # cheap guesses at the update/OS side of the tree
    'firmware/versions.txt',
    'blackfin/bin/opz.ldr',
    'firmware/blackfin/bin/opz.ldr',
]


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with LOG.open('a') as fh:
        fh.write(line + '\n')


def main():
    import mido
    log(f"watching {SECS}s for a normal-mode OP-Z (fired fetches are read-only)")
    deadline = time.time() + SECS
    seen_in, seen_out = set(), set()
    fired = False
    while time.time() < deadline:
        try:
            ins, outs = set(mido.get_input_names()), set(mido.get_output_names())
        except Exception as e:
            log(f"mido error: {e}"); time.sleep(1); continue
        if ins != seen_in or outs != seen_out:
            for n in sorted(ins - seen_in): log(f"MIDI IN  + {n!r}")
            for n in sorted(outs - seen_out): log(f"MIDI OUT + {n!r}")
            for n in sorted(seen_in - ins): log(f"MIDI IN  - {n!r}")
            for n in sorted(seen_out - outs): log(f"MIDI OUT - {n!r}")
            seen_in, seen_out = ins, outs
        opz = [n for n in ins | outs if 'OP-Z' in n.upper() or 'OPZ' in n.upper()]
        if opz and not fired:
            fired = True
            log(f"OP-Z MIDI UP ({opz}) - fetching {len(TARGETS)} files now")
            t0 = time.time()
            try:
                r = subprocess.run([str(H / 'opzuv/bin/python'),
                                    str(H / 'toolkit/opzfetch.py'), '--wait', '900', *TARGETS],
                                   capture_output=True, text=True, timeout=max(20, int(deadline - time.time())))
                for line in (r.stdout + r.stderr).splitlines():
                    log("  fetch | " + line[:150])
            except subprocess.TimeoutExpired as e:
                out = (e.stdout or b'').decode('latin1', 'replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
                for line in out.splitlines(): log("  fetch(t) | " + line[:150])
                log("  fetch timed out (device likely crashed)")
            log(f"fetch attempt took {time.time()-t0:.1f}s")
            got = sorted(p.name for p in (H / 'fetched').glob('*')) if (H / 'fetched').is_dir() else []
            log(f"fetched dir now: {got}")
        time.sleep(0.25)
    log(f"watch ended (fired={fired})")
    v = sorted(p.name for p in (H / 'fetched').glob('*')) if (H / 'fetched').is_dir() else []
    log(f"final fetched dir: {v}")


if __name__ == '__main__':
    main()
