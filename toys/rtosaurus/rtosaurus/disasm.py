"""T16 disassembler (owner: agent 3).

`disasm(w0, w1, symbols)` renders one instruction in syntax the assembler
accepts, so `assemble(disasm(w0, w1))` reproduces the same two words.
Jump/call targets and absolute memory operands are shown as symbols when one
matches exactly (user labels first, then MMIO_* names for memory operands).
"""

from __future__ import annotations

from . import isa

_JUMPS = {"JMP", "JZ", "JNZ", "JLT", "JGE", "JGT", "JLE", "JC", "JNC", "CALL"}
_MMIO = {
    v: k for k, v in sorted(isa.mmio_constants().items(), reverse=True) if k.startswith("MMIO_")
}


def _reverse(symbols: dict[str, int] | None) -> dict[int, str]:
    if not symbols:
        return {}
    rev: dict[int, str] = {}
    # deterministic: shortest, then alphabetical name wins for a given value
    for name, val in sorted(symbols.items(), key=lambda kv: (len(kv[0]), kv[0])):
        rev.setdefault(val & 0xFFFF, name)
    return rev


_cache: tuple[int, dict[int, str]] | None = None


def _rev_cached(symbols: dict[str, int] | None) -> dict[int, str]:
    global _cache
    if symbols is None:
        return {}
    key = id(symbols)
    if _cache is None or _cache[0] != key or len(_cache[1]) > len(symbols):
        _cache = (key, _reverse(symbols))
    return _cache[1]


def _signed(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


def _num(v: int) -> str:
    s = _signed(v)
    return str(s) if -256 <= s <= 256 else f"0x{v:04X}"


def _reg(n: int) -> str:
    return "sp" if n == isa.SP else f"r{n}"


def disasm(w0: int, w1: int, symbols: dict[str, int] | None = None) -> str:
    name, rd, rs, imm = isa.decode(w0 & 0xFFFF, w1 & 0xFFFF)
    rev = _rev_cached(symbols)
    if name is None:
        return f".word 0x{w0 & 0xFFFF:04X}, 0x{w1 & 0xFFFF:04X}"
    form = isa.OPCODES[name][1]

    def target(v: int) -> str:
        return rev.get(v) or f"0x{v:04X}"

    def mem(base: int, off: int) -> str:
        if base == isa.ZERO_BASE:
            return f"[{rev.get(off) or _MMIO.get(off) or f'0x{off:04X}'}]"
        s = _signed(off)
        if s == 0:
            return f"[{_reg(base)}]"
        return f"[{_reg(base)}{'+' if s > 0 else '-'}{abs(s)}]"

    # anything an assembler cannot express (stray fields, illegal regs) -> raw words
    used_rd = form in ("rd,rs", "rd,imm", "rd", "mem_ld", "mem_st")
    used_rs = form in ("rd,rs", "rs", "rs,imm", "mem_ld", "mem_st")
    used_imm = form in ("rd,imm", "imm", "rs,imm", "mem_ld", "mem_st")
    bad = (
        (not used_rd and rd)
        or (not used_rs and rs)
        or (not used_imm and imm)
        or (rd > 7 and not (form == "mem_st" and rd == isa.ZERO_BASE))
        or (rs > 7 and not (form == "mem_ld" and rs == isa.ZERO_BASE))
    )
    if bad:
        return f".word 0x{w0 & 0xFFFF:04X}, 0x{w1 & 0xFFFF:04X}  ; {name}?"

    if form == "":
        return name
    if form == "rd,rs":
        return f"{name} {_reg(rd)}, {_reg(rs)}"
    if form == "rd,imm":
        if name == "LDI" and imm in rev and imm >= isa.CODE_BASE:
            return f"{name} {_reg(rd)}, {rev[imm]}"
        return f"{name} {_reg(rd)}, {_num(imm)}"
    if form == "rd":
        return f"{name} {_reg(rd)}"
    if form == "rs":
        return f"{name} {_reg(rs)}"
    if form == "imm":
        return f"{name} {target(imm)}" if name in _JUMPS else f"{name} {_num(imm)}"
    if form == "rs,imm":
        return f"{name} {_reg(rs)}, {_num(imm)}"
    if form == "mem_ld":
        return f"{name} {_reg(rd)}, {mem(rs, imm)}"
    if form == "mem_st":
        return f"{name} {mem(rd, imm)}, {_reg(rs)}"
    raise AssertionError(form)


def listing(image, start: int | None = None, end: int | None = None) -> list[str]:
    """Human listing of an assembled Image: instructions where the assembler
    emitted them, raw `.word`s elsewhere, labels on their own lines."""
    lines: list[str] = []
    labels: dict[int, list[str]] = {}
    for name in sorted(getattr(image, "labels", None) or image.symbols):
        labels.setdefault(image.symbols[name], []).append(name)
    addrs = sorted(image.words)
    if start is not None:
        addrs = [a for a in addrs if a >= start]
    if end is not None:
        addrs = [a for a in addrs if a < end]
    skip = set()
    for a in addrs:
        if a in skip:
            continue
        for lab in labels.get(a, []):
            lines.append(f"{lab}:")
        w0 = image.words[a]
        if a in image.lines:
            w1 = image.words.get(a + 1, 0)
            skip.add(a + 1)
            src = image.lines[a].split("  ", 1)[0]
            lines.append(
                f"  {a:04X}: {w0:04X} {w1:04X}  {disasm(w0, w1, image.symbols):<28} ; {src}"
            )
        else:
            ch = f"  '{chr(w0)}'" if 32 <= w0 < 127 else ""
            lines.append(f"  {a:04X}: {w0:04X}       .word 0x{w0:04X}{ch}")
    return lines


if __name__ == "__main__":
    import sys

    words = [int(x, 16) for x in sys.argv[1:]]
    for i in range(0, len(words) - 1, 2):
        print(disasm(words[i], words[i + 1]))
