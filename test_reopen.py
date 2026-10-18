#!/usr/bin/env python3
"""Regression test for the console-capture reopen path.

The device re-enumerates mid-cycle (the update volume reappeared ~3 s after the eject),
which kills the open handle.  The original reopen loop accepted pyserial's
`Serial(None)` -- a *closed* object that does not raise -- so every read raised
PortNotOpenError, the loop spun at full speed for the whole window (7,298 log lines in
45 s on the real run) and the console capture, the only thing the cycle exists to get,
was lost entirely.
"""
import contextlib, importlib.util, io, sys, time
spec = importlib.util.spec_from_file_location("F", "/Users/jakubkolcar/projects/customs/opz-firmware-notes/opzfarm.py")
F = importlib.util.module_from_spec(spec); spec.loader.exec_module(F)
_sink = io.StringIO()
F.log = lambda m: _sink.write(m + "\n")     # keep the farm's real evidence log clean

ok = True
def chk(c, m):
    global ok
    if not c: print("  FAIL", m); ok = False
    else: print("  PASS", m)


class FakeSerial:
    def __init__(self, data=b'', open_=True, err=None):
        self.data, self.is_open, self.err = data, open_, err
    def read(self, n):
        if self.err: raise self.err
        if not self.is_open: raise F.serial.PortNotOpenError()
        return self.data
    def close(self): self.is_open = False


# 1. reopen only ever yields a CLOSED handle: must give up quickly, not spin
calls = {'n': 0}
def closed_reopen():
    calls['n'] += 1
    return FakeSerial(open_=False)

t0 = time.time()
buf, ser = F._read_all(FakeSerial(err=OSError(6, 'Device not configured')), 2.0, reopen=closed_reopen)
dt = time.time() - t0
chk(buf == b'', 'closed-handle reopen captures nothing')
chk(ser is None, 'closed-handle reopen reports no usable port')
chk(dt < 8, f'closed-handle reopen gives up inside the window ({dt:.1f}s for a 2s window)')
chk(calls['n'] <= 6, f'closed-handle reopen retries a bounded number of times ({calls["n"]})')
chk(_sink.getvalue().count('serial read failed') == 1,
    f'failure logged once per outage, not per iteration ({_sink.getvalue().count("serial read failed")})')

# 2. reopen yields a WORKING handle: the capture must recover the rest of the window
_sink.truncate(0); _sink.seek(0)
good = FakeSerial(b'leaked-bytes')
buf, ser = F._read_all(FakeSerial(err=OSError(6, 'Device not configured')), 1.0,
                       reopen=lambda: good)
chk(b'leaked-bytes' in buf, f'capture resumes after a working reopen (got {len(buf)}B)')
chk(ser is good, 'the working handle is returned to the caller')

# 3. a reopen that raises must not be treated as success either
_sink.truncate(0); _sink.seek(0)
buf, ser = F._read_all(FakeSerial(err=OSError(6, 'x')), 1.5,
                       reopen=lambda: (_ for _ in ()).throw(OSError('no port')))
chk(ser is None and buf == b'', 'a raising reopen is reported, not accepted')

print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
