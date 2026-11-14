import itertools
import random

import pytest
from rtosaurus import isa
from rtosaurus.asm import AsmError, assemble
from rtosaurus.disasm import disasm, listing


def words(img, start=isa.CODE_BASE):
    return [img.words[a] for a in range(start, start + len(img.words))]


def test_basic_encoding_and_labels():
    img = assemble(
        """
        start:  LDI r1, 42        ; comment
                ADD r1, r2
        loop:   JNZ loop
                ld r3, [r2+4]
                ST [sp-1], r3
                LD r0, [MMIO_ADC_TEMP]
                HALT
        """
    )
    b = isa.CODE_BASE
    assert img.symbols["start"] == b and img.symbols["loop"] == b + 4
    assert (img.words[b], img.words[b + 1]) == isa.encode("LDI", 1, 0, 42)
    assert (img.words[b + 4], img.words[b + 5]) == isa.encode("JNZ", imm=b + 4)
    assert (img.words[b + 6], img.words[b + 7]) == isa.encode("LD", 3, 2, 4)
    assert (img.words[b + 8], img.words[b + 9]) == isa.encode("ST", 7, 3, 0xFFFF)
    assert (img.words[b + 10], img.words[b + 11]) == isa.encode(
        "LD", 0, isa.ZERO_BASE, isa.MMIO_ADC_TEMP
    )
    assert img.lines[b].endswith("start:  LDI r1, 42        ; comment")
    assert img.lines[b].startswith("<src>:2")


def test_forward_refs_equ_and_expressions():
    img = assemble(
        """
        .equ N, SIZE * 2 + (1 << 3)
        .equ SIZE, 5
                CALL fn
                LDI r0, N
                LDI r1, -3
                LDI r2, 'a'
                LDI r3, '\\n'
                LDI r4, 0b101 | 0x10
                LDI r5, end - fn
                LDI r6, ~0 & 0xFF
                LDI r0, 7 / 2 - -1
        fn:     RET
        end:
        """
    )
    b = isa.CODE_BASE
    imms = [img.words[b + 1 + 2 * i] for i in range(10)]
    assert imms == [img.symbols["fn"], 18, 0xFFFD, 97, 10, 0x15, 2, 255, 4, 0]
    assert img.symbols["N"] == 18


def test_data_directives_and_org():
    img = assemble(
        """
        .org 0
        .word reset, 0, 7
        .org 0x100
        reset: HALT
        msg:   .string "hi\\n"
        buf:   .zero 3
        tail:  .word msg, 'x', -1
        """
    )
    assert [img.words[i] for i in range(3)] == [0x100, 0, 7]
    m = img.symbols["msg"]
    assert [img.words[m + i] for i in range(4)] == [104, 105, 10, 0]
    assert img.symbols["buf"] == m + 4 and img.symbols["tail"] == m + 7
    assert [img.words[m + 4 + i] for i in range(3)] == [0, 0, 0]
    assert [img.words[m + 7 + i] for i in range(3)] == [m, 120, 0xFFFF]
    assert "reset" in img.labels and "msg" in img.labels


def test_include(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.s").write_text('.include "c.s"\nb: RET\n')
    (tmp_path / "sub" / "c.s").write_text(".equ C, 3\n")
    (tmp_path / "a.s").write_text('a: CALL b\n.include "sub/b.s"\nLDI r0, C\n')
    from rtosaurus.asm import assemble_file

    img = assemble_file(str(tmp_path / "a.s"))
    assert img.symbols["b"] == isa.CODE_BASE + 2 and img.symbols["C"] == 3
    assert "b.s:2" in img.lines[isa.CODE_BASE + 2]


@pytest.mark.parametrize(
    "src, msg",
    [
        ("FOO r1", "unknown mnemonic"),
        ("LDI r1", "operand"),
        ("JMP nowhere", "undefined symbol nowhere"),
        ("x: NOP\nx: NOP", "duplicate symbol x"),
        ("LDI r9, 1", "expected register"),
        ("MOV r1, 5", "expected register"),
        ("LDI r0, 70000", "16 bits"),
        (".equ A, B\n.equ B, A\nLDI r0, A", "circular"),
        (".org 0x20\nNOP\n.org 0x20\nNOP", "overlaps"),
        (".bogus 1", "unknown directive"),
        ('.include "missing.s"', "cannot include"),
        ("LD r1, r2", "memory operand"),
        ("LDI r0, (1 + 2", "missing ')'"),
        (".equ MMIO_HALT, 1", "shadows"),
    ],
)
def test_errors_have_location(src, msg):
    with pytest.raises(AsmError) as e:
        assemble("NOP\n" + src, "t.s")
    assert msg in str(e.value)
    assert str(e.value).startswith("t.s:")


def _operand_samples(form):
    regs = range(8)
    imms = [0, 1, 0x7FFF, 0x8000, 0xFFFF, 0x1234]
    if form == "":
        yield 0, 0, 0
    elif form == "rd,rs":
        yield from ((d, s, 0) for d, s in itertools.product(regs, regs))
    elif form == "rd,imm":
        yield from ((d, 0, i) for d in regs for i in imms)
    elif form == "rd":
        yield from ((d, 0, 0) for d in regs)
    elif form in ("rs",):
        yield from ((0, s, 0) for s in regs)
    elif form == "imm":
        yield from ((0, 0, i) for i in imms)
    elif form == "rs,imm":
        yield from ((0, s, i) for s in regs for i in imms)
    elif form == "mem_ld":
        yield from ((d, s, i) for d in regs for s in [*regs, isa.ZERO_BASE] for i in imms)
    elif form == "mem_st":
        yield from ((d, s, i) for d in [*regs, isa.ZERO_BASE] for s in regs for i in imms)


@pytest.mark.parametrize("op", sorted(isa.OPCODES))
def test_disasm_roundtrip_every_opcode(op):
    form = isa.OPCODES[op][1]
    syms = {"here": 0x1234, "zero_lbl": 0}
    for rd, rs, imm in _operand_samples(form):
        w0, w1 = isa.encode(op, rd, rs, imm)
        for s in (None, syms):
            text = disasm(w0, w1, s)
            img = (
                assemble(text + "\nhere_: NOP", origin=0x40)
                if s is None
                else assemble(f".equ here, 0x1234\n.equ zero_lbl, 0\n{text}", origin=0x40)
            )
            assert (img.words[0x40], img.words[0x41]) == (w0, w1), (op, rd, rs, imm, text)


def test_disasm_random_words_roundtrip():
    rng = random.Random(3)
    for _ in range(3000):
        w0, w1 = rng.randrange(0x10000), rng.randrange(0x10000)
        text = disasm(w0, w1)
        img = assemble(text, origin=0x40)
        assert (img.words[0x40], img.words[0x41]) == (w0, w1), text


def test_disasm_pretty():
    syms = {"loop": 0x20}
    assert disasm(*isa.encode("JMP", imm=0x20), syms) == "JMP loop"
    assert (
        disasm(*isa.encode("LD", 1, isa.ZERO_BASE, isa.MMIO_ADC_TEMP)) == "LD r1, [MMIO_ADC_TEMP]"
    )
    assert disasm(*isa.encode("ST", 7, 2, 0xFFFF)) == "ST [sp-1], r2"
    assert disasm(*isa.encode("ADDI", 7, 0, 0xFFFE)) == "ADDI sp, -2"
    assert disasm(0xEE00, 0).startswith(".word")


def test_firmware_assembles():
    import os

    from rtosaurus.asm import assemble_file

    main = os.path.join(os.path.dirname(__file__), "..", "firmware", "main.s")
    if not os.path.exists(os.path.join(os.path.dirname(main), "app.s")):
        pytest.skip("firmware/app.s not written yet")
    img = assemble_file(main)
    assert img.words[isa.VEC_RESET] == img.symbols["reset"]
    for name in ("k_tcb", "k_current", "k_ticks", "task_table", "app_init"):
        assert name in img.symbols
    assert listing(img)
