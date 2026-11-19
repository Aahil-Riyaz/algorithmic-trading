import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import numpy as np

import trend as T
import trend_basket_paper as B

DAY = T.DAY_MS


def series(n, seed, vol=1., end=date(2026, 11, 18)):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(.001, .03, n)))
    dates = [end - timedelta(days=n - 1 - i) for i in range(n)]
    return dates, np.r_[c[0], c[:-1]], c, np.full(n, vol)


class TrendBasketPaperTest(unittest.TestCase):
    def test_choose_ranks_by_30_day_volume_and_skips_ineligible(self):
        hist = {"AAAUSDT": series(400, 1, 5.), "BBBUSDT": series(400, 2, 9.), "CCCUSDT": series(100, 3, 99.),
                "USDCUSDT": series(400, 4, 99.), "BTCUPUSDT": series(400, 5, 99.), "NVDABUSDT": series(400, 6, 99.),
                "UUSDT": (series(400, 7)[0], np.ones(400), np.full(400, 1.0002), np.full(400, 99.))}
        ticker = [dict(symbol=s, quoteVolume="1") for s in hist]
        with mock.patch.object(B, "SIZE", 2):
            uni, start = B.choose(ticker, hist.get)
        self.assertEqual(uni, ["BBBUSDT", "AAAUSDT"])
        self.assertEqual(start, date(2026, 11, 18))

    def test_candles_keep_newest_unbroken_run(self):
        rows = []
        t0 = 1_700_000_000_000 // DAY * DAY
        for i in range(20):
            t = t0 + (i + (i >= 8)) * DAY  # one missing day after the eighth candle
            rows.append([t, "1", "2", ".5", "1.5", "1", t + DAY - 1, "10", 0, 0, 0, 0])
        with mock.patch.object(B, "fetch", return_value=json.dumps(rows).encode()):
            dates, o, c, qv = B.candles("X", now_ms=10 ** 15)
        self.assertEqual(len(dates), 12)
        self.assertTrue(all((b - a).days == 1 for a, b in zip(dates, dates[1:])))

    def test_combine_carries_a_finished_sleeve_forward(self):
        d0, d1, d2 = date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)
        sleeves = {"A": dict(trend={d0: 100, d1: 110, d2: 120}, hold={d0: 100, d1: 90, d2: 80}),
                   "B": dict(trend={d0: 100, d1: 95}, hold={d0: 100, d1: 50})}
        days, tot = B.combine(sleeves, d2)
        np.testing.assert_allclose(tot["trend"], [200, 205, 215])
        np.testing.assert_allclose(tot["hold"], [200, 140, 130])

    def test_run_is_idempotent_and_freezes_a_vanished_coin(self):
        hist = {f"C{i}USDT": series(400, i, 10. + i) for i in range(4)}
        ticker = [dict(symbol=s, quoteVolume="1") for s in hist]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(B, "SIZE", 3), \
                mock.patch.dict("os.environ", {}, clear=True):
            root = Path(tmp)
            state, tot = B.run(root=root, history=hist.get, ticker=ticker)
            self.assertEqual(len(state["universe"]), 3)
            self.assertAlmostEqual(tot["trend"][0], T.CAPITAL)
            B.run(root=root, history=hist.get)
            gone = state["universe"][0]
            state2, tot2 = B.run(root=root, history=lambda s: None if s == gone else hist[s])
            self.assertEqual(len(state2["ledger"]), 1)
            self.assertAlmostEqual(tot2["trend"][-1], tot["trend"][-1])
            self.assertEqual(T.SLIP, .0002)


if __name__ == "__main__":
    unittest.main()
