import random
import unittest
from concurrent.futures import ProcessPoolExecutor

import evolve
import tournament
import vm


def _run(pool, seed=3):
    hill = tournament.load_warriors(only=["dwarf", "imp", "stone"])
    (fit, genome, per), _, _, history = evolve.evolve(
        hill,
        generations=3,
        pop_size=10,
        rounds=2,
        seed=seed,
        max_cycles=2000,
        coevolve=0,
        elite=2,
        pool=pool,
        log=lambda *_: None,
    )
    return fit, genome.key(), per, [h["best"] for h in history]


class EvolveTest(unittest.TestCase):
    def test_operators_keep_genomes_legal(self):
        rng = random.Random(0)
        pop = [evolve.random_genome(rng) for _ in range(20)]
        for _ in range(500):
            g = evolve.mutate(rng.choice(pop), rng)
            if rng.random() < 0.5:
                g = evolve.crossover(g, rng.choice(pop), rng)
            self.assertTrue(1 <= len(g.code) <= evolve.MAXLEN)
            w = g.warrior("x")
            back = vm.parse_redcode(w.redcode())
            self.assertEqual((back.code, back.start), (w.code, w.start))
            pop[rng.randrange(len(pop))] = g

    def test_replay_is_independent_of_workers(self):
        serial = _run(None)
        with ProcessPoolExecutor(max_workers=3) as pool:
            parallel = _run(pool)
        self.assertEqual(serial, parallel)
        self.assertNotEqual(serial, _run(None, seed=4))

    def test_coevolution_grows_the_hill(self):
        hill = tournament.load_warriors(only=["imp"])
        _, final_hill, champs, _ = evolve.evolve(
            hill,
            generations=5,
            pop_size=6,
            rounds=1,
            seed=1,
            max_cycles=500,
            coevolve=2,
            elite=1,
            pool=None,
            log=lambda *_: None,
        )
        self.assertEqual([c.name for c in champs], ["gen2", "gen4"])
        self.assertEqual(len(final_hill), 3)


if __name__ == "__main__":
    unittest.main()
