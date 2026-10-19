#!/usr/bin/env python3
"""opzsdk.py - write OP-Z engine modules in Python, without touching assembly.

An engine is a five-entry module the OS loads into a slot and calls per voice.  This module supplies
everything around the DSP - header, segments, symbols, prologue, argument access, register allocation,
frame slots, branch encoding - so what is left to write is arithmetic and loops.

    import opzsdk as S

    e = S.Engine("triangle", slot=63)
    COEF = e.words("COEF", rows)                        # a read-only table at a known address

    @e.fn("render", ["out", "pitch", "bend", "ctx", "params", "amp"])
    def render(out, pitch, bend, ctx, params, amp):
        gate = S.var("gate")
        acc = S.var("acc", hot=True)                    # hot: kept in a register
        o, c = S.pin(S.ptr(out)), S.pin(S.ptr(ctx))     # pin: kept in a pointer register
        with S.if_(S.zero(c[0x00])):
            c[0x00].set(1)
            c[0x10].set(0x40000000)                     # seed the oscillator
        acc.set(0)
        with S.repeat(64):                              # one block, as the OS calls it
            acc.set(acc + S.qmul(c[0x10], 0x60000000))
            o.put(acc)                                  # [out++] = acc
            o.put(acc)
        S.unpin(o)
        S.unpin(c)

    e.write("triangle.engine")

Syntax
------
Everything is Python; the DSL supplies what Python cannot express.

  values      `a + b`, `a - b`, `a & b`, `a | b`, `a ^ b`, `a << n`, `a >> n`, `a * b` (Q31 multiply),
              ints, `S.sym("NAME")`, slot reads `c[0x10]`, table reads `TAB[row]`.
  conditions  `a == b`, `a != b`, `a < b`, `a <= b`, `a > b`, `a >= b` (all unsigned, like the machine),
              `S.lt_s(a, b)` / `S.le_s(a, b)` (signed), `S.zero(v)` / `S.nz(v)`, `S.not_(c)`.
  statements  `x.set(v)`, `c[off].set(v)`, `o.put(v)` (post-increment store),
              `with S.if_(c):` / `with S.else_():`, `with S.while_(c):`, `with S.repeat(n):`,
              `S.break_()`, `S.continue_()`, `S.ret(v)`.
  storage     `S.var(name)` - a word in the frame, loaded when used;
              `S.var(name, hot=True)` - a dedicated register for the whole function;
              `S.pin(ptr)` / `S.unpin(p)` - a dedicated pointer register.
  pointers    `S.ptr(word)` for an address held in a word (usually a pointer argument),
              a table symbol, `.at(off)` or `[off]` for a constant offset, `TAB[index]` for a runtime
              index, `S.pin(p).next()` / `o.put(v)` to walk with post-increment.

Semantics worth knowing
-----------------------
`*` is the machine's Q31 fractional multiply: (a*b) >> 32, doubled back into Q31, so 0x40000000 times
0x40000000 is 0x20000000. `+` and `-` are the saturating ones. Shift amounts are build-time constants
because the instruction's immediate is.

Registers: a hot variable and a pin each hold one register for the whole function, taken in declaration
order. Everything else lives in a frame slot. Expression temporaries are allocated and freed per
statement, so an expression that needs more registers than are free raises `SDKError` naming the fix
(name an intermediate in a `var`). There is no liveness analysis, which is why this cannot be silently
wrong.

Branches: every conditional branch is emitted as a short `brcc` over a full `jump`, so a branch to a
distant label cannot fall outside the conditional's +-1 KB reach. Hand-written engines hit exactly that
and needed a hand-placed trampoline.

Frame: the prologue is `LINK <frame>` then `push (R7:4, P5:3)`, so in addition to the slots this SDK
hands out, stack arguments past the third are at `[FP + 8 + 12]`, `[FP + 12 + 12]`, ... which is what
`S.arg(i)` returns.

Not implemented, deliberately: calls into OS host services, interrupts, and the DSP accumulator
instructions. No authored engine needs them, and each would need its ABI verified before it could be
trusted.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import opzasm as A
import opzengine as E

__all__ = ("Engine", "SDKError", "q31", "hz_q16", "qmul", "sym", "ptr", "var", "pin", "unpin",
           "if_", "else_", "while_", "repeat", "break_", "continue_", "ret", "zero", "nz",
           "lt_s", "le_s", "not_", "scale", "mul32", "find_row", "udiv", "Val", "Cond", "Var", "Slot",
           "Ptr", "Pin", "Table", "Sym")

ONE = 0x7FFFFFFF
HALF = 0x40000000


class SDKError(Exception):
    pass


class _Returned(Exception):
    """Unwinds a Python `with` chain after S.ret(), so nothing is emitted after a return."""


def q31(x):
    """Float to Q31, saturating."""
    return max(-2 ** 31, min(2 ** 31 - 1, int(round(x * 2 ** 31))))


def hz_q16(note):
    """MIDI note to the Q16 Hz the OS passes as render's second argument."""
    return int(round(440.0 * 2 ** ((note - 69) / 12.0) * 65536))


# ------------------------------------------------------------------------------- expressions

def _v(x):
    if isinstance(x, Val):
        return x
    if isinstance(x, (Sym, Ptr, Pin, Table)):
        return x
    return Val("imm", int(x) & 0xFFFFFFFF)


class Val:
    """A 32-bit word. Operators build nodes; code is emitted when the function is generated."""

    __slots__ = ("k", "a", "b", "c")
    __hash__ = object.__hash__

    def __init__(self, k, a=None, b=None, c=None):
        self.k, self.a, self.b, self.c = k, a, b, c

    def __add__(self, o): return Val("bin", "+", self, _v(o))
    def __radd__(self, o): return Val("bin", "+", _v(o), self)
    def __sub__(self, o): return Val("bin", "-", self, _v(o))
    def __rsub__(self, o): return Val("bin", "-", _v(o), self)
    def __and__(self, o): return Val("bin", "&", self, _v(o))
    def __rand__(self, o): return Val("bin", "&", _v(o), self)
    def __or__(self, o): return Val("bin", "|", self, _v(o))
    def __ror__(self, o): return Val("bin", "|", _v(o), self)
    def __xor__(self, o): return Val("bin", "^", self, _v(o))
    def __rxor__(self, o): return Val("bin", "^", _v(o), self)
    def __mul__(self, o): return Val("qmul", self, _v(o))
    def __rmul__(self, o): return Val("qmul", _v(o), self)
    def mul32(self, o):
        """The raw product `(a*b) >> 32`: HALF of the Q31 result, without the doubling `*` does."""
        return Val("mul32", self, _v(o))

    def __lshift__(self, n): return Val("shl", self, _shift(n))
    def __rshift__(self, n): return Val("shr", self, _shift(n))

    def __eq__(self, o): return Cond("eq", self, _v(o), True)
    def __ne__(self, o): return Cond("eq", self, _v(o), False)
    def __lt__(self, o): return Cond("lt", self, _v(o), True)
    def __le__(self, o): return Cond("lt", _v(o), self, False)   # !(b < a)
    def __gt__(self, o): return Cond("lt", _v(o), self, True)    # b < a
    def __ge__(self, o): return Cond("lt", self, _v(o), False)   # !(a < b)

    def set(self, v):
        raise SDKError(f"{self!r} is not assignable")

    def __bool__(self):
        raise SDKError("a value has no truth value here: use S.if_(S.nz(v)) or S.if_(S.zero(v))")


def _shift(n):
    if not isinstance(n, int):
        raise SDKError("a shift amount must be a build-time integer: the instruction's imm is")
    return n


class Cond:
    """A comparison. `k` is the compare the machine performs (`eq`, `lt`, `lt_s` or `zero`) and `sense`
    is the CC value that makes the condition hold - `not` absorbs the inversion rather than emitting a
    second compare, so `a != b` is one instruction."""

    __slots__ = ("k", "a", "b", "sense")

    def __init__(self, k, a, b, sense):
        self.k, self.a, self.b, self.sense = k, a, b, sense

    def __bool__(self):
        raise SDKError("a condition is not a Python bool: put it in `with S.if_(...)`")


def zero(v):
    """`v == 0`, which the machine tests without loading an immediate."""
    return Cond("zero", _v(v), None, True)


def nz(v):
    return Cond("zero", _v(v), None, False)


def not_(c):
    return Cond("not", c, None, None)


def lt_s(a, b):
    """Signed compare; the plain `<` is unsigned, which is what a table search wants."""
    return Cond("lt_s", _v(a), _v(b), True)


def le_s(a, b):
    return Cond("lt_s", _v(b), _v(a), False)


def gt_s(a, b):
    return Cond("lt_s", _v(b), _v(a), True)


def ge_s(a, b):
    return Cond("lt_s", _v(a), _v(b), False)


def qmul(a, b):
    """Q31 multiply: `a*b` for two Q31 words, i.e. the machine's (>> 32) form doubled back."""
    return Val("qmul", _v(a), _v(b))


def mul32(a, b):
    """The raw machine product `(a*b) >> 32` - half of `qmul`. Needed whenever the *sum* of squares is
    what is wanted: `qmul(c,c)` alone can reach 1.0, which does not fit Q31 and wraps negative."""
    return Val("mul32", _v(a), _v(b))


# ------------------------------------------------------------------------------- storage

class Sym:
    """An address known at build time."""

    def __init__(self, name, off=0):
        self.name, self.off = name, off

    def at(self, off):
        _need_const(off)
        return type(self)(self.name, self.off + off)

    def __add__(self, off):
        _need_const(off)
        return type(self)(self.name, self.off + off)

    def __getitem__(self, off):
        _need_const(off)
        return Slot(Ptr(self, 0), off)

    def __repr__(self):
        return f"<{self.name}+0x{self.off:x}>"


class Table(Sym):
    """A symbol that also indexes by a runtime value: `TAB[row]` is `[base + row*stride]`."""

    def __init__(self, name, stride=4, off=0):
        Sym.__init__(self, name, off)
        self.stride = stride

    def at(self, off):
        _need_const(off)
        return Table(self.name, self.stride, self.off + off)

    def __getitem__(self, i):
        # the symbol's own offset travels in the base (syms[name] + base.off), so it is NOT added here
        if isinstance(i, int):
            return Slot(Ptr(self, i * self.stride), 0)
        return Slot(Ptr(self, scale(_v(i), self.stride)), 0)

    def row(self, i):
        """A pointer to row `i` of a strided table: COEF.row(note)[0x18] reads word 6 of that row."""
        if isinstance(i, int):
            return Ptr(self, i * self.stride)
        return Ptr(self, scale(_v(i), self.stride))


def scale(v, n):
    """`v * n` for a build-time constant n, as shifts and adds (the machine's multiply is fractional)."""
    if not isinstance(n, int) or n < 0:
        raise SDKError("scale() wants a non-negative build-time constant")
    bits = [b for b in range(32) if n >> b & 1]
    if not bits:
        return Val("imm", 0)
    terms = [v << b if b else v for b in bits]
    out = terms[0]
    for t in terms[1:]:
        out = out + t
    return out


class Ptr:
    """A base plus a constant offset. The base is a symbol, a pin, or a word holding an address."""

    def __init__(self, base, off=0):
        self.base, self.off = base, off

    def at(self, off):
        _need_const(off)
        return Ptr(self.base, self.off + off)

    def __getitem__(self, off):
        _need_const(off)
        return Slot(self, off)

    def __repr__(self):
        return f"<ptr {self.base!r}+0x{self.off:x}>"


def _need_const(off):
    if not isinstance(off, int):
        raise SDKError("a constant offset was expected; use TAB[index] for a runtime index")


def ptr(word):
    """A pointer from a word holding one (usually a pointer argument)."""
    if isinstance(word, Ptr):
        return word
    if isinstance(word, (Sym, Pin)):
        return Ptr(word)
    return Ptr(_v(word))


def sym(name):
    return Sym(name)


class Slot(Val):
    """An assignable word at `ptr + off`."""

    __slots__ = ("p", "off")

    def __init__(self, p, off):
        if isinstance(off, int) and off % 4:
            raise SDKError(f"slot offset 0x{off:x} is not a whole word: offsets are in BYTES, so "
                           f"field 3 of a word array is 0x0c, not 3")
        Val.__init__(self, "load", p, off)
        self.p, self.off = p, off

    def set(self, v):
        _stmt(("store", self, _v(v)))

    def __repr__(self):
        return f"<[{self.p!r}+0x{self.off:x}]>"


class Var(Val):
    """A named word: a frame slot, or a dedicated register when hot."""

    __slots__ = ("name", "hot", "slot", "reg", "argindex")

    def __init__(self, name, hot=False, argindex=None):
        Val.__init__(self, "load", None, None)
        self.name, self.hot, self.slot, self.reg, self.argindex = name, hot, None, None, argindex

    def set(self, v):
        _stmt(("store", self, _v(v)))

    def __repr__(self):
        return f"<var {self.name}>"


class Pin:
    """A pointer held in one register for the whole function."""

    def __init__(self, p):
        self.ptr = ptr(p)
        self.reg = None
        self.alive = True

    def __getitem__(self, off):
        _need_const(off)
        return Slot(self, off)

    def at(self, off):
        _need_const(off)
        return Ptr(self, off)

    def __add__(self, off):
        _need_const(off)
        return Ptr(self, off)

    def put(self, v):
        """Store and advance by one word: the post-increment form."""
        _stmt(("put", self, _v(v)))

    def next(self):
        """Load the word then advance."""
        return Val("get", self, None)


# ------------------------------------------------------------------------------- builder

_builders = []


def _b():
    if not _builders:
        raise SDKError("this DSL call is outside a @e.fn body")
    return _builders[-1]


def _stmt(s):
    _b().cur().append(s)


class _Ctx:
    def __init__(self, b, node, body):
        self.b, self.node, self.body = b, node, body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.b.stack.pop()
        return False


class _Builder:
    def __init__(self):
        self.stmts = []
        self.stack = []
        self.vars = []
        self.pins = []

    def cur(self):
        return self.stack[-1] if self.stack else self.stmts


def if_(cond):
    b = _b()
    node = {"kind": "if", "cond": cond, "body": [], "els": None}
    b.cur().append(node)
    b.stack.append(node["body"])
    return _Ctx(b, node, node["body"])


def else_():
    b = _b()
    parent = b.cur()
    node = parent[-1] if parent else None
    if not node or node.get("kind") != "if" or node["els"] is not None:
        raise SDKError("S.else_() must directly follow a `with S.if_(...):` block in the same block")
    node["els"] = []
    b.stack.append(node["els"])
    return _Ctx(b, node, node["els"])


def while_(cond):
    b = _b()
    node = {"kind": "while", "cond": cond, "body": []}
    b.cur().append(node)
    b.stack.append(node["body"])
    return _Ctx(b, node, node["body"])


def repeat(count):
    b = _b()
    if not isinstance(count, (int, Val)):
        raise SDKError("S.repeat() wants an int or a Val")
    node = {"kind": "repeat", "count": count, "body": []}
    b.cur().append(node)
    b.stack.append(node["body"])
    return _Ctx(b, node, node["body"])


def break_():
    _stmt(("break",))


def continue_():
    _stmt(("continue",))


def ret(v=None):
    """Emit the epilogue and return. Statements written after a return in the same block are still
    emitted (they are unreachable, which costs bytes); a return inside a conditional is the normal case
    and must not stop the rest of the body from being built."""
    _stmt(("ret", None if v is None else _v(v)))


def var(name, hot=False):
    b = _b()
    if any(x.name == name for x in b.vars):
        raise SDKError(f"variable {name!r} is already declared in this function")
    v = Var(name, hot)
    b.vars.append(v)
    return v


def pin(p):
    b = _b()
    q = Pin(p)
    b.pins.append(q)
    return q


def unpin(p):
    """Release a pointer register at this point in the code (statement order, not build order)."""
    _stmt(("unpin", p))


def arg(word):
    """The value of a stack argument beyond the third, by index: S.arg(3) is `[FP + 0x14]`."""
    return word


# ------------------------------------------------------------------------------- macros

def find_row(pitch, freq, rows=128):
    """The index of the largest table row at or below `pitch` (Q16 Hz), by binary search.

    Seven iterations whatever the note, no logarithm and no state. Returns a Var, so the row can be
    stored, compared or used to index another table. A pitch below row 0 gives 0, above the last row
    gives rows-1 - callers should guard, because row 0 is a real (very low) frequency.
    """
    lo, hi, mid = var("search_lo"), var("search_hi"), var("search_mid")
    lo.set(0)
    hi.set(rows - 1)
    with while_(hi - lo > 1):
        mid.set((lo + hi) >> 1)
        with if_(pitch < freq[mid]):
            hi.set(mid)
        with else_():
            lo.set(mid)
    # mid = (lo+hi)>>1 can never reach the last row, so an exact match on it would land a semitone low:
    # that is how the hand-written engine rendered note 127 as note 126.
    with if_(freq[hi] <= pitch):
        lo.set(hi)
    return lo


def udiv(num, den, bits=16):
    """`num / den` as a `bits`-bit fraction, by restoring division (the machine has no divide).

    Q16 output: 0x10000 means 1.0. Both operands must be positive and `den` below 0x4000_0000 or the
    doubled remainder can reach the sign bit.
    """
    r, q = var("div_r"), var("div_q")
    r.set(num)
    q.set(0)
    with repeat(bits):
        r.set(r << 1)
        q.set(q << 1)
        with if_(r >= den):
            r.set(r - den)
            q.set(q + 1)
    return q


# ------------------------------------------------------------------------------- codegen

class _Sig:
    def __init__(self, name, args):
        self.name, self.args = name, list(args)


class Gen:
    D_ALL = ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7")
    P_ALL = ("P0", "P1", "P2", "P3", "P4", "P5")

    def __init__(self, code, sig, syms, argmap):
        self.c = code
        self.sig = sig
        self.syms = syms
        self.argmap = argmap
        self.frame = 8                  # [FP-4] saved FP, [FP-8] saved RETS
        self.free_d = list(self.D_ALL)
        self.free_p = list(self.P_ALL)
        self.loops = []
        self.n = 0

    # ---- resources
    def label(self, stem):
        self.n += 1
        return f"{self.sig.name}${stem}${self.n}"

    def dl(self):
        if not self.free_d:
            raise SDKError(f"{self.sig.name}: out of data registers. Name an intermediate in a S.var(...) "
                           f"so the expression is split across two statements.")
        return self.free_d.pop(0)

    def pl(self):
        if not self.free_p:
            raise SDKError(f"{self.sig.name}: out of pointer registers. S.unpin(...) a pointer that is "
                           f"no longer live.")
        return self.free_p.pop(0)

    def drel(self, r):
        self.free_d.insert(0, r)

    def prel(self, r):
        self.free_p.insert(0, r)

    def slot(self, v):
        if v.slot is None:
            self.frame += 4
            v.slot = self.frame
        return -v.slot

    # ---- prologue / epilogue
    def prologue(self):
        self.c.emit(A.link(self.frame))
        self.c.emit(A.push_r7_p5())
        for i, name in enumerate(self.sig.args):
            v = self.argmap[name]
            if v.reg:
                if i < 3:
                    if v.reg != f"R{i}":
                        self.c.emit(A.regmv(v.reg, f"R{i}"))
                else:
                    self.c.emit(A.ldst_disp("FP", v.reg, 8 + 4 * (i - 3)))
            else:
                if i < 3:
                    self.c.emit(A.ldst_fp(f"R{i}", -self.slot(v), store=True))
                else:
                    self.c.emit(A.ldst_disp("FP", "R0", 8 + 4 * (i - 3)))
                    self.c.emit(A.ldst_fp("R0", -self.slot(v), store=True))

    def epilogue(self):
        self.c.emit(A.pop_r7_p5())
        self.c.emit(A.unlink())
        self.c.emit(A.rts())

    # ---- branch / immediates
    def br(self, target, take_when):
        """Branch to `target` when CC == take_when (or, for take_when=False, when CC == 0).

        Emitted as a short `brcc` over a full `jump`, so the distance to `target` can never fall out of
        the conditional branch's +-1 KB reach - the trampoline the hand-written engines needed."""
        skip = self.label("skip")
        self.c.branch(skip, cond=not take_when)
        self.c.jump(target)
        self.c.label(skip)

    def mv(self, dst, src):
        """A register-to-register move. The 16-bit move only reaches pointer registers, so a data
        register is copied with an OR against itself - the same idiom the hand-written engines use."""
        if dst == src:
            return
        if src in self.P_ALL or src in ("SP", "FP"):
            if dst not in self.P_ALL and dst not in ("SP", "FP", "I0", "I1", "I2", "I3"):
                raise SDKError("a pointer cannot be moved into a data register; keep offsets on the "
                               "pointer (p.at(off)) instead")
            self.c.emit(A.regmv(dst, src))
        else:
            self.c.emit(A.logic32(dst, src, src, "|"))

    def imm(self, reg, value):
        v = value & 0xFFFFFFFF
        s = v - 0x100000000 if v & 0x80000000 else v
        if -64 <= s <= 63:
            self.c.emit(A.ldimm7(reg, s))
        else:
            self.c.emit(A.ldimm32(reg, v))

    # ---- addresses
    def base(self, p):
        """(pointer register, extra offset or None, owned). `owned` means the caller frees the register.

        A static offset comes back as an int for `access()` to fold into a displacement; a runtime one
        comes back as None, already added into the register.
        """
        if isinstance(p, Pin):
            if not p.alive:
                raise SDKError("pointer used after S.unpin()")
            return p.reg, 0, False
        if not isinstance(p, Ptr):
            p = ptr(p)
        b, off = p.base, p.off
        if isinstance(b, Pin):
            if not isinstance(off, int):
                raise SDKError("a pinned pointer takes a constant offset; index a symbol or S.ptr(word) "
                               "instead of a pin")
            return b.reg, off, False
        if isinstance(b, Sym):
            if b.name not in self.syms:
                raise SDKError(f"unknown symbol {b.name!r}")
            addr = self.syms[b.name] + b.off
            if isinstance(off, int):
                reg = self.pl()
                self.c.emit(A.ldimm32(reg, addr + off))
                return reg, 0, True
            r = self.eval(off)
            ra = self.dl()
            self.imm(ra, addr)
            self.c.emit(A.logic32(ra, ra, r, "+"))
            self.drel(r)
            reg = self.pl()
            self.c.emit(A.regmv(reg, ra))
            self.drel(ra)
            return reg, 0, True
        # an address held in a word
        if isinstance(b, Var) and isinstance(off, int):
            reg = self.pl()
            if b.reg:
                self.c.emit(A.regmv(reg, b.reg))
            else:
                self.c.emit(A.ldst_fp(reg, -self.slot(b), preg=True))
            return reg, off, True
        ra = self.dl()
        if isinstance(b, Var):
            if b.reg:
                self.c.emit(A.regmv(ra, b.reg))
            else:
                self.c.emit(A.ldst_fp(ra, -self.slot(b)))
        else:
            r = self.eval(b)
            self.mv(ra, r)
            self.drel(r)
        if isinstance(off, int):
            if off:
                tmp = self.dl()
                self.imm(tmp, off)
                self.c.emit(A.logic32(ra, ra, tmp, "+"))
                self.drel(tmp)
        else:
            r = self.eval(off)
            self.c.emit(A.logic32(ra, ra, r, "+"))
            self.drel(r)
        reg = self.pl()
        self.c.emit(A.regmv(reg, ra))
        self.drel(ra)
        return reg, 0, True

    def pin_load(self, pin):
        """Emit the address a pin holds. Called from the prologue, after the arguments are stored."""
        b, off = pin.ptr.base, pin.ptr.off
        if isinstance(b, Sym):
            if b.name not in self.syms:
                raise SDKError(f"unknown symbol {b.name!r}")
            self.c.emit(A.ldimm32(pin.reg, self.syms[b.name] + b.off + off))
            return
        if isinstance(b, Var):
            if b.reg:
                self.c.emit(A.regmv(pin.reg, b.reg))
            else:
                self.c.emit(A.ldst_fp(pin.reg, -self.slot(b), preg=True))
            if off:
                tmp = self.pl()
                self.c.emit(A.ldimm32(tmp, off & 0xFFFFFFFF))
                self.c.emit(A.ptr2op(pin.reg, tmp, 5))
                self.prel(tmp)
            return
        raise SDKError(f"cannot pin {pin.ptr!r}: pin a symbol or a pointer argument")

    def access(self, p, extra):
        """Resolve to (preg, disp) with disp in 0..0x3c; `owned` means the caller frees the preg."""
        reg, off, owned = self.base(p)
        if off is None:
            return reg, 0, owned
        total = off + extra
        if 0 <= total <= 0x3C:
            return reg, total, owned
        tmp = self.pl()
        self.c.emit(A.ldimm32(tmp, total & 0xFFFFFFFF))
        self.c.emit(A.ptr2op(tmp, reg, 5))          # tmp = tmp + reg
        if owned:
            self.prel(reg)
        return tmp, 0, True

    # ---- expressions
    def eval(self, v):
        k = v.k
        if k == "imm":
            r = self.dl()
            self.imm(r, v.a)
            return r
        if k == "load":
            if isinstance(v, Var):
                r = self.dl()
                if v.reg:
                    self.mv(r, v.reg)
                else:
                    self.c.emit(A.ldst_fp(r, -self.slot(v)))
                return r
            preg, disp, owned = self.access(v.p, v.off)
            r = self.dl()
            if disp == 0:
                self.c.emit(A.ldst(preg, r, aop=2))
            else:
                self.c.emit(A.ldst_disp(preg, r, disp))
            if owned:
                self.prel(preg)
            return r
        if k == "get":
            r = self.dl()
            self.c.emit(A.ldst(v.a.reg, r))
            return r
        if k == "bin":
            ra = self.eval(v.b)
            rb = self.eval(v.c)
            self.c.emit(A.logic32(ra, ra, rb, v.a))
            self.drel(rb)
            return ra
        if k == "mul32":
            ra = self.eval(v.a)
            rb = self.eval(v.b)
            self.c.emit(A.mul32(ra, ra, rb))
            self.drel(rb)
            return ra
        if k == "qmul":
            ra = self.eval(v.a)
            rb = self.eval(v.b)
            self.c.emit(A.mul32(ra, ra, rb))
            self.c.emit(A.logic32(ra, ra, ra, "+"))     # >>32 extraction, doubled back into Q31
            self.drel(rb)
            return ra
        if k in ("shl", "shr"):
            ra = self.eval(v.a)
            self.c.emit((A.shl if k == "shl" else A.shr)(ra, ra, v.b))
            return ra
        raise SDKError(f"expression {v!r}")

    # ---- conditions
    def cond(self, c):
        """Emit the one compare behind this condition and return the CC value that means `true`."""
        if not isinstance(c, Cond):
            raise SDKError(f"{c!r} is not a condition; a bare word needs S.nz(word) or S.zero(word)")
        if c.k == "not":
            return not self.cond(c.a)
        ra = self.eval(c.a)
        if c.k == "zero":
            self.c.emit(A.cmp_eq0(ra))
            self.drel(ra)
            return c.sense
        rb = self.eval(c.b)
        if c.k == "eq":
            self.c.emit(A.comp_eq(ra, rb))
        elif c.k == "lt":
            self.c.emit(A.comp_lt(ra, rb))
        elif c.k == "lt_s":
            self.c.emit(A.comp(ra, rb, "slt"))
        else:
            raise SDKError(f"condition {c!r}")
        self.drel(rb)
        self.drel(ra)
        return c.sense

    # ---- statements
    def stmt(self, s):
        k = s["kind"] if isinstance(s, dict) else s[0]
        if k == "store":
            self.do_store(s[1], s[2])
        elif k == "put":
            r = self.eval(s[2])
            self.c.emit(A.ldst(s[1].reg, r, store=True))
            self.drel(r)
        elif k == "break":
            self.c.jump(self.loops[-1][0])
        elif k == "continue":
            self.c.jump(self.loops[-1][1])
        elif k == "ret":
            if s[1] is not None:
                r = self.eval(s[1])
                self.mv("R0", r)
                self.drel(r)
            self.epilogue()
        elif k == "unpin":
            if s[1].reg is not None:
                self.prel(s[1].reg)
            s[1].alive = False
        elif k == "if":
            self.do_if(s)
        elif k == "while":
            self.do_loop(s, back_edge=True)
        elif k == "repeat":
            self.do_repeat(s)
        else:
            raise SDKError(f"statement {k}")

    def do_store(self, dst, v):
        if isinstance(dst, Var):
            r = self.eval(v)
            if dst.reg:
                self.mv(dst.reg, r)
            else:
                self.c.emit(A.ldst_fp(r, -self.slot(dst), store=True))
            self.drel(r)
            return
        if isinstance(dst, Slot):
            preg, disp, owned = self.access(dst.p, dst.off)
            r = self.eval(v)
            if disp == 0:
                self.c.emit(A.ldst(preg, r, store=True, aop=2))
            else:
                self.c.emit(A.ldst_disp(preg, r, disp, store=True))
            self.drel(r)
            if owned:
                self.prel(preg)
            return
        raise SDKError(f"cannot assign to {dst!r}")

    def do_if(self, s):
        end = self.label("end")
        other = self.label("else")
        sense = self.cond(s["cond"])
        self.br(other, not sense)
        for b in s["body"]:
            self.stmt(b)
        if s["els"] is not None:
            self.c.jump(end)
            self.c.label(other)
            for b in s["els"]:
                self.stmt(b)
            self.c.label(end)
        else:
            self.c.label(other)

    def do_loop(self, s, back_edge):
        top, end = self.label("top"), self.label("end")
        self.c.label(top)
        sense = self.cond(s["cond"])
        self.br(end, not sense)
        self.loops.append((end, top))
        for b in s["body"]:
            self.stmt(b)
        self.loops.pop()
        self.c.jump(top)
        self.c.label(end)

    def do_repeat(self, s):
        cnt = s["count"]
        creg = self.dl()
        if isinstance(cnt, int):
            self.imm(creg, cnt)
        else:
            r = self.eval(cnt)
            self.mv(creg, r)
            self.drel(r)
        top, end = self.label("top"), self.label("end")
        self.c.label(top)
        self.loops.append((end, top))
        for b in s["body"]:
            self.stmt(b)
        self.loops.pop()
        one = self.dl()
        self.imm(one, 1)
        self.c.emit(A.logic32(creg, creg, one, "-"))
        self.drel(one)
        self.c.emit(A.cmp_eq0(creg))
        self.br(top, False)
        self.c.label(end)
        self.drel(creg)


def _ends_with_ret(stmts):
    if not stmts:
        return False
    last = stmts[-1]
    return not isinstance(last, dict) and last[0] == "ret"


# ------------------------------------------------------------------------------- module

class Engine:
    """Placement, data tables, functions, header and container for one .engine module."""

    CODE_RESERVE = 0x1000

    def __init__(self, name, slot, span_slots=3):
        self.name, self.slot, self.span = name, slot, 0x1400 * span_slots
        self.mod_base = 0x81BE4C00 + (slot - 61) * 0x1400
        self.code_base = self.mod_base + 0x38
        self.data_base = self.code_base + self.CODE_RESERVE
        self.data = bytearray()
        self.tables = {}
        self.fns = []
        self.notes = []

    # ---- data
    def words(self, name, values, stride=4):
        while len(self.data) % 4:
            self.data.append(0)
        off = len(self.data)
        for v in values:
            self.data += (int(v) & 0xFFFFFFFF).to_bytes(4, "little")
        self.tables[name] = off
        return Table(name, stride, 0)

    def raw(self, name, blob, align=4):
        while len(self.data) % align:
            self.data.append(0)
        off = len(self.data)
        self.data += blob
        while len(self.data) % 4:
            self.data.append(0)
        self.tables[name] = off
        return Sym(name, 0)

    def reserve(self, name, nbytes):
        return self.raw(name, b"\x00" * nbytes)

    def syms(self):
        return {n: self.data_base + o for n, o in self.tables.items()}

    def note(self, text):
        self.notes.append(text)

    # ---- functions
    def fn(self, name, args=()):
        def deco(body):
            b = _Builder()
            argmap = {a: Var(a, argindex=i) for i, a in enumerate(args)}
            for a in args:
                b.vars.append(argmap[a])
            _builders.append(b)
            try:
                body(*[argmap[a] for a in args])
            finally:
                _builders.pop()
            self.fns.append({"name": name, "args": list(args), "argmap": argmap, "b": b})
            return body
        return deco

    def build(self):
        syms = self.syms()
        code = A.Code(self.code_base)
        labels = {}
        for f in self.fns:
            # build() must be idempotent: register, slot and pin state left over from an earlier build
            # would otherwise make the second build differ from the first.
            for v in f["b"].vars:
                v.reg, v.slot = None, None
            for p_ in f["b"].pins:
                p_.reg, p_.alive = None, True
            b, sig = f["b"], _Sig(f["name"], f["args"])
            g = Gen(code, sig, syms, f["argmap"])
            for v in b.vars:
                if v.hot:
                    v.reg = g.dl()
            for v in b.vars:
                if not v.hot:
                    g.slot(v)          # arguments too: the LINK frame must cover every slot, and it is
                                       # emitted before the prologue stores anything
            pin_emits = []
            for p in b.pins:
                p.reg = g.pl()
                pin_emits.append(p)
            g.frame = (g.frame + 7) // 8 * 8
            if g.frame > 0x7C:
                raise SDKError(f"{f['name']}: frame is {g.frame} B; the machine's frame slots stop at "
                               f"[FP - 0x7c]")
            labels[f["name"]] = code.pos()
            code.label(f["name"])
            g.prologue()
            for p in pin_emits:
                g.pin_load(p)
            for s in b.stmts:
                g.stmt(s)
            if not _ends_with_ret(b.stmts):
                g.epilogue()
        names = {}
        order = ("initModule", "init", "render", "onNoteOn", "onNoteOff")
        for nm in order:
            names[nm] = code.pos()
            code.emit(nm.encode() + b"\x00")
        body = code.finish()
        if len(body) > self.CODE_RESERVE:
            raise SDKError(f"code is {len(body)} B, past the {self.CODE_RESERVE} B reserve that keeps the "
                           f"data address fixed")
        hdr = bytearray()
        hdr += (0xFEED0AD1).to_bytes(4, "little")
        hdr += (0xAD1FACEF).to_bytes(4, "little")
        for nm in order:
            hdr += names[nm].to_bytes(4, "little")
            hdr += labels.get(nm, 0).to_bytes(4, "little")
        hdr += b"\x00" * 8
        assert len(hdr) == 56, len(hdr)
        payload = len(hdr) + len(body) + len(self.data)
        if payload > self.span:
            raise SDKError(f"module is {payload} B, past its {self.span} B slot span")
        segs = [
            (0x5000, 0x11A00000, 0, payload, b""),
            (0x0000, self.mod_base, len(hdr), 0, bytes(hdr)),
            (0x0000, self.code_base, len(body), 0, bytes(body)),
            (0x0000, self.data_base, len(self.data), 0, bytes(self.data)),
            (0x8000, 0x11A00000, 0, 0, b""),
        ]
        self.layout = (len(hdr), len(body), len(self.data))
        self.labels = labels
        return E.pack(segs)

    def write(self, path, quiet=False):
        raw = self.build()
        pathlib.Path(path).write_bytes(raw)
        hl, cl, dl = self.layout
        if not quiet:
            print(f"wrote {path} ({len(raw)} B)")
            print(f"  header {hl} B @0x{self.mod_base:08x}   code {cl} B @0x{self.code_base:08x}"
                  f"   data {dl} B @0x{self.data_base:08x}")
            print(f"  span 0x{self.mod_base:08x}..0x{self.data_base + dl - 1:08x}  (memoryslot {self.slot})")
            print("  exports: " + ", ".join(f"{k}=0x{v:08x}" for k, v in self.labels.items()))
            mod = E.read_module(raw)
            print("  container round-trip: " + ("parsed OK" if mod else "PARSE FAILED"))
        return raw
