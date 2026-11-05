import unittest

from vm import Battle, Insn, RedcodeError, battle, parse_redcode

IMP = "MOV 0, 1"
DWARF = """
;name dwarf
        ADD #4, 3
        MOV 2, @2
        JMP -2
        DAT #0, #0
"""
SUICIDE = "DAT #0, #0"


class ParseTest(unittest.TestCase):
    def test_labels_org_and_defaults(self):
        w = parse_redcode(
            """
            ;name looper
            ORG start
            bomb  DAT #0
            start: ADD #4, bomb
                   MOV bomb, @bomb
                   JMP start
            """
        )
        self.assertEqual(w.name, "looper")
        self.assertEqual(w.start, 1)
        self.assertEqual(w.code[0], Insn("DAT", "#", 0, "#", 0))
        self.assertEqual(w.code[1], Insn("ADD", "#", 4, "$", 3999))
        self.assertEqual(w.code[3], Insn("JMP", "$", 3998, "$", 0))

    def test_rejects_94(self):
        with self.assertRaises(RedcodeError):
            parse_redcode("MOV.I 0, 1")
        with self.assertRaises(RedcodeError):
            parse_redcode("MOV }0, 1")

    def test_roundtrip(self):
        w = parse_redcode(DWARF)
        self.assertEqual(parse_redcode(w.redcode()).code, w.code)


class VMTest(unittest.TestCase):
    def test_imp_crawls(self):
        b = Battle([parse_redcode(IMP)], maxcycles=10)
        b.run()
        for i in range(11):
            self.assertEqual(str(b.peek(i)), "MOV $0, $1")
        self.assertEqual(b.owner[10], 0)

    def test_dat_kills(self):
        r = battle([parse_redcode(IMP), parse_redcode(SUICIDE)], seed=3)
        self.assertEqual(r.winner, 0)
        self.assertEqual(r.cycles, 1)

    def test_dwarf_bombs_every_fourth(self):
        b = Battle([parse_redcode(DWARF)], maxcycles=30)
        b.run()
        # After 10 loops the dwarf has dropped DATs at 7, 11, 15, ...
        self.assertEqual(b.peek(7).op, "DAT")
        self.assertEqual(b.peek(11).op, "DAT")
        self.assertEqual(b.peek(8).op, "DAT")  # untouched empty core is DAT too
        self.assertEqual(b.owner[7], 0)
        self.assertEqual(b.owner[8], -1)

    def test_predecrement_and_djn(self):
        b = Battle([parse_redcode("loop DJN loop, #3\nDAT 0")], maxcycles=10)
        b.run()
        self.assertFalse(b.alive[0])
        self.assertEqual(b.cycle, 4)

    def test_spl_respects_maxproc(self):
        b = Battle([parse_redcode("SPL 0\nJMP -1")], maxcycles=500, maxproc=8)
        b.run()
        self.assertLessEqual(len(b.queues[0]), 8)

    def test_cmp_skips_when_equal(self):
        b = Battle([parse_redcode("CMP 3, 4\nDAT 0\nJMP 0\nDAT 1\nDAT 1")], maxcycles=5)
        b.run()
        self.assertTrue(b.alive[0])

    def test_imp_vs_dwarf_is_deterministic(self):
        ws = [parse_redcode(IMP), parse_redcode(DWARF)]
        self.assertEqual(battle(ws, seed=7), battle(ws, seed=7))


if __name__ == "__main__":
    unittest.main()
