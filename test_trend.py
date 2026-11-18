import unittest

import numpy as np

from trend import BAND, CAPITAL, FEE, SLIP, WARM, bootstrap, norm_ts, scale, signal, simulate, targets, validate


def walk(n=400, seed=1, sig=.03):
    return 100 * np.exp(np.cumsum(np.random.default_rng(seed).normal(.001, sig, n)))


class TrendTests(unittest.TestCase):
    def test_no_lookahead(self):
        c = walk()
        for rule in ("trend", "vt", "bh"):
            w = targets(c, rule)
            t = 300
            d = c.copy()
            d[t + 1:] *= 3
            np.testing.assert_array_equal(w[:t + 1], targets(d, rule)[:t + 1])
        o = c * 1.001
        w, o2, c2 = targets(c, "trend"), o.copy(), d.copy()
        o2[t + 1:] *= 3
        a, b = simulate(o, c, w), simulate(o2, c2, w)  # same weights, future prices differ
        np.testing.assert_array_equal(a["eq"][:t + 1], b["eq"][:t + 1])
        self.assertEqual([x for x in a["trades"] if x[0] <= t], [x for x in b["trades"] if x[0] <= t])

    def test_trade_uses_prior_close_weight_at_next_open(self):
        c = np.full(200, 100.)
        o = np.full(200, 100.)
        w = np.full(200, np.nan)
        w[WARM] = 1.
        w[WARM + 1:] = 1.
        s = simulate(o, c, w)
        self.assertEqual(s["trades"][0][0], WARM + 1)  # decided at close WARM, traded at open WARM+1
        self.assertEqual(s["held"][WARM], 0.)

    def test_rebalance_band(self):
        n = 200
        o = c = np.full(n, 100.)
        w = np.full(n, np.nan)
        w[WARM:] = .5
        w[WARM + 3] = .5 + BAND - 1e-3
        w[WARM + 6] = .5 + BAND + .05
        w[WARM + 7:] = .6 + BAND
        s = simulate(o, c, w)
        days = [i for i, _ in s["trades"]]
        self.assertIn(WARM + 1, days)
        self.assertNotIn(WARM + 4, days)  # change of just under 0.10 is ignored
        self.assertIn(WARM + 7, days)  # 0.15 beyond the held weight triggers a trade

    def test_fee_math(self):
        n = 200
        o = c = np.full(n, 100.)
        w = np.full(n, np.nan)
        w[WARM:] = .5
        s = simulate(o, c, w)
        d = CAPITAL * .5
        self.assertAlmostEqual(s["trades"][0][1], d)
        self.assertAlmostEqual(s["fees"], d * FEE)
        self.assertAlmostEqual(s["slip"], d * SLIP)
        self.assertAlmostEqual(s["eq"][-1], CAPITAL - d * (FEE + SLIP))
        w[:] = np.where(np.isnan(w), np.nan, 1.)
        s = simulate(o, c, w)  # full investment is capped so cash never goes negative
        self.assertAlmostEqual(s["eq"][-1], CAPITAL - CAPITAL / (1 + FEE + SLIP) * (FEE + SLIP))
        self.assertGreaterEqual(s["held"][-1], .9999)

    def test_vol_scale_is_capped_at_one(self):
        self.assertTrue((scale(walk(sig=.001))[30:] == 1.).all())
        s = scale(walk(sig=.06))[30:]
        self.assertTrue(((s > 0) & (s < 1)).all())
        self.assertEqual(scale(np.full(60, 100.))[-1], 1.)
        w = targets(walk(), "trend")
        self.assertTrue(np.nanmax(w) <= 1 and np.nanmin(w) >= 0)

    def test_signal_levels(self):
        s = signal(walk(1000, 5))
        self.assertTrue(np.isnan(s[:120]).all())
        self.assertTrue(set(np.unique(s[120:])) <= {0, 1 / 3, 2 / 3, 1})
        self.assertEqual(signal(np.arange(1., 300.))[-1], 1.)
        self.assertEqual(signal(np.arange(300., 1., -1.))[-1], 0.)

    def test_timestamp_units(self):
        self.assertEqual(norm_ts("1735689600000"), 1735689600000)
        self.assertEqual(norm_ts("1735689600000000"), 1735689600000)

    def test_validation_and_bootstrap(self):
        t = np.arange(5) * 86_400_000. + 1_514_764_800_000
        a = np.column_stack([t, [10.] * 5, [11.] * 5, [9.] * 5, [10.] * 5, [1.] * 5])
        validate(a)
        for bad in (np.delete(a, 2, 0), np.where(np.arange(5)[:, None] == 1, a * [1, 1, .5, 1, 1, 1], a)):
            with self.assertRaises(ValueError):
                validate(bad)
        r = np.random.default_rng(2).normal(.001, .02, 500)
        x, y = bootstrap(r, r, n=200), bootstrap(r, r * .5, n=200)
        self.assertEqual((x["lo"], x["hi"]), (0., 0.))
        self.assertEqual(bootstrap(r, r * .5, n=200), y)  # fixed seed
        self.assertLess(y["lo"], y["point"] + 1e-9)


if __name__ == "__main__":
    unittest.main()
