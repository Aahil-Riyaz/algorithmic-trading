import json
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import numpy as np

import trend as T
import trend_paper as P


def market(n=400, seed=3):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(.001, .03, n)))
    o = np.r_[c[0], c[:-1]]
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(n)]
    return dates, o, np.maximum(o, c) * 1.01, np.minimum(o, c) * .99, c


class TrendPaperTest(unittest.TestCase):
    def test_levels_are_the_prices_tomorrows_signal_compares_against(self):
        dates, o, h, l, c = market()
        lv = P.levels(c)
        for nxt in (min(lv.values()) * .5, max(lv.values()) * 2):
            self.assertAlmostEqual(T.signal(np.r_[c, nxt])[-1], np.mean([nxt > v for v in lv.values()]))

    def test_no_paper_trades_before_start(self):
        dates, o, h, l, c = market()
        start = dates[300]
        w, sim, first, bh = P.replay(dates, o, c, start)
        self.assertEqual(first, 300)
        self.assertTrue(all(i > 300 for i, _ in sim["trades"]))
        self.assertEqual(sim["eq"][300], T.CAPITAL)
        self.assertEqual(bh[0], T.CAPITAL)

    def test_start_without_warmup_is_refused(self):
        dates, o, h, l, c = market()
        with self.assertRaises(ValueError):
            P.replay(dates, o, c, dates[10])

    def test_message_says_paper_and_states_the_move(self):
        dates, o, h, l, c = market()
        r, _ = P.summary("BTCUSDT", dates, o, c, dates[300])
        text = P.message([r])
        self.assertIn("no orders placed", text)
        self.assertIn(r["action"] if r["action"] != "HOLD" else "no trade", text)
        self.assertLessEqual(len(text), 2000)

    def test_multipart_carries_json_and_png(self):
        body, kind = P.multipart("hello", b"\x89PNGdata")
        boundary = kind.split("boundary=")[1].encode()
        self.assertEqual(body.count(b"--" + boundary), 3)
        self.assertIn(b'"content": "hello"', body)
        self.assertIn(b"\x89PNGdata", body)

    def test_rerun_same_day_keeps_one_ledger_row_and_posts_once(self):
        data = market()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(P, "closed_candles", return_value=data), \
                mock.patch.object(P, "post") as post, \
                mock.patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://example.invalid/hook"}):
            root = Path(tmp)
            P.run(start=data[0][300].isoformat(), root=root)
            P.run(root=root)
            state = json.loads((root / "state.json").read_text())
            self.assertEqual(len(state["ledger"]), 1)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(state["start"], data[0][300].isoformat())
            self.assertTrue((root / f"{data[0][-1]}.png").read_bytes().startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
