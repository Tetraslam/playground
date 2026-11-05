import unittest

import viz
import vm


class TestViz(unittest.TestCase):
    def test_writelog_sees_identical_rewrites(self):
        imp = vm.parse_redcode("MOV $0, $1", "imp")
        battle = vm.Battle([imp], seed=0)
        painter = viz.Painter(battle)
        for _ in range(10):
            battle.step()
        # The imp rewrites MOV 0,1 onto cells; every hop is stamped.
        self.assertEqual(painter.log.stamp[1:11], list(range(10)))
        self.assertEqual(battle.owner[5], 0)

    def test_colors_and_png(self):
        import tempfile
        from pathlib import Path

        ws = [
            vm.parse_redcode("MOV $0, $1", "imp"),
            vm.parse_redcode("ADD #4, $3\nMOV $2, @2\nJMP $-2\nDAT #0", "dwarf"),
        ]
        battle = vm.Battle(ws, seed=1)
        painter = viz.Painter(battle)
        for _ in range(200):
            battle.step()
        colors = painter.colors()
        self.assertEqual(len(colors), vm.CORESIZE)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "x.png"
            viz.write_png(out, viz.core_image(painter, 100, 4))
            self.assertTrue(out.read_bytes().startswith(b"\x89PNG"))

    def test_evolution_plot(self):
        gen = lambda i, hill: {
            "gen": i,
            "best": 2.0,
            "mean": 1.0,
            "hill": ["a"] * hill,
            "ops": {"SPL": 0.5, "DAT": 0.5},
        }
        img = viz.evolution({"generations": [gen(0, 1), gen(1, 2)]}, colw=3)
        self.assertEqual(len(img[0]), 6)
        self.assertEqual(img[0][0], viz.OP_COLORS["DAT"])  # DAT stacks first
        self.assertEqual(img[239][0], viz.OP_COLORS["SPL"])


if __name__ == "__main__":
    unittest.main()
