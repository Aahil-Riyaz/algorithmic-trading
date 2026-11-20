import unittest

import numpy as np

import trend_tpsl as S


def market(path, warm=20):
    """Flat warm-up candles with a 2-point range (ATR 2), then (open, high, low, close) rows from path."""
    rows = [(100, 101, 99, 100)] * warm + list(path)
    o, h, l, c = (np.array(x, float) for x in zip(*rows))
    return o, h, l, c


def signal(n, on_from, off_from=None):
    s = np.full(n, 0.)
    s[on_from:] = 1.
    if off_from is not None:
        s[off_from:] = 1 / 3
    return s


class TrendTpslTest(unittest.TestCase):
    def setUp(self):
        self.saved = S.COST, S.BORROW
        S.COST = S.BORROW = 0.

    def tearDown(self):
        S.COST, S.BORROW = self.saved

    def test_half_at_tp1_then_trailing_stop(self):
        # Entry 100, ATR 2 -> stop 96, R 4, TP1 104. The close of 110 trails the stop to 106.
        o, h, l, c = market([(100, 101, 99, 100), (100, 105, 99, 104), (104, 111, 103, 110), (110, 110, 105, 106)])
        s = S.simulate(o, h, l, c, signal(len(c), 19))
        t = s["trades"][0]
        self.assertEqual(t["exits"], "tp1+trail")
        self.assertAlmostEqual(t["r"], (.5 * 4 + .5 * 6) / 4)

    def test_without_breakeven_the_runner_keeps_the_initial_stop(self):
        # TP1 fills at 104 and the day closes at 102, so the 2-ATR trail sits at 98. Base lifts the stop to the entry
        # and is stopped by the dip to 99.5; without breakeven the runner survives on the trail at 98.
        path = [(100, 101, 99, 100), (100, 105, 99, 102), (102, 102, 99.5, 100), (100, 104, 99.5, 103)]
        o, h, l, c = market(path)
        base = S.simulate(o, h, l, c, signal(len(c), 19))
        loose = S.simulate(o, h, l, c, signal(len(c), 19), breakeven=False)
        self.assertEqual(base["trades"][0]["exits"], "tp1+trail")
        self.assertEqual(loose["trades"], [])

    def test_stop_first_and_sizing_risk(self):
        o, h, l, c = market([(100, 105, 95, 98)])
        s = S.simulate(o, h, l, c, signal(len(c), 19))
        self.assertEqual(s["trades"][0]["exits"], "stop")
        self.assertAlmostEqual(s["trades"][0]["r"], -1)
        self.assertAlmostEqual(s["eq"][-1], S.T.CAPITAL * (1 - S.RISK))

    def test_trend_exit_at_next_open_and_risk_sizing(self):
        o, h, l, c = market([(100, 101, 99.5, 100.5), (101, 101.5, 100, 101), (102, 102, 101, 101.5)])
        s = S.simulate(o, h, l, c, signal(len(c), 19, off_from=21))
        self.assertEqual(s["trades"][0]["exits"], "trend")
        # 2% risk over a 4-point stop buys 50 units at 100, well under the 2x cap.
        self.assertAlmostEqual(s["held"][20], 50 * 100.5 / (5000 + 50 * 100.5))

    def test_decision_ignores_later_data(self):
        o, h, l, c = market([(100, 101, 99, 100)] * 5)
        sig = signal(len(c), 19)
        a = S.simulate(o, h, l, c, sig)
        c2 = c.copy()
        c2[-1] = 500
        b = S.simulate(o, h, l, c2, sig)
        np.testing.assert_allclose(a["eq"][:-1], b["eq"][:-1])

    def test_sharpe_interval_brackets_point(self):
        r = np.random.default_rng(0).normal(.001, .02, 800)
        x = S.sharpe_interval(r)
        self.assertLess(x["lo"], x["point"])
        self.assertGreater(x["hi"], x["point"])


if __name__ == "__main__":
    unittest.main()
