import unittest
from datetime import date, timedelta

import numpy as np

import trend as T
import trend_improve as I


class TrendImproveTest(unittest.TestCase):
    def test_split_is_deterministic_and_disjoint(self):
        coins = [f"C{i}" for i in range(10)]
        a, b = I.split(coins)
        self.assertEqual((a, b), I.split(coins))
        self.assertEqual(sorted(a + b), sorted(coins))
        self.assertFalse(set(a) & set(b))

    def test_liquidity_uses_only_closes_through_the_day(self):
        c, v = np.ones(60), np.full(60, 2e6)
        before = I.liquid(c, v)
        v2 = v.copy()
        v2[45:] = 0
        after = I.liquid(c, v2)
        np.testing.assert_array_equal(before[:45], after[:45])
        self.assertFalse(before[28])
        self.assertTrue(before[29])

    def test_filters_zero_weights_without_touching_warmup(self):
        n = T.WARM + 50
        rng = np.random.default_rng(2)
        c = 100 * np.exp(np.cumsum(rng.normal(.002, .02, n)))
        dates = [date(2022, 1, 1) + timedelta(days=i) for i in range(n)]
        btc_off = {d: 0. for d in dates}
        base = I.weights(dates, c, np.full(n, 1e9), btc_off, "base")
        reg = I.weights(dates, c, np.full(n, 1e9), btc_off, "regime")
        liq = I.weights(dates, c, np.zeros(n), btc_off, "liquidity")
        self.assertTrue(np.isnan(reg[:T.WARM]).all())
        self.assertTrue((reg[T.WARM:] == 0).all())
        self.assertTrue((liq[T.WARM:] == 0).all())
        self.assertTrue((base[T.WARM:] > 0).any())


if __name__ == "__main__":
    unittest.main()
