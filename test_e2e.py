#!/usr/bin/env python3
"""END-TO-END pipeline verification with a SIMULATED device.

Builds a synthetic firmware payload (a zip with a nameless manifest holding a
string the device provably prints, plus a Blackfin ELF32 'os' image whose symbol
sits exactly at RETX 0x80117baa), then simulates the bootloader's console oracle
-- each window leaks plaintext up to the first NUL, exactly as the real device
does -- and drives the farm's own parser + worklist until coverage completes.
Finally it assembles, walks the zip and resolves the fault address.
"""
import importlib.util, io, struct, zipfile, sys
sys.path.insert(0, '/tmp')
spec=importlib.util.spec_from_file_location("opzfarm","/tmp/opzfarm.py")
F=importlib.util.module_from_spec(spec); spec.loader.exec_module(F)
spec2=importlib.util.spec_from_file_location("opzanalyze","/tmp/opzanalyze.py")
A=importlib.util.module_from_spec(spec2); spec2.loader.exec_module(A)
import opzsim

def blackfin_elf(entry_addr):
    sh=lambda n,t,f,a,o,s,l,i,al,e: struct.pack('<10I',n,t,f,a,o,s,l,i,al,e)
    shstr=b'\x00.shstrtab\x00.symtab\x00.strtab\x00'
    strtab=b'\x00os_fault_function\x00'
    symtab=struct.pack('<IIIBBH',0,0,0,0,0,0)+struct.pack('<IIIBBH',1,entry_addr,128,0x12,0,1)
    TAB=52; NSEC=4; shstr_off=TAB+NSEC*40
    sym_off=shstr_off+len(shstr); str_off=sym_off+len(symtab)
    secs=b''.join([sh(0,0,0,0,0,0,0,0,0,0),
                   sh(11,2,0,0,sym_off,len(symtab),2,1,4,16),
                   sh(19,3,0,0,str_off,len(strtab),0,0,1,0),
                   sh(1,3,0,0,shstr_off,len(shstr),0,0,1,0)])
    ehdr=(b'\x7fELF'+bytes([1,1,1,0])+b'\x00'*8)+struct.pack('<HHIIIIIHHHHHH',
          2,106,1,0x80000000,0,TAB,0,52,32,0,40,NSEC,3)
    return ehdr+secs+shstr+symtab+strtab

# synthetic payload = a zip whose entries mimic the archive layout
man = (b'main: DCPLB_FAULT_ADDR: 0x00000000\n'
       b'snakesystem: load general config /yaffs2/user/config/general.json\n') * 6
import random
random.seed(7)

elf = blackfin_elf(0x80117ba0) + bytes(random.getrandbits(8) for _ in range(3000))
buf = io.BytesIO()
with zipfile.ZipFile(buf,'w',zipfile.ZIP_STORED) as z:
    z.writestr('0', man); z.writestr('1', elf); z.writestr('2', bytes(random.getrandbits(8) for _ in range(1024)))
payload = buf.getvalue()
print(f"synthetic payload: {len(payload)} bytes, {payload.count(b'PK')} local headers")

def simulate_cycle(targets):
    """Emulate one boot through the shared device model: the bootloader leaks each
    window's plaintext up to the first NUL, capped by its 128-byte log buffer."""
    return opzsim.cycle(targets, payload, F.parse_cycle, F.WIN)

N=200; MAXC=20000
st={"pending":[[0,len(payload)]],"bytes":{},"cycles":0,"miss":0}
while st["pending"] and st["cycles"]<MAXC:
    st["pending"].sort()
    targets=st["pending"][:N]
    nb,produced,got=simulate_cycle(targets)
    st["bytes"].update(nb)
    F.advance(st,targets,nb,produced)
    st["cycles"]+=1
cov=sum(1 for k in st["bytes"] if int(k)<len(payload))
over=len(st["bytes"])-cov   # the parser bounds by the module's ZIP_LEN, not by this
                              # synthetic payload, so a window near the end can leak a
                              # few real bytes past it; harmless and out of scope here
print(f"cycles used: {st['cycles']}   coverage: {cov}/{len(payload)} ({100*cov/len(payload):.2f}%)  misses={st['miss']}  over-range={over}")
# assemble from the map exactly as opzassemble.py does
out=bytearray(b'\x00'*len(payload))
for k,v in st["bytes"].items():
    i=int(k)
    if 0<=i<len(payload): out[i]=v
mismatch=sum(1 for i in range(len(payload)) if out[i]!=payload[i])
print("assembled bytes differing from ground truth:", mismatch)
ok = (cov==len(payload) and mismatch==0)
# analysis: walk the zip, find the ELF, resolve the fault address
entries=A.walk_zip(bytes(out))
print("zip entries recovered:", [(e['name'], e['method'], e['csize'], e['usize']) for e in entries])
fault=None
for e in entries:
    data,how=A.extract(bytes(out), e)
    el=A.elf_symbols(data)
    if el:
        r=A.addr_to_sym(el['symbols'], 0x80117baa)
        print(f"  ELF entry {e['name']!r} ({how}) machine={el['machine']} -> RETX 0x80117baa = {r}")
        fault=r
ss=A.strings(bytes(out))
print("string self-check:", [s.decode() for s in A.KNOWN_STRINGS if any(s in t.encode() for _,t in ss)])
ok = ok and fault==('os_fault_function',10,128)
print("END-TO-END RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
