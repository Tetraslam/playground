"""T16 two-pass assembler (owner: agent 3).

Syntax (see PLAN.md): one statement per line, `;` comments, `label:` prefixes,
case-insensitive mnemonics/registers/directives, case-sensitive symbols.
Directives: .org .word .zero .string .equ .include. Expressions support
`+ - * / % & | ^ << >> ~ ( )`, numbers (dec, 0x, 0b), char literals, symbols.
Every name from `isa.mmio_constants()` is predefined.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from . import isa


class AsmError(Exception):
    """Assembly error; the message starts with `file:line:`."""


@dataclass
class Image:
    words: dict[int, int] = field(default_factory=dict)  # addr -> 16-bit word
    symbols: dict[str, int] = field(default_factory=dict)  # labels + .equ
    lines: dict[int, str] = field(default_factory=dict)  # instr addr -> "file:line  source"
    labels: set[str] = field(default_factory=set)  # which symbols are labels (vs .equ)


# ---- lexing ---------------------------------------------------------------

_ESCAPES = {"n": 10, "t": 9, "r": 13, "0": 0, "\\": 92, "'": 39, '"': 34, "e": 27}
_TOKEN = re.compile(
    r"\s*(?:"
    r"(?P<num>0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*)"
    r"|(?P<chr>'(?:\\.|[^'\\])')"
    r"|(?P<name>[A-Za-z_.$][A-Za-z0-9_.$]*)"
    r"|(?P<op><<|>>|[-+*/%&|^~()])"
    r")"
)
_NAME = re.compile(r"[A-Za-z_.$][A-Za-z0-9_.$]*$")


def _unescape(body: str, where: str) -> list[int]:
    out, i = [], 0
    while i < len(body):
        c = body[i]
        if c == "\\":
            if i + 1 >= len(body):
                raise AsmError(f"{where}: dangling backslash")
            e = body[i + 1]
            if e == "x":
                hexs = body[i + 2 : i + 4]
                if len(hexs) != 2:
                    raise AsmError(f"{where}: bad \\x escape")
                out.append(int(hexs, 16))
                i += 4
                continue
            if e not in _ESCAPES:
                raise AsmError(f"{where}: unknown escape \\{e}")
            out.append(_ESCAPES[e])
            i += 2
        else:
            out.append(ord(c))
            i += 1
    return out


def _strip_comment(line: str) -> str:
    quote = None
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        elif c == ";":
            return line[:i]
        i += 1
    return line


def _split_operands(s: str) -> list[str]:
    """Split on commas outside quotes/brackets/parens."""
    parts, depth, quote, cur, i = [], 0, None, [], 0
    while i < len(s):
        c = s[i]
        if quote:
            cur.append(c)
            if c == "\\" and i + 1 < len(s):
                cur.append(s[i + 1])
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
            cur.append(c)
        elif c in "([":
            depth += 1
            cur.append(c)
        elif c in ")]":
            depth -= 1
            cur.append(c)
        elif c == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    tail = "".join(cur).strip()
    if tail or parts:
        parts.append(tail)
    return parts


# ---- expressions ------------------------------------------------------------


class _Expr:
    """Tokenized expression; evaluated later against a symbol resolver."""

    def __init__(self, text: str, where: str):
        self.text, self.where, self.toks = text, where, []
        pos, text = 0, text.rstrip()
        while pos < len(text):
            m = _TOKEN.match(text, pos)
            if not m or m.end() == pos:
                raise AsmError(f"{where}: bad expression {text!r} at {text[pos:]!r}")
            pos = m.end()
            kind = m.lastgroup
            val = m.group(kind)
            if kind == "num":
                val = int(val.replace("_", ""), 0)
            elif kind == "chr":
                cs = _unescape(val[1:-1], where)
                if len(cs) != 1:
                    raise AsmError(f"{where}: bad char literal {val}")
                kind, val = "num", cs[0]
            self.toks.append((kind, val))
        if not self.toks:
            raise AsmError(f"{where}: empty expression")

    def names(self) -> list[str]:
        return [v for k, v in self.toks if k == "name"]

    def eval(self, lookup) -> int:
        toks, i = self.toks, 0
        w = self.where

        def peek():
            return toks[i][1] if i < len(toks) and toks[i][0] == "op" else None

        def take():
            nonlocal i
            i += 1
            return toks[i - 1]

        def atom():
            if i >= len(toks):
                raise AsmError(f"{w}: unexpected end of expression {self.text!r}")
            kind, val = take()
            if kind == "num":
                return val
            if kind == "name":
                if val.lower() in isa.REGS:
                    raise AsmError(f"{w}: register {val} not allowed in expression")
                return lookup(val)
            if val == "(":
                v = bor()
                if peek() != ")":
                    raise AsmError(f"{w}: missing ')' in {self.text!r}")
                take()
                return v
            if val == "-":
                return -atom()
            if val == "+":
                return atom()
            if val == "~":
                return ~atom()
            raise AsmError(f"{w}: unexpected {val!r} in {self.text!r}")

        def binary(sub, ops):
            def f():
                v = sub()
                while peek() in ops:
                    op = take()[1]
                    r = sub()
                    if op in ("/", "%") and r == 0:
                        raise AsmError(f"{w}: division by zero in {self.text!r}")
                    if op == "/":
                        v = int(v / r)
                    elif op == "%":
                        v = v - r * int(v / r)
                    else:
                        v = {
                            "*": lambda a, b: a * b,
                            "+": lambda a, b: a + b,
                            "-": lambda a, b: a - b,
                            "<<": lambda a, b: a << b,
                            ">>": lambda a, b: a >> b,
                            "&": lambda a, b: a & b,
                            "^": lambda a, b: a ^ b,
                            "|": lambda a, b: a | b,
                        }[op](v, r)
                return v

            return f

        mul = binary(atom, ("*", "/", "%"))
        add = binary(mul, ("+", "-"))
        shift = binary(add, ("<<", ">>"))
        band = binary(shift, ("&",))
        bxor = binary(band, ("^",))
        bor = binary(bxor, ("|",))
        v = bor()
        if i != len(toks):
            raise AsmError(f"{w}: trailing junk in expression {self.text!r}")
        return v


# ---- statements -------------------------------------------------------------


@dataclass
class _Stmt:
    addr: int
    kind: str  # "instr" | "word" | "string" | "zero"
    where: str
    source: str
    op: str = ""
    args: list = field(default_factory=list)


def _reg(tok: str) -> int | None:
    return isa.REGS.get(tok.strip().lower())


def _word(v: int, where: str, what: str = "value") -> int:
    if not -0x8000 <= v <= 0xFFFF:
        raise AsmError(f"{where}: {what} {v} does not fit in 16 bits")
    return v & 0xFFFF


class _Assembler:
    def __init__(self):
        self.symbols: dict[str, int] = {}
        self.equs: dict[str, _Expr] = {}
        self.defined_at: dict[str, str] = {}
        self.stmts: list[_Stmt] = []
        self.pc = isa.CODE_BASE
        self.include_stack: list[str] = []

    # symbol resolution: labels, then .equ (lazy, cycle-checked), then isa
    def lookup(self, name: str, where: str, resolving=()) -> int:
        if name in self.symbols:
            return self.symbols[name]
        if name in self.equs:
            if name in resolving:
                raise AsmError(f"{where}: circular .equ {name}")
            e = self.equs[name]
            v = e.eval(lambda n: self.lookup(n, e.where, resolving + (name,)))
            self.symbols[name] = v
            return v
        consts = isa.mmio_constants()
        if name in consts:
            return consts[name]
        raise AsmError(f"{where}: undefined symbol {name}")

    def now(self, expr: _Expr) -> int:
        """Evaluate in pass 1 (only already-known symbols)."""
        return expr.eval(lambda n: self.lookup(n, expr.where))

    def define(self, name: str, where: str):
        if not _NAME.match(name) or name.lower() in isa.REGS:
            raise AsmError(f"{where}: bad symbol name {name!r}")
        if name in self.defined_at:
            raise AsmError(
                f"{where}: duplicate symbol {name} (first defined at {self.defined_at[name]})"
            )
        if name in isa.mmio_constants():
            raise AsmError(f"{where}: {name} shadows a predefined isa constant")
        self.defined_at[name] = where

    # pass 1 ---------------------------------------------------------------
    def source(self, src: str, path: str):
        real = os.path.realpath(path) if os.path.exists(path) else path
        if real in self.include_stack:
            raise AsmError(f"{path}: circular .include")
        self.include_stack.append(real)
        base = os.path.dirname(path) if os.path.exists(path) else os.getcwd()
        for lineno, raw in enumerate(src.splitlines(), 1):
            where = f"{path}:{lineno}"
            line = _strip_comment(raw).strip()
            # labels (possibly several) at line start
            while True:
                m = re.match(r"([A-Za-z_.$][A-Za-z0-9_.$]*)\s*:(?!:)", line)
                if not m or m.group(1).lower() in _DIRECTIVES:
                    break
                name = m.group(1)
                self.define(name, where)
                self.symbols[name] = self.pc
                line = line[m.end() :].strip()
            if not line:
                continue
            head, rest = (re.split(r"\s+", line, maxsplit=1) + [""])[:2]
            rest = rest.strip()
            low = head.lower()
            if low.startswith("."):
                self.directive(low, rest, where, raw.strip(), base)
            else:
                op = head.upper()
                if op not in isa.OPCODES:
                    raise AsmError(f"{where}: unknown mnemonic {head}")
                self.emit(_Stmt(self.pc, "instr", where, raw.strip(), op, _split_operands(rest)), 2)
        self.include_stack.pop()

    def emit(self, st: _Stmt, size: int):
        if self.pc + size > 0x10000:
            raise AsmError(f"{st.where}: address overflow past 0xFFFF")
        self.stmts.append(st)
        self.pc += size

    def directive(self, d: str, rest: str, where: str, raw: str, base: str):
        if d == ".org":
            v = self.now(_Expr(rest, where))
            if not 0 <= v <= 0xFFFF:
                raise AsmError(f"{where}: .org out of range: {v}")
            self.pc = v
        elif d == ".equ":
            parts = _split_operands(rest)
            if len(parts) != 2:
                raise AsmError(f"{where}: .equ NAME, expr")
            name = parts[0]
            self.define(name, where)
            self.equs[name] = _Expr(parts[1], where)
        elif d == ".word":
            exprs = [_Expr(p, where) for p in _split_operands(rest)]
            if not exprs:
                raise AsmError(f"{where}: .word needs values")
            self.emit(_Stmt(self.pc, "word", where, raw, args=exprs), len(exprs))
        elif d == ".zero":
            n = self.now(_Expr(rest, where))
            if n < 0:
                raise AsmError(f"{where}: .zero count must be >= 0")
            self.emit(_Stmt(self.pc, "zero", where, raw, args=[n]), n)
        elif d in (".string", ".ascii"):
            m = re.fullmatch(r'"((?:\\.|[^"\\])*)"', rest)
            if not m:
                raise AsmError(f'{where}: {d} needs a "quoted string"')
            chars = _unescape(m.group(1), where)
            if d == ".string":
                chars.append(0)
            self.emit(_Stmt(self.pc, "string", where, raw, args=chars), len(chars))
        elif d == ".include":
            m = re.fullmatch(r'"([^"]+)"', rest)
            if not m:
                raise AsmError(f'{where}: .include "file.s"')
            inc = os.path.join(base, m.group(1))
            try:
                with open(inc) as f:
                    text = f.read()
            except OSError as e:
                raise AsmError(f"{where}: cannot include {m.group(1)}: {e.strerror}") from None
            self.source(text, inc)
        else:
            raise AsmError(f"{where}: unknown directive {d}")

    # pass 2 ---------------------------------------------------------------
    def value(self, text: str, where: str) -> int:
        e = _Expr(text, where)
        return e.eval(lambda n: self.lookup(n, where))

    def mem(self, text: str, where: str) -> tuple[int, int]:
        """`[rX]`, `[rX+e]`, `[rX-e]`, `[e]` -> (base field, imm)."""
        t = text.strip()
        if not (t.startswith("[") and t.endswith("]")):
            raise AsmError(f"{where}: expected memory operand [..], got {text!r}")
        inner = t[1:-1].strip()
        m = re.match(r"([A-Za-z0-9]+)\s*(?=$|[+-])", inner)
        if m and _reg(m.group(1)) is not None:
            base = _reg(m.group(1))
            tail = inner[m.end() :].strip()
            if not tail:
                return base, 0
            if tail[0] == "+":
                return base, self.value(tail[1:], where)
            return base, -self.value(tail[1:], where)
        return isa.ZERO_BASE, self.value(inner, where)

    def reg(self, text: str, where: str) -> int:
        r = _reg(text)
        if r is None:
            raise AsmError(f"{where}: expected register, got {text!r}")
        return r

    def encode(self, st: _Stmt) -> tuple[int, int]:
        op, a, w = st.op, st.args, st.where
        form = isa.OPCODES[op][1]
        want = {"": 0, "rd": 1, "rs": 1, "imm": 1}.get(form, 2)
        if len(a) != want:
            raise AsmError(f"{w}: {op} takes {want} operand(s) ({form or 'none'}), got {len(a)}")
        rd = rs = imm = 0
        if form == "rd,rs":
            rd, rs = self.reg(a[0], w), self.reg(a[1], w)
        elif form == "rd,imm":
            rd, imm = self.reg(a[0], w), self.value(a[1], w)
        elif form == "rd":
            rd = self.reg(a[0], w)
        elif form == "rs":
            rs = self.reg(a[0], w)
        elif form == "imm":
            imm = self.value(a[0], w)
        elif form == "rs,imm":
            rs, imm = self.reg(a[0], w), self.value(a[1], w)
        elif form == "mem_ld":
            rd = self.reg(a[0], w)
            rs, imm = self.mem(a[1], w)
        elif form == "mem_st":
            rd, imm = self.mem(a[0], w)
            rs = self.reg(a[1], w)
        return isa.encode(op, rd, rs, _word(imm, w, "immediate"))

    def finish(self) -> Image:
        img = Image()
        owner: dict[int, str] = {}

        def put(addr: int, val: int, where: str):
            if addr in owner:
                raise AsmError(
                    f"{where}: overlaps address {addr:#06x} already written at {owner[addr]}"
                )
            owner[addr] = where
            img.words[addr] = val

        for st in self.stmts:
            if st.kind == "instr":
                w0, w1 = self.encode(st)
                put(st.addr, w0, st.where)
                put(st.addr + 1, w1, st.where)
                img.lines[st.addr] = f"{st.where}  {st.source}"
            elif st.kind == "word":
                for k, e in enumerate(st.args):
                    put(
                        st.addr + k,
                        _word(e.eval(lambda n, e=e: self.lookup(n, e.where)), st.where),
                        st.where,
                    )
            elif st.kind == "string":
                for k, c in enumerate(st.args):
                    put(st.addr + k, c & 0xFFFF, st.where)
            elif st.kind == "zero":
                for k in range(st.args[0]):
                    put(st.addr + k, 0, st.where)
        for name in self.equs:
            self.lookup(name, self.equs[name].where)
        img.symbols = {k: v & 0xFFFF if v >= -0x8000 else v for k, v in self.symbols.items()}
        img.labels = {k for k in self.symbols if k not in self.equs}
        return img


_DIRECTIVES = {".org", ".equ", ".word", ".zero", ".string", ".ascii", ".include"}


def assemble(src: str, path: str = "<src>", origin: int = isa.CODE_BASE) -> Image:
    a = _Assembler()
    a.pc = origin
    a.source(src, path)
    return a.finish()


def assemble_file(path: str) -> Image:
    with open(path) as f:
        return assemble(f.read(), path)


if __name__ == "__main__":
    import sys

    from .disasm import listing

    img = assemble_file(sys.argv[1]) if len(sys.argv) > 1 else assemble(sys.stdin.read())
    print("\n".join(listing(img)))
