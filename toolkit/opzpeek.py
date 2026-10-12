import os, subprocess, sys
print("volumes:", sorted(os.listdir("/Volumes")))
if not os.path.isdir("/Volumes/OP-Z"):
    print("OP-Z not mounted"); sys.exit(0)
code = "import os;print('LISTING:',sorted(os.listdir('/Volumes/OP-Z')))"
try:
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=6)
    print(r.stdout.strip() or r.stderr.strip())
except subprocess.TimeoutExpired:
    print("LISTING TIMED OUT (volume wedged -- device not servicing I/O)")
    sys.exit(3)
# copy anything zip-like, still guarded by a timeout
cpy = ("import glob,shutil,os,time;"
       "fs=[p for p in glob.glob('/Volumes/OP-Z/*') if os.path.isfile(p) and not os.path.basename(p).startswith('._')];"
       "print('FILES:',[(os.path.basename(p),os.path.getsize(p)) for p in fs]);"
       "[shutil.copyfile(p,os.path.expanduser('~/opz-capture-'+time.strftime('%H%M%S')+'-'+os.path.basename(p))) or print('COPIED',p) for p in fs if p.lower().endswith('.zip')]")
try:
    r = subprocess.run([sys.executable, "-c", cpy], capture_output=True, text=True, timeout=20)
    print(r.stdout.strip() or r.stderr.strip())
except subprocess.TimeoutExpired:
    print("COPY TIMED OUT (wedged)")
