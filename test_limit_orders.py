import unittest
from types import SimpleNamespace

from backtest import FEE, SLIP
from limit_orders import Setup, resolve, setup
from test_backtest import candle
from train_limits import Example, Model, replay


class LimitTests(unittest.TestCase):
    order = Setup(100, 99, 102, (1, 1))

    def test_touch_expires(self):
        bars = [candle(i, 101, 103, 100, 102) for i in range(2)]
        self.assertEqual(resolve(self.order, bars, 0).reason, "expired")

    def test_entry_candle_cannot_claim_an_earlier_high(self):
        bars = [candle(0, 101, 105, 99.5, 101), candle(1, 101, 103, 98, 100)]
        outcome = resolve(self.order, bars, 0)
        self.assertEqual((outcome.end, outcome.reason), (1, "stop"))
        self.assertAlmostEqual(outcome.price, 99 * (1 - SLIP))

    def test_gap_through_stop(self):
        bars = [candle(0, 101, 101, 99.5, 100), candle(1, 97, 100, 96, 99)]
        self.assertAlmostEqual(resolve(self.order, bars, 0).price, 97 * (1 - SLIP))

    def test_profit_target_pays_net_one_and_a_half_r(self):
        bars = [candle(i) for i in range(24)]
        order = setup(bars, 24)
        cost = order.limit * (1 + FEE)
        risk = cost - order.stop * (1 - SLIP) * (1 - FEE)
        self.assertAlmostEqual(order.target * (1 - FEE) - cost, 1.5 * risk)

    def test_pending_orders_block_duplicate_entries(self):
        result = SimpleNamespace(end=3, fill=None, price=None, reason="expired")
        rows = [Example("BTC", i, self.order, result) for i in (2, 3)]
        self.assertEqual(len(replay(rows, Model([], {}, 1), 0.5)), 1)
