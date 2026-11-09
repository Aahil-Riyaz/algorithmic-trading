import unittest

from waves import wave_side


class WaveTests(unittest.TestCase):
    closes = [105, 103, 100, 103, 107, 110, 108, 106, 105, 106, 107]

    def test_waits_for_two_confirming_closes(self):
        self.assertEqual(wave_side(self.closes[:-1], 2), 0)
        self.assertEqual(wave_side(self.closes, 2), 1)

    def test_mirrors_and_scales(self):
        self.assertEqual(wave_side([220 - p for p in self.closes], 2), -1)
        self.assertEqual(wave_side([3*p for p in self.closes], 6), 1)

    def test_small_impulse_and_stale_pivots_are_skipped(self):
        self.assertEqual(wave_side(self.closes, 6), 0)
        self.assertEqual(wave_side(self.closes + [107]*8, 2), 0)
