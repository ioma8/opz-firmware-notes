#!/usr/bin/env python3
"""Post-decode analysis: turn the recovered payload into named addresses.

Needs no ISA knowledge: an ELF's symbol table is readable for any machine type,
so RETX 0x80117baa can be mapped to a function even for a Blackfin (EM=106) image.
"""
import json, struct, sys, zlib
from pathlib import Path

import struct as _st
def _zfw_len():
    try:
        from pathlib import Path as _P
        d=_P('/Users/jakubkolcar/projects/customs/opz-firmware-notes/z_firmware_1_2_45.zfw').read_bytes()[:0x84]
        if len(d)>=0x84 and d[0x04]==0xff: return _st.unpack_from('<I', d, 0x80)[0]
    except Exception: pass
    return 1490575
ZIP_LEN = _zfw_len()
MAP = Path('/tmp/opzfarm_map.json')

# ---------- ELF ----------
def elf_symbols(buf):
    if buf[:4] != b'\x7fELF': return None
    cls = buf[4]                 # 1=32bit 2=64bit
    end = '<' if buf[5] == 1 else '>'
    if cls == 1:
        e_shoff, e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(end+'IIHHH', buf, 0x20)[0], \
            struct.unpack_from(end+'H', buf, 0x2e)[0], struct.unpack_from(end+'H', buf, 0x30)[0], \
            struct.unpack_from(end+'H', buf, 0x32)[0]
        e_machine = struct.unpack_from(end+'H', buf, 0x12)[0]
    else:
        e_shoff = struct.unpack_from(end+'Q', buf, 0x28)[0]
        e_shentsize = struct.unpack_from(end+'H', buf, 0x3a)[0]
        e_shnum = struct.unpack_from(end+'H', buf, 0x3c)[0]
        e_shstrndx = struct.unpack_from(end+'H', buf, 0x3e)[0]
        e_machine = struct.unpack_from(end+'H', buf, 0x12)[0]
    secs = []
    for i in range(e_shnum):
        off = e_shoff + i*e_shentsize
        if cls == 1: name,typ,flags,addr,offset,size,link,info,align,entsize = struct.unpack_from(end+'10I', buf, off)
        else:        name,typ,flags,addr,offset,size,link,info,align,entsize = struct.unpack_from(end+'IIQQQQIIQQ', buf, off)
        secs.append(dict(name=name,typ=typ,addr=addr,off=offset,size=size,link=link,entsize=entsize))
    strtab = buf[secs[e_shstrndx]['off']:secs[e_shstrndx]['off']+secs[e_shstrndx]['size']] if e_shstrndx < len(secs) else b''
    def nm(o):
        e=strtab.find(b'\0',o); return strtab[o:e].decode('latin1','replace')
    syms=[]
    for s in secs:
        if s['typ'] not in (2,11): continue          # SYMTAB / DYNSYM
        st = secs[s['link']] if s['link'] < len(secs) else None
        if not st: continue
        stab = buf[st['off']:st['off']+st['size']]
        ent = s['entsize'] or (16 if cls==1 else 24)
        for o in range(0, s['size'], ent):
            if o+ent > s['size']: break
            if cls == 1: nameo,value,size,info,other,shndx = struct.unpack_from(end+'IIIBBH', buf, s['off']+o)
            else:        nameo,info,other,shndx,value,size = struct.unpack_from(end+'IBBHQQ', buf, s['off']+o)
            if value == 0: continue
            e=stab.find(b'\0',nameo); name=stab[nameo:e].decode('latin1','replace')
            if name: syms.append((value, size, name))
    syms.sort()
    return dict(machine=e_machine, cls=cls, symbols=syms)

def addr_to_sym(syms, addr):
    lo, hi, best = 0, len(syms)-1, None
    while lo <= hi:
        mid=(lo+hi)//2
        if syms[mid][0] <= addr: best=syms[mid]; lo=mid+1
        else: hi=mid-1
    if best is None: return None
    v,size,name = best
    return (name, addr-v, size)

# ---------- zip (local-header walk; works for streaming archives) ----------
def walk_zip(buf):
    out=[]; o=0; n=len(buf)
    while o+30 <= n:
        if buf[o:o+4] != b'PK\x03\x04':
            nxt = buf.find(b'PK\x03\x04', o+1)
            if nxt < 0: break
            o = nxt; continue
        ver,flags,method = struct.unpack_from('<HHH', buf, o+4)
        csize, usize = struct.unpack_from('<II', buf, o+18)
        nlen, elen = struct.unpack_from('<HH', buf, o+26)
        name = buf[o+30:o+30+nlen].decode('latin1','replace')
        data_off = o+30+nlen+elen
        out.append(dict(off=o, name=name, method=method, flags=flags, csize=csize, usize=usize, data_off=data_off))
        if csize == 0 or flags & 0x08: break     # streaming/data-descriptor: sizes unknown
        o = data_off + csize
    return out

def extract(buf, e):
    raw = buf[e['data_off']:e['data_off']+e['csize']]
    if e['method'] == 0: return raw, 'stored'
    if e['method'] == 8:
        try: return zlib.decompress(raw, -15), 'deflate'
        except Exception as ex: return raw, f'deflate-failed({ex})'
    return raw, f'method{e["method"]}(opaque)'

def main():
    if not MAP.exists(): print("no map yet"); return
    m=json.loads(MAP.read_text())
    buf=bytearray(b'\x00'*ZIP_LEN)
    for k,v in m.items():
        i=int(k)
        if 0 <= i < ZIP_LEN: buf[i]=v
    have=len(m); print(f"payload known {have}/{ZIP_LEN} bytes ({100*have/ZIP_LEN:.2f}%)")
    entries = walk_zip(bytes(buf))
    print(f"zip local headers found: {len(entries)}")
    for e in entries[:12]:
        print(f"  @0x{e['off']:06x} name={e['name']!r} method={e['method']} csize={e['csize']} usize={e['usize']}")
    print("\n-- component classification --")
    for e in entries:
        data,how = extract(bytes(buf), e)
        desc = classify(data)
        print(f"  entry {e['name']!r} ({how}, {len(data)} B): {desc}")
        c = te_container(data)
        if c:
            ss = strings(c['payload'])
            print(f"    payload strings: {len(ss)}" + (f", first: {ss[0][1][:60]!r}" if ss else ""))
        el = elf_symbols(data)
        if el:
            for target in (0x80117baa, 0x8010ea52):
                print(f"    RETX 0x{target:08x} -> {addr_to_sym(el['symbols'], target)}")

# ---------- raw flash image path (no ELF: engines are raw Blackfin blobs) ----------
def raw_symbolize(base, addr):
    """Offset of a runtime address inside a raw image loaded at `base`."""
    if addr < base: return None
    return addr - base

def strings(buf, minlen=6):
    """Printable-string index: '(offset, text)'. Used to verify a decode against
    strings the device itself prints, e.g. 'load general config'."""
    out=[]; i=0; n=len(buf)
    while i < n:
        c=buf[i]
        if 32 <= c < 127:
            j=i
            while j<n and 32 <= buf[j] < 127: j+=1
            if j-i >= minlen: out.append((i, buf[i:j].decode('latin1')))
            i=j
        else: i+=1
    return out

# Strings the OP-Z firmware provably contains (it prints them on the console).
KNOWN_STRINGS = [b'load general config', b'DCPLB_FAULT_ADDR', b'exc reason',
                 b'failed to load slot configuration', b'Calculating used sample memory',
                 b'firmware_bin_only_with_bootloader', b'psoc upgrade row',
                 b'load dmx config', b'Sequencer']

# ---------- TE Blackfin blob container (proven layout, see FIRMWARE_ANALYSIS 43) ----------
def te_container(data):
    """Recognise a TE Blackfin module: 16-byte header whose u32 at 0x0c is
    filesize-16.  Returns a dict or None.  Validated by that exact relation,
    which holds for all 21 known engines."""
    if len(data) < 32: return None
    if data[0:2] != b'\x00\x50': return None
    import struct as _s
    size_field = _s.unpack_from('<I', data, 0x0c)[0]
    if size_field != len(data) - 16: return None
    return dict(opcode=_s.unpack_from('<H', data, 0)[0],
                operand=_s.unpack_from('<H', data, 2)[0],
                shared_base=_s.unpack_from('<I', data, 4)[0],
                payload_size=size_field, payload=data[16:])


def classify(data):
    """Describe a decoded firmware component: TE Blackfin blob, ELF, or raw."""
    c = te_container(data)
    if c:
        return (f"TE Blackfin module: opcode=0x{c['opcode']:04x} operand=0x{c['operand']:04x} "
                f"shared_base=0x{c['shared_base']:08x} payload={c['payload_size']} B")
    el = elf_symbols(data)
    if el:
        return f"ELF cls={el['cls']} machine={el['machine']} symbols={len(el['symbols'])}"
    return f"raw image: {len(data)} B (entropy-eye needed)"

if __name__ == "__main__":
    main()
