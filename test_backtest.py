import unittest

from backtest import FEE, INITIAL, SLIP, exit_price, open_position, signal, simulate
from prices import Candle, validate


def candle(hour, o=100, h=101, l=99, c=100):
    return Candle(hour * 3600, o, h, l, c, 10)


class ReplayTests(unittest.TestCase):
    def test_breakout_waits_for_next_open(self):
        bars = [candle(i) for i in range(20)] + [candle(20, h=110, c=108)]
        self.assertFalse(signal(bars, 20))
        self.assertTrue(signal(bars, 21))
        bars.append(candle(21, o=112, h=113, l=111, c=112))
        _, trades = simulate(bars, 0, len(bars))
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0]["entry"], 112 * (1 + SLIP))
        self.assertEqual(trades[0]["reason"], "period end")
        self.assertLess(trades[0]["pnl"], 0)

    def test_stop_wins_ambiguous_bar_and_gap_uses_open(self):
        p = open_position(candle(0), INITIAL)
        self.assertEqual(exit_price(p, candle(1, h=105, l=95), False), (p.stop, "stop"))
        self.assertEqual(exit_price(p, candle(1, o=95, l=94), False), (95, "gap stop"))

    def test_size_accounts_for_costs(self):
        p = open_position(candle(0), INITIAL)
        proceeds = p.quantity * p.stop * (1 - SLIP) * (1 - FEE)
        self.assertAlmostEqual(p.cost - proceeds, INITIAL * 0.005)
        self.assertLessEqual(p.cost, INITIAL)

    def test_gap_in_history_is_rejected(self):
        with self.assertRaises(ValueError):
            validate([candle(0), candle(2)])

    def test_flat_market_stays_in_cash(self):
        bars = [candle(i) for i in range(48)]
        summary, trades = simulate(bars, 0, len(bars))
        self.assertEqual(trades, [])
        self.assertEqual(summary["return_pct"], 0)
        self.assertIsNone(summary["win_pct"])


if __name__ == "__main__":
    unittest.main()
