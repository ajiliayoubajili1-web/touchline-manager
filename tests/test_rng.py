"""Tests for the deterministic seeded RNG."""

import unittest

from manager.rng import SeededRng, new_id


class SeededRngTest(unittest.TestCase):
    def test_same_seed_same_stream_identical(self):
        a = SeededRng(7)
        b = SeededRng(7)
        self.assertEqual(
            [a.randint(0, 100, "m") for _ in range(20)],
            [b.randint(0, 100, "m") for _ in range(20)],
        )

    def test_different_seeds_differ(self):
        a = SeededRng(1)
        b = SeededRng(2)
        self.assertNotEqual(
            [a.randint(0, 100, "m") for _ in range(5)],
            [b.randint(0, 100, "m") for _ in range(5)],
        )

    def test_streams_are_independent(self):
        a = SeededRng(5)
        first = a.randint(0, 100, "stream_one")
        # Drawing from a different stream must not change stream_one's sequence.
        a.randrange(0, 50, "stream_two")
        b = SeededRng(5)
        b.randint(0, 100, "stream_one")
        self.assertEqual(
            [a.randint(0, 100, "stream_one") for _ in range(8)],
            [b.randint(0, 100, "stream_one") for _ in range(8)],
        )
        self.assertTrue(first >= 0)

    def test_randint_inclusive_bounds(self):
        rng = SeededRng(9)
        for _ in range(500):
            value = rng.randint(3, 7, "x")
            self.assertTrue(3 <= value <= 7)

    def test_choice_and_shuffle(self):
        rng = SeededRng(3)
        pool = list(range(20))
        rng.shuffle(pool, "s")
        self.assertEqual(sorted(pool), list(range(20)))
        chosens = {rng.choice("abcdefghij", "c") for _ in range(400)}
        self.assertGreater(len(chosens), 1)

    def test_new_id_format(self):
        rng = SeededRng(2)
        ident = new_id("ply", rng)
        self.assertTrue(ident.startswith("ply_"))
        self.assertTrue(ident[4:].isdigit())

    def test_url_usable(self):
        # new_id output must be safe for drop-in string slots.
        rng = SeededRng(11)
        self.assertRegex(new_id("clb", rng), r"^clb_\d+$")


if __name__ == "__main__":
    unittest.main()