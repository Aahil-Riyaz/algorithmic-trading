import unittest
from types import SimpleNamespace

from purged_cv import purged_folds
from regime_filters import classify, live_book, rolling_atr


class FilterTests(unittest.TestCase):
    def test_thresholds_and_direction(self):
        def gate(expansion=1, basis=-12, volume=1, book=1):
            return classify([-3, expansion, basis, volume, book]).block
        self.assertIsNone(gate(1.5))
        self.assertEqual(gate(1.501), "atr_expansion")
        self.assertEqual(gate(basis=12), "premium")
        self.assertEqual(gate(volume=0.1), "thin_liquidity")
        self.assertEqual(gate(book=0.2), "thin_liquidity")

    def test_rolling_shock_excludes_current_hour_from_reference(self):
        bar = SimpleNamespace(high=101, low=99, close=100)
        bars = [bar]*2400
        shock = SimpleNamespace(high=130, low=99, close=125)
        atr, ref = rolling_atr(bars+[shock])
        self.assertAlmostEqual(atr[2400],2)
        self.assertAlmostEqual(ref[2401],2)
        self.assertGreater(atr[2401]/ref[2401],1.5)

    def test_purge_gap_postfold_embargo_and_right_censoring(self):
        rows = [SimpleNamespace(start=a,end=b) for a,b in
                [(5,10),(79,91),(98,105),(100,108),(145,149),(150,155),(172,177)]]
        splits = list(purged_folds(rows,[(100,150),(200,250)],20,10))
        self.assertEqual(splits[0],([0],[3]))
        self.assertNotIn(5,splits[1][0])
        self.assertIn(6,splits[1][0])

    def test_partial_or_late_live_snapshot_fails_closed(self):
        band = dict(complete=True,bid_usdt=100,ask_usdt=80)
        record = dict(received_ms=99901,book=dict(observed_ms=99900,bands_bps={"100":band}))
        self.assertEqual(live_book(record,100)["bid_near"],100)
        band["complete"] = False
        self.assertIsNone(live_book(record,100))
