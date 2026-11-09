import unittest

from flow_features import decisions
from perp_market import Bar, Funding, Market, aggregate


def fixture():
    bars = [Bar(i * 300, 100, 101, 99, 100, 1, 100, 65) for i in range(60 * 12)]
    t = 30 * 3600
    rates = [Funding((t - 3600) * 1000, 0.0001, 100), Funding(t * 1000, 0.7, 100)]
    book = dict(observed=t - 5, bid_near=80, ask_near=20, bid_wide=200, ask_wide=100)
    option = dict(call_buy=10, call_sell=5, put_buy=5, put_sell=6, trades=4)
    m = Market(bars, aggregate(bars), rates, [f.ms for f in rates], {t: book},
               {t: {"BTC": option, "ETH": option}}, "test")
    return t, m


class ClockTests(unittest.TestCase):
    def test_future_candles_and_future_settlement_cannot_change_inputs(self):
        t, m = fixture()
        rows, _ = decisions("BTC", m, t, t + 26 * 3600)
        self.assertEqual(len(rows), 1)
        before = rows[0].proposals[0].features
        self.assertEqual(before[13], 1.0)  # last settled funding was one basis point
        m.bars[t // 300] = Bar(t, 100, 150, 95, 147, 1, 100, 0)
        m.hours = aggregate(m.bars)
        rows, _ = decisions("BTC", m, t, t + 26 * 3600)
        self.assertEqual(before, rows[0].proposals[0].features)
        self.assertEqual(m.bars[rows[0].start].time, t + 300)

    def test_stale_book_and_cross_boundary_label_are_excluded(self):
        t, m = fixture()
        self.assertFalse(decisions("BTC", m, t, t + 26 * 3600 - 1)[0])
        m.depth[t]["observed"] = t - 181
        rows, coverage = decisions("BTC", m, t, t + 26 * 3600)
        self.assertFalse(rows)
        self.assertEqual(coverage["missing_or_stale_book"], 1)
