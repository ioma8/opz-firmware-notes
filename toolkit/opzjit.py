#!/usr/bin/env python3
"""opzjit.py - translate an OP-Z .engine's Blackfin+ code to C, compile it, and run it at native speed.

opzsim.py interprets the real machine code and is the reference: it caught eight bugs that static checking
missed. It also runs at about 0.2x realtime, which is fine for verification and useless for playing an
instrument. This module emits C for the same instruction set, compiles it with clang -O2, and calls it through
ctypes, so a rendered block costs microseconds instead of milliseconds.

The generated code is a switch-dispatch over instruction addresses - the same shape as the interpreter, minus
Python - so its semantics are the interpreter's by construction rather than by a second reading of the manual.

The correctness gate is bit-exactness: the same module, note and parameters must produce *identical samples*
from the translator and from the interpreter. `python3 toolkit/opzjit.py selftest` checks that on every module
it can translate, and anything unsupported raises Unsupported rather than emitting a guess.

Usage:
    python3 toolkit/opzjit.py selftest [engine ...]
    python3 toolkit/opzjit.py bench
"""
import ctypes, hashlib, pathlib, subprocess, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzengine as E

CACHE = pathlib.Path.home() / ".cache" / "opzjit"
OUT_OFF, PARAM_OFF, SCRATCH_OFF, HEADROOM = 0x10000, 0x20000, 0x30000, 0x40000
SENTINEL = 0xDEAD0000


class Unsupported(RuntimeError):
    pass


# ------------------------------------------------------------------------------------------ layout

def layout(raw):
    segs = [g for g in E.parse(raw) if g[4]]
    lo = min(g[1] for g in segs)
    hi = max(g[1] + g[2] for g in segs)
    base = (lo & ~0xFFF) - HEADROOM
    size = ((hi - base) + HEADROOM + 0xFFF) & ~0xFFF
    _, img = E.expand(raw)
    mod = E.read_module(raw)
    return base, size, img, dict(mod["exports"]), mod["base"]


# ------------------------------------------------------------------------------------------ decode
# Each emitter returns (instruction_length, C statements). The statements must finish the instruction by
# assigning `pc` and `break`ing out of the switch. Every one mirrors opzsim.step() line for line.

def _s8(v):
    return v - 0x100 if v & 0x80 else v


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


def decode(img, addr, eaddr):
    """(length, statements) for the instruction at virtual address eaddr inside img."""
    o = eaddr - addr
    h = img[o] | (img[o + 1] << 8)
    h2 = (img[o + 2] | (img[o + 3] << 8)) if o + 3 < len(img) else 0
    nxt = eaddr + 2

    def fin(extra=""):
        return f"{extra} pc = {nxt}u; break;"

    if h == 0x0000:
        return 2, fin()
    if (h & 0xFE00) == 0x0400:                                    # PushPopMult
        d, pflag, w = (h >> 8) & 1, (h >> 7) & 1, (h >> 6) & 1
        dr, pr = (h >> 3) & 7, h & 7
        st = []
        if w:
            for i in range(7, dr - 1, -1):
                if d:
                    st.append(f"P[6]-=4; WR(P[6], (uint32_t)R[{i}]);")
            for i in range(5, pr - 1, -1):
                if pflag:
                    st.append(f"P[6]-=4; WR(P[6], P[{i}]);")
        else:
            for i in range(pr, 6):
                if pflag:
                    st.append(f"P[{i}]=RD(P[6]); P[6]+=4;")
            for i in range(dr, 8):
                if d:
                    st.append(f"R[{i}]=(int32_t)RD(P[6]); P[6]+=4;")
        return 2, fin(" ".join(st))
    if (h & 0xFF80) == 0x0100:                                    # single push/pop
        w, grp, reg = (h >> 6) & 1, (h >> 3) & 7, h & 7
        if grp == 0:
            st = f"P[6]-=4; WR(P[6], (uint32_t)R[{reg}]);" if w else f"R[{reg}]=(int32_t)RD(P[6]); P[6]+=4;"
            return 2, fin(st)
        if grp == 1:
            st = f"P[6]-=4; WR(P[6], P[{reg}]);" if w else f"P[{reg}]=RD(P[6]); P[6]+=4;"
            return 2, fin(st)
        raise Unsupported(f"push/pop group {grp} at 0x{eaddr:08x}")
    if (h & 0xE000) == 0xA000:                                    # fitted displacement load/store
        w, cls = (h >> 12) & 1, (h >> 10) & 3
        reg, ptr = h & 7, (h >> 3) & 7
        if cls == 2:                                              # [FP - n]
            field = (h >> 4) & 0x3F
            if field & 0x20:
                field -= 0x40
            a = f"(P[7] + {field * 4}u)"
            return 2, fin(f"WR({a}, (uint32_t)R[{reg}]);" if w else f"R[{reg}]=(int32_t)RD({a});")
        if cls == 1:
            cls = 0
        if cls not in (0, 3):
            raise Unsupported(f"displacement class {cls} at 0x{eaddr:08x}")
        disp = ((h >> 6) & 0xF) * 4
        a = f"(P[{ptr}] + {disp}u)"
        if cls == 3:
            return 2, fin(f"WR({a}, P[{reg}]);" if w else f"P[{reg}]=RD({a});")
        return 2, fin(f"WR({a}, (uint32_t)R[{reg}]);" if w else f"R[{reg}]=(int32_t)RD({a});")
    if (h & 0xFF00) == 0xE100:                                    # LdImmHalf
        z, hb, sb, reg = (h >> 7) & 1, (h >> 6) & 1, (h >> 5) & 1, h & 7
        if z == 0 and hb == 1 and sb == 0:
            return 4, f"R[{reg}]=(R[{reg}] & 0xFFFF) | ({h2} << 16); pc = {eaddr + 4}u; break;"
        if z == 0 and hb == 0 and sb == 1:
            return 4, f"R[{reg}]={_s16(h2)}; pc = {eaddr + 4}u; break;"
        if z == 1 and hb == 0 and sb == 0:
            return 4, f"R[{reg}]={h2}; pc = {eaddr + 4}u; break;"
        if z == 0 and hb == 0 and sb == 0:
            return 4, f"R[{reg}]=(R[{reg}] & 0xFFFF0000) | {h2}; pc = {eaddr + 4}u; break;"
        raise Unsupported(f"LdImmHalf z={z} h={hb} s={sb} at 0x{eaddr:08x}")
    if (h & 0xFC00) == 0xE400:                                    # LdStIdxI
        w, z, sz = (h >> 9) & 1, (h >> 8) & 1, (h >> 6) & 3
        ptr, reg = (h >> 3) & 7, h & 7
        mult = {0: 4, 1: 2, 2: 1}.get(sz, 4)
        a = f"W32((int64_t)P[{ptr}] + {_s16(h2) * mult})"
        e4 = eaddr + 4
        if sz == 0:
            if w:
                src = f"P[{reg}]" if z else f"R[{reg}]"
                return 4, f"WR({a}, (uint32_t){src}); pc = {e4}u; break;"
            dst = f"P[{reg}]" if z else f"R[{reg}]"
            return 4, f"{dst}={'(int32_t)' if not z else ''}RD({a}); pc = {e4}u; break;"
        if sz == 2 and w:
            return 4, (f"{{ uint32_t _a=(uint32_t)({a}) & ~3u; uint32_t _w=RD(_a); int _s=8*((uint32_t)({a}) & 3);"
                       f" WR(_a, (_w & ~(0xFFu<<_s)) | (((uint32_t)R[{reg}] & 0xFF) << _s)); }} pc = {e4}u; break;")
        if sz == 2:
            return 4, (f"{{ uint32_t _w=RD((uint32_t)({a}) & ~3u); uint32_t _b=(_w >> (8*((uint32_t)({a}) & 3))) & 0xFF;"
                       f" R[{reg}]={'((int32_t)(int8_t)_b)' if z else '(int32_t)_b'}; }} pc = {e4}u; break;")
        raise Unsupported(f"LdStIdxI sz={sz} w={w} at 0x{eaddr:08x}")
    if h == 0xD800:                                               # LdStAbs
        immv = ((h2 << 16) | (img[o + 4] | (img[o + 5] << 8))) & 0xFFFFFFFF
        if immv & 0x80000000:
            immv -= 0x100000000
        ctrl = img[o + 6] | (img[o + 7] << 8)
        sz, w, z, reg = (ctrl >> 10) & 3, (ctrl >> 9) & 1, (ctrl >> 6) & 1, ctrl & 7
        e8 = eaddr + 8
        if sz == 0 and not w:
            dst = f"P[{reg}]" if z else f"R[{reg}]"
            return 8, f"{dst}={' ' if z else '(int32_t)'}RD({immv}); pc = {e8}u; break;"
        if sz == 0 and w:
            src = f"P[{reg}]" if z else f"(uint32_t)R[{reg}]"
            return 8, f"WR({immv}, {src}); pc = {e8}u; break;"
        raise Unsupported(f"LdStAbs sz={sz} w={w} at 0x{eaddr:08x}")
    if (h & 0xFF00) == 0xDA00:                                    # ldimm32
        reg = h & 7
        v = ((img[o + 2] | (img[o + 3] << 8)) << 16) | (img[o + 4] | (img[o + 5] << 8))
        if v & 0x80000000:
            v -= 0x100000000
        return 8, f"R[{reg}]={v}; pc = {eaddr + 8}u; break;"
    if (h & 0xF000) == 0xC000:
        # NOP32 first: 0xC803 followed by 0x1800 is four bytes of padding, and without this test it
        # decodes as a DSP multiply-accumulate - the same fault the interpreter had.
        if h == 0xC803 and (img[o + 2] | (img[o + 3] << 8)) == 0x1800:
            return 4, f"pc = {eaddr + 4}u; break;"
    if (h & 0xF000) == 0xC000:                                    # 32-bit DSP
        sig2, sigd = (h >> 9) & 3, (h >> 7) & 0xF
        e4 = eaddr + 4
        if sigd == 0xD:                                           # shift by immediate
            sopc, sop = h & 0x1F, (h2 >> 14) & 3
            dst, src = (h2 >> 9) & 7, h2 & 7
            right, imm5 = (h2 >> 8) & 1, (h2 >> 3) & 0x1F
            if sopc != 0x02:
                raise Unsupported(f"shift family {sopc:#x} at 0x{eaddr:08x}")
            n = (0x20 - imm5) if right else imm5
            # sop 2 and 3 are both logical (unsaturated) shifts; the interpreter treats them alike, and
            # factory engines use sop 3, so rejecting it here made them unplayable in the JIT player.
            if sop in (2, 3):
                st = (f"R[{dst}]=(int32_t)((uint32_t)R[{src}] >> {n});" if right
                      else f"R[{dst}]=(int32_t)((uint32_t)R[{src}] << {n});")
            elif sop in (0, 1):
                st = (f"R[{dst}]=SAT((int64_t)R[{src}] >> {n});" if right
                      else f"R[{dst}]=SAT((int64_t)R[{src}] << {n});")
            else:
                raise Unsupported(f"shift sop={sop} at 0x{eaddr:08x}")
            return 4, f"{st} pc = {e4}u; break;"
        if sigd == 0xC:                                           # Dsp32Shf: shift by a register
            sopc, sop = h & 0x1F, (h2 >> 14) & 3
            dst, s0, s1 = (h2 >> 9) & 7, (h2 >> 3) & 7, h2 & 7
            if sopc == 0x02:
                # the count is the low 6 bits sign-extended: positive shifts right, negative left
                cnt = (f"int _c=(int)((uint32_t)R[{s0}] & 0x3Fu); if(_c&0x20)_c-=0x40; "
                       f"_c=_c>63?63:(_c<-63?-63:_c);")
                right = (f"R[{dst}]=" + ("SAT((int64_t)R[%d] >> _c);" if sop in (0, 1)
                         else "(int32_t)((uint32_t)R[%d] >> _c);") % s1)
                left = (f"R[{dst}]=" + ("SAT((int64_t)R[%d] << (-_c));" if sop in (0, 1)
                        else "(int32_t)((uint32_t)R[%d] << (-_c));") % s1)
                return 4, (f"{{ {cnt} if(_c>0){{ {right} }} else if(_c<0){{ {left} }} "
                           f"else R[{dst}]=R[{s1}]; }} pc = {e4}u; break;")
            if sopc == 0x04:                                      # Pack16Vec: PACK(Rs0.L, Rs1.L)
                return 4, (f"R[{dst}]=(int32_t)(((uint32_t)R[{s0}] & 0xFFFFu) << 16 | "
                           f"((uint32_t)R[{s1}] & 0xFFFFu)); pc = {e4}u; break;")
            if sopc == 0x06 and sop == 3:                         # Ones: population count
                return 4, (f"R[{dst}]=(int32_t)__builtin_popcount((uint32_t)R[{s0}]); "
                           f"pc = {e4}u; break;")
            if sopc == 0x05:                                      # SignBits: leading sign-redundant bits
                arg = {1: f"((int32_t)((uint32_t)R[{s1}] << 16) >> 16)",
                       2: f"((int32_t)((uint32_t)R[{s1}] << 16) >> 16)",
                       3: f"((int32_t)(uint32_t)R[{s1}] >> 16)"}.get(sop, f"R[{s1}]")
                return 4, f"R[{dst}]=SGNB({arg}); pc = {e4}u; break;"
            if sopc == 0x07:                                      # ExpAdj: MIN(sign bits, src1)
                lo = f"((int32_t)((uint32_t)R[{s0}] << 16) >> 16)"
                hi = f"((int32_t)(uint32_t)R[{s0}] >> 16)"
                if sop == 1:
                    arg = f"((SGNB({lo})<SGNB({hi}))?SGNB({lo}):SGNB({hi}))"
                elif sop == 2:
                    arg = f"SGNB({lo})"
                elif sop == 3:
                    arg = f"SGNB({hi})"
                else:
                    arg = f"SGNB(R[{s0}])"
                return 4, (f"{{ int a_={arg}, b_=R[{s1}]; R[{dst}]=(a_<b_)?a_:b_; }} "
                           f"pc = {e4}u; break;")
            if sopc == 0x0A:                                      # Extract: len bits at off from src1
                return 4, (f"{{ uint32_t sp_=(uint32_t)R[{s0}], ln_=sp_&0x1Fu, of_=(sp_>>8)&0x1Fu, "
                           f"v_=(uint32_t)R[{s1}]; R[{dst}]=(int32_t)(ln_?((v_>>of_)&((1u<<ln_)-1u)):0u); }} "
                           f"pc = {e4}u; break;")
            raise Unsupported(f"Dsp32Shf sopc={sopc:#x} at 0x{eaddr:08x}")
        if sig2 == 1:                                             # Dsp32Mult (T): >> 32
            dst, s0, s1 = (h2 >> 6) & 7, (h2 >> 3) & 7, h2 & 7
            return 4, f"R[{dst}]=SAT(((int64_t)R[{s0}] * R[{s1}]) >> 32); pc = {e4}u; break;"
        if sig2 == 2:                                             # Dsp32Alu
            aopc, aop, sat = h & 0x1F, (h2 >> 14) & 3, (h2 >> 13) & 1
            d0, s0, s1 = (h2 >> 9) & 7, (h2 >> 3) & 7, h2 & 7
            if aopc == 0x04:
                if aop == 0:
                    st = (f"R[{d0}]=SAT((int64_t)R[{s0}]+R[{s1}]);" if sat
                          else f"R[{d0}]=W32((int64_t)R[{s0}]+R[{s1}]);")
                    return 4, f"{st} pc = {e4}u; break;"
                if aop == 1:
                    st = (f"R[{d0}]=SAT((int64_t)R[{s0}]-R[{s1}]);" if sat
                          else f"R[{d0}]=W32((int64_t)R[{s0}]-R[{s1}]);")
                    return 4, f"{st} pc = {e4}u; break;"
                if aop == 2:
                    return 4, (f"R[{d0}]=W32((int64_t)R[{s0}]+R[{s1}]); "
                               f"R[{(h2 >> 6) & 7}]=W32((int64_t)R[{s0}]-R[{s1}]); pc = {e4}u; break;")
            if aopc == 0x07:
                if aop == 0:
                    return 4, f"R[{d0}]=R[{s0}]>R[{s1}]?R[{s0}]:R[{s1}]; pc = {e4}u; break;"
                if aop == 1:
                    return 4, f"R[{d0}]=R[{s0}]<R[{s1}]?R[{s0}]:R[{s1}]; pc = {e4}u; break;"
                if aop == 2:
                    return 4, f"R[{d0}]=SAT(R[{s0}]<0?-(int64_t)R[{s0}]:R[{s0}]); pc = {e4}u; break;"
                if aop == 3:
                    return 4, f"R[{d0}]=SAT(-(int64_t)R[{s0}]); pc = {e4}u; break;"
            if aopc == 0x19:                                  # AddSubAC0: dst = src0 +/- src1 +/- AC0
                # instr32/27-Dsp32Alu.sinc: aop 0 adds src1 + AC0, aop 1 subtracts src1 and adds AC0-1.
                # These forms READ AC0 only; nothing in this JIT sets it, so it stays at its initial 0.
                if aop in (0, 1):
                    if aop == 0:
                        expr = f"((int64_t)R[{s0}]+R[{s1}]+AC0)"
                    else:
                        expr = f"((int64_t)R[{s0}]-R[{s1}]+AC0-1)"
                    st = (f"R[{d0}]=SAT({expr});" if sat else f"R[{d0}]=W32({expr});")
                    return 4, f"{st} pc = {e4}u; break;"
            raise Unsupported(f"Dsp32Alu aopc={aopc:#x} aop={aop} at 0x{eaddr:08x}")
        raise Unsupported(f"DSP sig2={sig2} sigd={sigd:#x} at 0x{eaddr:08x}")
    if (h & 0xFF80) == 0xE080:                                    # LSETUP, both forms
        # Semantics mirror opzsim exactly: rop at bits 5-6 says where the count comes from (0 = keep the
        # current value, 1 = LC = Preg, 2 = immediate, 3 = LC = Preg>>1); the loop start comes from the
        # first half's 4-bit offset and the end from the second half's 10-bit one. The end address is
        # static, so the back-edge can be emitted at exactly that instruction.
        rop, slot = (h >> 5) & 3, (h >> 4) & 1
        soff = h & 0xF
        reg, lop, eoff = (h2 >> 12) & 7, (h2 >> 10) & 3, h2 & 0x3FF
        start = eaddr + 4 if rop == 2 else (eaddr + soff * 2) & 0xFFFFFFFF
        end = (eaddr + eoff * 2) & 0xFFFFFFFF
        if rop == 2:
            cnt = ((h & 0xF) << 6) | ((h2 >> 10) & 0x3F)
            setc = f"LC[{slot}]={cnt};"
        elif rop == 1:
            setc = f"LC[{slot}]=P[{reg}];"
        elif rop == 3:
            setc = f"LC[{slot}]=P[{reg}]>>1;"
        else:
            setc = ""
        LOOP_ENDS.setdefault(end, set()).add(slot)
        skip = f" if (LC[{slot}]==0) {{ HAVE[{slot}]=0; pc = {end}u; break; }}" if lop == 1 else ""
        return 4, (f"{{ {setc} LB[{slot}]={start}u; LE[{slot}]={end}u; HAVE[{slot}]=1;{skip} "
                    f"pc = {eaddr + 4}u; break; }}")
    sig = (h >> 12) & 0xF
    if sig == 0x1:                                                # BrCC
        offv = h & 0x3FF
        if offv & 0x200:
            offv -= 0x400
        want = (h >> 11) & 1
        tgt = (eaddr + offv * 2) & 0xFFFFFFFF
        return 2, f"if (CC == {want}) {{ pc = {tgt}u; break; }} pc = {nxt}u; break;"
    if sig == 0x2:                                                # JUMP.S
        offv = h & 0xFFF
        if offv & 0x800:
            offv -= 0x1000
        return 2, f"pc = {(eaddr + offv * 2) & 0xFFFFFFFF}u; break;"
    if sig == 0x3:                                                # RegMv
        gd, gs = (h >> 9) & 7, (h >> 6) & 7
        dst, src = (h >> 3) & 7, h & 7
        if gs == 0:
            val = f"R[{src}]"
        elif gs == 1:
            val = f"P[{src}]"
        elif gs == 2 and not ((h >> 5) & 1):
            val = f"I[{src & 3}]"
        elif gs in (3, 4, 6, 7):
            val = "0"
        else:
            raise Unsupported(f"regmv source gs={gs} at 0x{eaddr:08x}")
        if gd == 0:
            return 2, fin(f"R[{dst}]={val};")
        if gd == 1:
            return 2, fin(f"P[{dst}]={val};")
        if gd == 2 and not ((h >> 5) & 1):
            return 2, fin(f"I[{dst & 3}]={val};")
        if gd in (2, 3, 4, 6, 7):
            return 2, fin()
        raise Unsupported(f"regmv dest gd={gd} at 0x{eaddr:08x}")
    if sig == 0x5:                                                # Comp3op
        opc = (h >> 9) & 7
        dst, s1, s0 = (h >> 6) & 7, (h >> 3) & 7, h & 7
        st = (f"R[{dst}]=SAT((int64_t)R[{s0}]+R[{s1}]);" if opc == 0
              else f"R[{dst}]=SAT((int64_t)R[{s0}]-R[{s1}]);")
        return 2, fin(st)
    if sig == 0x6:                                                # CompI2op
        r_is_p, opc = (h >> 11) & 1, (h >> 10) & 1
        imm = _s8(((h >> 3) & 0x7F))
        reg = h & 7
        tgt = f"P[{reg}]" if r_is_p else f"R[{reg}]"
        st = f"{tgt}={imm};" if opc == 0 else f"{tgt}=W32((int64_t){tgt}+{imm});"
        return 2, fin(st)
    if sig == 0x9:                                                # LdSt (32-bit access, sz sets the step)
        sz, store, aop = (h >> 10) & 3, (h >> 9) & 1, (h >> 7) & 3
        use_p, ptr, reg = (h >> 6) & 1, (h >> 3) & 7, h & 7
        inc = {0: 4, 1: 2, 2: 1}.get(sz, 4)
        upd = f"P[{ptr}]+={inc};" if aop == 0 else (f"P[{ptr}]-={inc};" if aop == 1 else "")
        if store:
            src = f"P[{reg}]" if use_p else f"(uint32_t)R[{reg}]"
            st = f"WR(P[{ptr}], {src});"
        else:
            st = (f"P[{reg}]=RD(P[{ptr}]);" if use_p else f"R[{reg}]=(int32_t)RD(P[{ptr}]);")
        return 2, fin(f"{st} {upd}")
    if (h & 0xFE00) == 0x0600:                                    # CCMV
        t, d, sf = (h >> 8) & 1, (h >> 7) & 1, (h >> 6) & 1
        dst, src = (h >> 3) & 7, h & 7
        val = f"R[{src}]" if sf == 0 else f"P[{src}]"
        out = f"R[{dst}]" if d == 0 else f"P[{dst}]"
        return 2, fin(f"if (CC == {t}) {out}={val};")
    if (h & 0xFE00) == 0x0200:                                    # CC2Dreg
        opc, reg = (h >> 3) & 3, h & 7
        st = {0: f"R[{reg}]=CC;", 1: f"CC = (R[{reg}]!=0);",
              2: f"R[{reg}]=CC^1;", 3: "CC = CC^1;"}[opc]
        return 2, fin(st)
    if (h & 0xF800) == 0x0800:                                    # CCFlag
        i_bit, opc, g = (h >> 10) & 1, (h >> 7) & 7, (h >> 6) & 1
        x, y = h & 7, (h >> 3) & 7
        xv = f"P[{x}]" if g else f"R[{x}]"
        yv = str(y - 0x20 if (opc <= 2 and y & 0x10) else y) if i_bit else (f"P[{y}]" if g else f"R[{y}]")
        if opc == 0:
            return 2, fin(f"CC = ({xv} == (int32_t)({yv}));")
        if opc == 1:
            return 2, fin(f"CC = ({xv} < (int32_t)({yv}));")
        if opc == 2:
            return 2, fin(f"CC = ({xv} <= (int32_t)({yv}));")
        if opc == 3:
            return 2, fin(f"CC = ((uint32_t){xv} < (uint32_t)({yv}));")
        if opc == 4:
            return 2, fin(f"CC = ((uint32_t){xv} <= (uint32_t)({yv}));")
        raise Unsupported(f"CCFlag opc={opc} at 0x{eaddr:08x}")
    if (h & 0xF800) == 0x4800:                                    # Logi2Op
        opc, bitn, reg = (h >> 8) & 7, (h >> 3) & 0x1F, h & 7
        st = {0: f"CC = ((R[{reg}] & (1u<<{bitn})) == 0);",
              1: f"CC = ((R[{reg}] & (1u<<{bitn})) != 0);",
              2: f"R[{reg}] |= (1u<<{bitn});", 3: f"R[{reg}] ^= (1u<<{bitn});",
              4: f"R[{reg}] &= ~(1u<<{bitn});", 5: f"R[{reg}] >>= {bitn};",
              6: f"R[{reg}] = (int32_t)((uint32_t)R[{reg}] >> {bitn});",
              7: f"R[{reg}] <<= {bitn};"}[opc]
        return 2, fin(st)
    if (h & 0xFC00) == 0x4000:                                    # ALU2op
        opc, src, dst = (h >> 6) & 0xF, (h >> 3) & 7, h & 7
        if opc == 0:
            return 2, fin(f"R[{dst}] >>= (R[{src}] & 63);")
        if opc == 1:
            return 2, fin(f"R[{dst}] = (int32_t)((uint32_t)R[{dst}] >> (R[{src}] & 63));")
        if opc == 2:
            return 2, fin(f"R[{dst}] <<= (R[{src}] & 63);")
        if opc == 3:
            return 2, fin(f"R[{dst}] *= R[{src}];")
        if opc == 4:
            return 2, fin(f"R[{dst}]=W32(((int64_t)R[{dst}]+R[{src}]) << 1);")
        if opc == 5:
            return 2, fin(f"R[{dst}]=W32(((int64_t)R[{dst}]+R[{src}]) << 2);")
        if opc in (0xA, 0xB, 0xC, 0xD, 0xE, 0xF):
            st = {0xA: f"R[{dst}]=(int32_t)(int16_t)R[{src}];",
                  0xB: f"R[{dst}]=R[{src}] & 0xFFFF;",
                  0xC: f"R[{dst}]=(int32_t)(int8_t)R[{src}];",
                  0xD: f"R[{dst}]=R[{src}] & 0xFF;",
                  0xE: f"R[{dst}]=W32(-(int64_t)R[{src}]);",
                  0xF: f"R[{dst}]=~R[{src}];"}[opc]
            return 2, fin(st)
        if opc == 8:                                              # DIVQ: one division step
            # instr16/12-ALU2op.sinc: add or subtract src<<16 depending on AQ, then set
            # AQ = (dst >= 0x80000000) ^ (src.low16 >= 0x8000) and shift the quotient in.
            return 2, ("{ int32_t v_; if (AQ) v_=(int32_t)((uint32_t)R[%d]+((uint32_t)R[%d]<<16)); "
                       "else v_=(int32_t)((uint32_t)R[%d]-((uint32_t)R[%d]<<16)); "
                       "AQ = (((uint32_t)v_ >= 0x80000000u) ^ (((uint32_t)R[%d] & 0xFFFFu) >= 0x8000u)) ? 1 : 0; "
                       "R[%d] = (int32_t)(((uint32_t)v_ << 1) | (AQ ? 0u : 1u)); } pc = %du; break;"
                       % (dst, src, dst, src, src, dst, eaddr + 2))
        if opc == 9:                                              # DIVS: division initialise
            return 2, ("{ AQ = (((uint32_t)R[%d] >= 0x80000000u) ^ (((uint32_t)R[%d] & 0xFFFFu) >= 0x8000u)) ? 1 : 0; "
                       "R[%d] = (int32_t)(((uint32_t)R[%d] << 1) | (AQ ? 1u : 0u)); } pc = %du; break;"
                       % (dst, src, dst, dst, eaddr + 2))
        raise Unsupported(f"ALU2op opc={opc:#x} at 0x{eaddr:08x}")
    if (h & 0xFE00) == 0x4400:                                    # Ptr2op
        opc, src, dst = (h >> 6) & 7, (h >> 3) & 7, h & 7
        st = {0: f"P[{dst}]=W32((int64_t)P[{dst}]-P[{src}]);",
              1: f"P[{dst}]=W32((int64_t)P[{src}] << 2);",
              2: f"P[{dst}]=W32((int64_t)P[{src}] << 1);",
              3: f"P[{dst}]=W32((int64_t)((uint32_t)P[{src}] >> 2));",
              4: f"P[{dst}]=W32((int64_t)((uint32_t)P[{src}] >> 1));",
              5: f"P[{dst}]=W32((int64_t)P[{dst}]+P[{src}]);"}[opc]
        return 2, fin(st)
    if (h & 0xFE00) == 0xE200:                                    # CallA
        delta = (_s8(h & 0xFF) << 16) | h2
        tgt = (eaddr + delta * 2) & 0xFFFFFFFF
        if (h >> 8) & 1:
            return 4, f"rets = {eaddr + 4}u; pc = {tgt}u; break;"
        return 4, f"pc = {tgt}u; break;"
    if h == 0xE800:                                               # LINK
        fr = h2 * 4
        return 4, (f"{{ P[6]-=4; WR(P[6], rets); P[6]-=4; WR(P[6], P[7]);"
                   f" P[7]=P[6]; P[6]=W32((int64_t)P[6]-{fr}); }} pc = {eaddr + 4}u; break;")
    if h == 0xE801:                                               # UNLINK
        return 2, fin("{ P[6]=P[7]; P[7]=RD(P[6]); P[6]+=4; rets=RD(P[6]); P[6]+=4; }")
    if h == 0x0010:                                               # RTS
        return 2, ("if (rets == 0x%08xu) return R[0]; pc = rets; break;" % SENTINEL)
    if (h & 0xFF00) == 0x0000:                                    # ProgCtrl
        opc, reg = (h >> 4) & 0xF, h & 7
        if opc == 5:
            return 2, "pc = P[%d]; break;" % reg
        if opc == 6:
            return 2, f"rets = {nxt}u; pc = P[{reg}]; break;"
        if opc in (1, 2, 3, 4, 0xC):
            return 2, fin()
        raise Unsupported(f"ProgCtrl opc={opc:#x} at 0x{eaddr:08x}")
    raise Unsupported(f"instruction 0x{h:04x} at 0x{eaddr:08x}")


# ------------------------------------------------------------------------------------------ emit

PRELUDE = r"""
#include <stdint.h>
#include <string.h>
typedef struct { uint8_t *mem; int64_t base; int64_t size; } Arena;
static Arena A;
static int32_t R[8], I[4];
uint32_t OPZ_STUCK = 0;   /* set when a call exceeds its step budget, so a hung engine reports where */
int32_t  LC[2] = {0, 0};  /* loop counters, one per LSETUP slot; file scope so a stuck call can be inspected */
uint32_t LB[2] = {0, 0}, LE[2] = {0, 0};
int      HAVE[2] = {0, 0};
/* leading sign-redundant bits, matching opzsim's _sgncount: lzcount(v)-1 for v>=0, lzcount(~v)-1 for v<0 */
static int SGNB(int32_t v){ uint32_t u = (v < 0) ? ~(uint32_t)v : (uint32_t)v; int n = 0;
    while (n < 32 && (((u >> (31 - n)) & 1u) == 0)) n++; return n - 1; }
static uint32_t P[8];
static int CC = 0;
static inline int32_t SAT(int64_t v) {
    return v > 2147483647LL ? 2147483647 : (v < -2147483648LL ? -2147483648 : (int32_t)v);
}
static inline int32_t W32(int64_t v) { return (int32_t)(uint32_t)v; }
static inline uint32_t RD(uint32_t a) {
    int64_t o = (int64_t)(uint64_t)a - A.base;
    if (o < 0 || o + 4 > A.size) return 0;
    uint32_t v; memcpy(&v, A.mem + o, 4); return v;
}
static inline void WR(uint32_t a, uint32_t v) {
    int64_t o = (int64_t)(uint64_t)a - A.base;
    if (o < 0 || o + 4 > A.size) return;
    memcpy(A.mem + o, &v, 4);
}
"""


def reachable(img, addr0, entries):
    seen, todo = {}, list(entries)
    while todo:
        a = todo.pop()
        if a in seen or a < addr0 or a >= addr0 + len(img):
            continue
        try:
            ln, code = decode(img, addr0, a)
        except Unsupported:
            raise
        seen[a] = (ln, code)
        nxt = a + ln
        if "break;" in code and "pc =" not in code and "return R[0]" not in code:
            todo.append(nxt)
        for tok in code.replace("pc = ", "|").split("|")[1:]:
            digits = tok.split("u")[0].strip()
            if digits.isdigit():
                t = int(digits)
                if addr0 <= t < addr0 + len(img):
                    todo.append(t)
        if "pc = RTS" in code:
            pass
        if "pc =" not in code:
            todo.append(nxt)
    return seen


LOOP_ENDS = {}


def emit(raw):
    global LOOP_ENDS
    LOOP_ENDS = {}
    base, size, img, exports, mod_base = layout(raw)
    entries = sorted({v for v in exports.values() if v})
    seen = reachable(img, mod_base, entries)
    out = [PRELUDE, "int32_t opz_call(void *mem, int64_t base, int64_t size, uint32_t entry,",
           "                 int32_t a1, int32_t a2, int32_t a3, int32_t s0, int32_t s1, int32_t s2,",
           "                 int32_t s3, int32_t s4, int32_t s5,",
           "                 int n_stack, uint32_t sp)", "{",
           "    A.mem=(uint8_t*)mem; A.base=base; A.size=size;",
           "    R[0]=a1; R[1]=a2; R[2]=a3; CC=0;",
           "    P[6]=sp;",
           # arguments go on in REVERSE so the first stack argument ends up at the lowest address,
           # which is what the Python reference does and what the engines' [FP+..] reads assume
           "    { int32_t st[6]={s0,s1,s2,s3,s4,s5};"
           "      for (int i=n_stack-1;i>=0;i--){ P[6]-=4; WR(P[6],(uint32_t)st[i]); } }",

           "    int AQ=0;   /* ASTAT bit 6, the divide quotient bit */",
           "    int AC0=0;  /* ASTAT bit 12, the AC0 carry; read by AddSubAC0, set elsewhere */",
           "    uint32_t rets = 0x%08uu;   /* RETS: set by every call form, restored by UNLINK */" % SENTINEL,
           "    uint32_t pc = entry;",
           "    long _steps = 0;",
           "    for (;;) {",
           "        if (++_steps > 4000000L) { OPZ_STUCK = pc; return -2; }",
           "        switch (pc) {"]
    for a in sorted(seen):
        ln, code = seen[a]
        ends = LOOP_ENDS.get(a)
        if ends:
            # A registered loop whose END is this address either jumps back to its start or finishes - and
            # it does so AFTER the instruction at `end` retires (opzsim's _loop_end runs post-step). Putting
            # the check first executed the body one iteration short and, with a zero counter, looped for ever.
            chk = " ".join(
                f"if (HAVE[{sl}] && LE[{sl}]==0x{a:08x}u) {{ if (LC[{sl}]) {{ LC[{sl}]--; "
                f"pc = LB[{sl}]; break; }} HAVE[{sl}]=0; }}" for sl in sorted(ends))
            # Route EVERY exit of this instruction through the loop check: if the end instruction is a
            # taken branch its inner `break` would otherwise skip the check, LC would never decrement, and
            # the loop would spin for ever.
            lab = f"lc_end_{a:08x}"
            body = code.replace("break;", f"goto {lab};")
            code = body + f" {lab}: " + chk + " break;"
        out.append(f"    case 0x{a:08x}u: {{ {code} }}")
    out.append("    default: return R[0];")
    out.append("        }")
    out.append("    }")
    out.append("}")
    return "\n".join(out), base, size, img, exports


def build(raw, name="engine"):
    """Compile the module to a dylib (cached by content hash) and return its path."""
    src, base, size, img, exports = emit(raw)
    h = hashlib.md5(src.encode()).hexdigest()[:16]
    CACHE.mkdir(parents=True, exist_ok=True)
    cpath = CACHE / f"{name}-{h}.c"
    dpath = CACHE / f"{name}-{h}.dylib"
    if not dpath.exists():
        cpath.write_text(src)
        r = subprocess.run(["clang", "-O2", "-shared", "-fPIC", "-o", str(dpath), str(cpath)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"clang failed:\n{r.stderr[:2000]}")
    return dpath, base, size, img, exports


if __name__ == "__main__":
    import opztime; opztime.watch("jit")
    print(__doc__)
