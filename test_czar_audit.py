import unittest

from discord_market import Bar

import czar_audit as C

ALERT = dict(side="LONG", entry="100", stop="90", tp1="103", tp2="106", tp3="112", tp4="118")


def bars(path):
    """Minute bars from (low, high) pairs; open and close sit mid-range. The first bar is the alert minute."""
    return [Bar(i * 60, (l + h) / 2, h, l, (l + h) / 2) for i, (l, h) in enumerate(path)]


class CzarAuditTest(unittest.TestCase):
    def setUp(self):
        self.costs = C.MAKER, C.TAKER, C.SLIP
        C.MAKER = C.TAKER = C.SLIP = 0.

    def tearDown(self):
        C.MAKER, C.TAKER, C.SLIP = self.costs

    def test_four_targets_average_their_r(self):
        b = bars([(104, 106), (99, 101), (100, 104), (105, 119)])
        r = C.replay(b, 0, ALERT, 0)
        self.assertEqual(r["status"], "TP4")
        self.assertAlmostEqual(r["r"], (.3 + .6 + 1.2 + 1.8) / 4)

    def test_tp1_then_stop_loses(self):
        b = bars([(104, 106), (99, 101), (100, 104), (89, 100)])
        r = C.replay(b, 0, ALERT, 0)
        self.assertEqual((r["status"], r["best_tp"]), ("SL", 1))
        self.assertAlmostEqual(r["r"], (.3 - 3) / 4)

    def test_stop_wins_a_shared_minute_and_breakeven_moves_it(self):
        b = bars([(104, 106), (99, 101), (89, 104)])
        self.assertEqual(C.replay(b, 0, ALERT, 0)["status"], "SL")
        b = bars([(104, 106), (99, 101), (100, 104), (99.5, 101)])
        self.assertEqual(C.replay(b, 0, ALERT, 0, breakeven=True)["status"], "BE")

    def test_trim_half_at_tp1_then_trailing_stop(self):
        b = bars([(104, 106), (99, 101), (100, 107), (102.5, 104)])
        r = C.replay(b, 0, ALERT, 0, weights=(.5, 1 / 6, 1 / 6, 1 / 6), trail="step")
        self.assertEqual((r["status"], r["best_tp"]), ("TRAIL", 2))
        self.assertAlmostEqual(r["r"], .5 * .3 + .6 / 6 + 2 * .3 / 6)

    def test_scaled_geometry_keeps_r_multiples(self):
        s = C.scaled(ALERT, 200)
        self.assertAlmostEqual((float(s["tp1"]) - float(s["entry"])) / (float(s["entry"]) - float(s["stop"])), .3)

    def test_unfilled_limit_expires_but_market_entry_fills(self):
        b = bars([(104, 106)] * (C.VALID // 60 + 3))
        self.assertEqual(C.replay(b, 0, ALERT, 0)["status"], "expired")
        self.assertTrue(C.replay(b, 0, ALERT, 0, market=True)["fill_utc"])


if __name__ == "__main__":
    unittest.main()
