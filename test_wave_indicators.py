import unittest

import numpy as np

from wave_indicators import indicator_series


class IndicatorTests(unittest.TestCase):
    def test_wilder_seed_and_next_update(self):
        # Fourteen changes with seven upward moves of 2 and seven losses of 1.
        changes = [2, -1] * 7 + [-3]
        prices = 100 + np.cumsum([0, *changes])
        rsi = indicator_series(prices)["rsi14"]
        self.assertTrue(np.isnan(rsi[:14]).all())
        self.assertAlmostEqual(rsi[14], 100 * 14 / 21)
        self.assertAlmostEqual(rsi[15], 100 * 13 / (13 + 6.5 + 3))

    def test_trend_extremes_and_constant_decimal_price(self):
        self.assertEqual(indicator_series(np.arange(1, 30))["rsi14"][-1], 100)
        self.assertEqual(indicator_series(np.arange(30, 0, -1))["rsi14"][-1], 0)
        result = indicator_series([0.12345] * 50)
        np.testing.assert_array_equal(result["rsi14"][14:], 50)
        np.testing.assert_array_equal(result["bb_percent_b"][19:], 0.5)
        np.testing.assert_array_equal(result["bb_bandwidth"][19:], 0)

    def test_population_bands_and_unclipped_breakout(self):
        result = indicator_series([100] * 19 + [120])
        # Mean=101; population variance=(19*1 + 19**2)/20=19.
        width = 4 * np.sqrt(19)
        self.assertAlmostEqual(result["bb_bandwidth"][-1], width / 101)
        self.assertAlmostEqual(result["bb_percent_b"][-1], 0.5 + 19 / width)
        self.assertGreater(result["bb_percent_b"][-1], 1)
        self.assertTrue(np.isnan(result["bb_percent_b"][:19]).all())

    def test_prefix_invariance_and_empty_input(self):
        prices = 100 + np.cos(np.arange(100) / 7) + np.arange(100) / 3
        full = indicator_series(prices)
        for cutoff in (0, 1, 14, 15, 19, 20, 25, 80):
            partial = indicator_series(prices[:cutoff])
            for key in full:
                np.testing.assert_array_equal(partial[key], full[key][:cutoff])

    def test_invalid_closes_raise(self):
        for prices in ([1, np.nan], [2, np.inf], [1, 0], [-1], [[1, 2]]):
            with self.subTest(prices=prices), self.assertRaises(ValueError):
                indicator_series(prices)
