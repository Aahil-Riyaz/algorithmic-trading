import unittest
from types import SimpleNamespace

from backtest import SLIP
from flow_replay import replay, summary
from perp_market import Funding
from perp_orders import HORIZON, Order, funding_payments, make_order, resolve, trade_pnl
from prices import Candle


def bar(i, low=99.5, high=100.5, opening=100.0, close=100.0):
    return Candle(i * 300, opening, high, low, close, 1)


def market():
    return SimpleNamespace(bars=[bar(i) for i in range(HORIZON + 1)], funding=[], funding_times=[])


class OrderTests(unittest.TestCase):
    def test_stop_and_target_geometry_both_sides(self):
        for side in (-1, 1):
            o = make_order(side, 100, 1, 92, 109)
            self.assertGreater((o.entry - o.stop) * side, 2)
            self.assertAlmostEqual(trade_pnl(side, o.entry, o.stop * (1 - side * SLIP)), -o.risk)
            self.assertAlmostEqual(trade_pnl(side, o.entry, o.target), 1.5 * o.risk)
            self.assertEqual(o.stop, 91.75 if side == 1 else 109.25)

    def test_short_touch_expires_and_penetration_fills(self):
        m = market()
        o = Order(-1, 100.5, 103, 97, 3)
        self.assertEqual(resolve(m, o, 0).reason, "expired")
        m.bars[23] = bar(23, high=100.51)
        m.bars[24] = bar(24, low=96)
        result = resolve(m, o, 0)
        self.assertEqual((result.fill, result.end, result.price), (23, 24, 97))

    def test_both_sides_take_adverse_path_and_gap_slippage(self):
        for side in (1, -1):
            m = market()
            o = Order(side, 100, 100 - side * 2, 100 + side * 3, 2.2)
            m.bars[0] = bar(0, low=97, high=104)
            result = resolve(m, o, 0)
            self.assertEqual((result.reason, result.end), ("stop", 0))
            m.bars[0] = bar(0)
            m.bars[1] = bar(1, low=93, high=107, opening=100 - side * 6)
            result = resolve(m, o, 0)
            self.assertAlmostEqual(result.price, (100 - side * 6) * (1 - side * SLIP))

    def test_debits_and_credits_respect_event_time_and_direction(self):
        m = market()
        m.funding = [Funding(i * 300_000 + 2, 0.01, 100) for i in range(5)]
        m.funding_times = [f.ms for f in m.funding]
        self.assertEqual(list(funding_payments(m, 1, 1, 3)), [(1, -1), (2, -1), (3, -1)])
        self.assertEqual(list(funding_payments(m, -1, 1, 3)), [(1, 0), (2, 1), (3, 0)])

    def test_tie_and_opposite_side_do_not_duplicate_position(self):
        m = market()
        proposals = []
        for side in (1, -1):
            o = Order(side, 100, 100-side*2, 100+side*3, 2.2)
            proposals.append(SimpleNamespace(order=o, outcome=resolve(m, o, 1)))
        def decision(start):
            return SimpleNamespace(coin="BTC", start=start, proposals=proposals)
        tickets = replay([decision(0), decision(1), decision(13)], [[0.2, 0.2], [0.1, 0.4], [0.8, 0.1]], 0)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].proposal.order.side, -1)
        self.assertEqual(summary(tickets)["wins"], 0)
