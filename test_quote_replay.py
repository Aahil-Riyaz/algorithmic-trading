import unittest
from types import SimpleNamespace

from perp_market import Bar
from perp_orders import Order
from quote_replay import Proposal, replay_quotes


class QuotesTest(unittest.TestCase):
    def setUp(self):
        bars = [Bar(300*i, 101, 102, 100, 101, 1, 101, 50) for i in range(310)]
        self.m = SimpleNamespace(bars=bars, funding=[], funding_times=[])
        self.o = Order(1, 99, 95, 105, 4.3)

    def dip(self, j, low):
        self.m.bars[j] = self.m.bars[j]._replace(low=low)

    def replay(self, times=(1, 2), **kwargs):
        return replay_quotes(self.m, [Proposal(i, self.o, .1) for i in times], **kwargs)

    def test_cancel_before_fill_on_replacement_bar(self):
        self.dip(3, 98)
        old, new = self.replay()
        self.assertEqual((old["status"], old["ended"], old["replaced_by"]), ("replaced", 900, 600))
        self.assertEqual((new["status"], new["fill"]), ("filled", 900))
        old, new = self.replay(replace=False)
        self.assertEqual((old["status"], new["status"]), ("filled", "kept_first"))

    def test_filled_position_survives_new_signal(self):
        self.dip(2, 98)
        old, new = self.replay()
        self.assertEqual((old["status"], new["status"]), ("filled", "position_busy"))
        self.assertEqual(old["exit_reason"], "timeout")

    def test_expiry_is_exclusive(self):
        self.dip(5, 98)
        old, new = self.replay(times=(1,4))
        self.assertEqual((old["status"], new["status"]), ("expired", "filled"))
        self.assertEqual(old["ended"], new["active"])

    def test_rejected_replacement_cancels_old_quote(self):
        self.m.bars[3] = self.m.bars[3]._replace(open=98, low=97)
        self.assertEqual([r["status"] for r in self.replay()], ["replaced", "post_only_reject"])

    def test_touch_and_penetration(self):
        self.dip(2, 99)
        self.assertEqual(self.replay((1,))[0]["status"], "expired")
        self.dip(2, 98.99)
        self.assertEqual(self.replay((1,))[0]["status"], "filled")
        self.assertEqual(self.replay((1,), penetration_bps=2)[0]["status"], "expired")

    def test_short_replacement(self):
        self.o = Order(-1, 103, 107, 95, 4.3)
        self.m.bars[3] = self.m.bars[3]._replace(high=104)
        self.assertEqual([r["status"] for r in self.replay()], ["replaced", "filled"])

    def test_duplicate_decisions_raise(self):
        with self.assertRaises(ValueError):
            self.replay((1,1))

    def test_paper_pending_survives_restart_then_expires(self):
        bars = self.m.bars
        self.m.bars = bars[:4]
        self.assertEqual(self.replay((1,), allow_open=True)[0]["status"], "working")
        self.m.bars = bars[:5]
        self.assertEqual(self.replay((1,), allow_open=True)[0]["status"], "expired")

    def test_paper_open_position_has_no_realized_pnl_until_exit(self):
        self.dip(2, 98)
        bars = self.m.bars
        self.m.bars = bars[:4]
        pending = self.replay(allow_open=True)
        self.assertEqual((pending[0]["status"], pending[0]["pnl"], pending[1]["status"]),
                         ("open", 0., "position_busy"))
        self.m.bars = bars[:7]
        self.dip(5, 94)
        done = self.replay(allow_open=True)
        self.assertEqual((done[0]["status"], done[0]["exit_reason"]), ("filled", "stop"))
        self.assertLess(done[0]["pnl"], 0.)
