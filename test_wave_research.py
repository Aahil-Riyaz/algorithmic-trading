import unittest
from types import SimpleNamespace
import numpy as np

from backtest import FEE,SLIP
from perp_market import Bar
from wave_research import GAP,HORIZON,candidate,geometry,indicators,pivot_sequence
from wave_validation import chronological


class ResearchTest(unittest.TestCase):
    def test_pivot_cannot_appear_at_extreme_before_reversal(self):
        prices=[100,103,105,104,103,101,104]
        self.assertEqual(pivot_sequence(prices[:4],[2]*4)[-1][2],-1)
        pivots=pivot_sequence(prices,[2]*len(prices))
        self.assertIn((2,105,1,4),pivots)

    def test_feature_prefix_invariance(self):
        p=100+np.sin(np.arange(940)/8)*4
        bars=[Bar(i*300,x,x+.5,x-.5,x,1,x,x*.55) for i,x in enumerate(p)]
        c,a=indicators(bars)
        v1=candidate("BTC",bars,900,c,a,.001,100,.0001)
        cc,aa=indicators(bars[:900])
        v2=candidate("BTC",bars[:900],900,cc,aa,.001,100,.0001)
        self.assertIsNotNone(v1)
        self.assertEqual(v1,v2)

    def test_geometry_accepts_both_directions_and_covers_cost(self):
        for side in (-1,1):
            o=geometry(side,100,.01)
            self.assertGreaterEqual(abs(o.entry-o.stop)+1e-12,4*(2*FEE+SLIP)*o.entry)
            self.assertGreater(side*(o.target-o.entry),0)

    def test_purge_and_fixed_right_edge(self):
        start=500000;stop=start+2*HORIZON
        rows=[dict(time=1,end=start-GAP-1),dict(time=2,end=start-GAP),dict(time=start,end=start+99),
              dict(time=stop-HORIZON+1,end=stop-100)]
        a,b=chronological(rows,start,stop)
        self.assertEqual(a,rows[:1])
        self.assertEqual(b,rows[2:3])
