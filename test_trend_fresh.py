import unittest
from datetime import date
from unittest import mock

import numpy as np

import trend as T
import trend_fresh as F

DAY = T.DAY_MS


def rows(n, start=0, gap_at=None, bad_at=None):
    out, t = [], start
    for i in range(n):
        if i == gap_at:
            t += DAY
        p = 100 + i
        r = (t, p, p + 2, p - 2, p + 1, 10.)
        if i == bad_at:
            r = (t, p, p - 5, p - 2, p + 1, 10.)
        out.append(r)
        t += DAY
    return out


class TrendFreshTest(unittest.TestCase):
    def test_universe_filter(self):
        for s in ("AVAXUSDT", "PAXGUSDT", "DOTUSDT"):
            self.assertTrue(F.eligible(s))
        for s in ("BTCUSDT", "USDCUSDT", "EURUSDT", "BTCUPUSDT", "ETHBEARUSDT", "AVAXBTC", "X-YUSDT", "币安人生USDT"):
            self.assertFalse(F.eligible(s), s)

    def test_candles_stop_at_first_gap_or_bad_row(self):
        with mock.patch.object(T, "month_rows", return_value=rows(50, gap_at=30)):
            self.assertEqual(len(F.candles("X", [(2020, 1)])), 30)
        with mock.patch.object(T, "month_rows", return_value=rows(50, bad_at=20)):
            self.assertEqual(len(F.candles("X", [(2020, 1)])), 20)

    def test_sleeves_align_days_and_need_a_year(self):
        rng = np.random.default_rng(1)
        n = T.WARM + 1 + 400
        c = 100 * np.exp(np.cumsum(rng.normal(0, .03, n)))
        a = np.column_stack([np.arange(n) * DAY, np.r_[c[0], c[:-1]], c * 1.01, c * .99, c, np.ones(n)])
        a[:, 2] = np.maximum(a[:, 2], a[:, 1])
        a[:, 3] = np.minimum(a[:, 3], a[:, 1])
        s = F.sleeves(a)
        self.assertEqual(len(s["days"]), len(s["trend"]["ret"]))
        self.assertEqual(len(s["days"]), len(s["bh"]["ret"]))
        self.assertEqual(s["days"][0], T.day(a[T.WARM + 1, 0]))
        self.assertIsNone(F.sleeves(a[:T.WARM + 100]))

    def test_basket_averages_only_live_coins(self):
        d1, d2 = date(2022, 1, 1), date(2022, 1, 2)
        daily = {d1: {"trend": [.02], "bh": [.04]}, d2: {"trend": [.01, .03], "bh": [0., .02]}}
        days, b = F.basket(daily)
        self.assertEqual(days, [d1, d2])
        np.testing.assert_allclose(b["trend"], [.02, .02])
        np.testing.assert_allclose(b["bh"], [.04, .01])

    def test_sign_test(self):
        self.assertAlmostEqual(F.sign_p(10, 10), 1 / 1024)
        self.assertAlmostEqual(F.sign_p(0, 4), 1.)


if __name__ == "__main__":
    unittest.main()
