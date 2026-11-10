import unittest

from discord_market import Bar
from discord_replay import Order, VALID, accounting, simulate


class CandleAuditTests(unittest.TestCase):
    order = Order(0,1,100,99,101.5,105)

    def tape(self, *observations):
        return [Bar(i*60,*ohlc) for i,ohlc in enumerate(observations)]

    def test_post_minute_excluded_and_stop_first(self):
        tape = self.tape((102,103,97,102),(102,103,101,102),(100.1,102,98,101))
        result = simulate(tape,self.order)
        self.assertEqual((result.status,result.fill,result.ambiguous),("SL",120,1))

    def test_last_minute_and_exact_expiry(self):
        tape = [Bar(t,102,103,101,102) for t in range(0,VALID+60,60)]
        tape[-1] = Bar(VALID,100,101,98,99)
        self.assertEqual(simulate(tape,self.order).status,"expired")
        self.assertEqual(simulate(tape[:-2],self.order).status,"pending_at_cutoff")
        tape[-2] = Bar(VALID-60,100,101,98,99)
        self.assertEqual(simulate(tape,self.order).fill,VALID-60)

    def test_ambiguous_invalidation(self):
        tape = self.tape((102,104,101,102),(102,106,99.5,103))
        self.assertEqual(simulate(tape,self.order,wave=True).status,"ambiguous_invalidation")

    def test_touch_and_be_after_confirmation(self):
        tape = self.tape((103,104,102,103),(102,102,100,101),(101,101,100.5,101))
        self.assertIsNone(simulate(tape,self.order).fill)
        self.assertEqual(simulate(tape,self.order,touch=True).fill,60)
        tape = self.tape((103,104,102,103),(100.4,101,99.8,100.2),
                         (100.2,100.8,100.1,100.7),(100.3,100.5,99.7,100))
        result = simulate(tape,self.order,be="0.5R")
        self.assertEqual((result.status,result.end,result.exit),("BE",180,100))
        net = accounting(self.order,result,[],2,5,1)
        self.assertTrue(net["taker_taker"]<net["maker_taker_stop"]<net["maker_maker"]<0)

    def test_censor_matched_random_window(self):
        tape = self.tape((103,104,102,103),(102,103,101,102),(102,103,98,100))
        self.assertEqual(simulate(tape,self.order,through=120).status,"pending_at_cutoff")

    def test_reported_level_cannot_change_independent_replay(self):
        tape = self.tape((103,104,102,103),(104,106,103,105),(103,104,98,99))
        self.assertEqual(simulate(tape,self.order).status,"SL")
        self.assertEqual(simulate(tape,self.order,wave=True).status,"invalidated")
