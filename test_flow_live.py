import unittest

from flow_live import comparable_book, snapshot_book


class LiveBookTests(unittest.TestCase):
    def test_truncated_band_is_explicit(self):
        thin = dict(T=3_599_000, lastUpdateId=1, bids=[["99.99","1"],["99.80","10"]],
                    asks=[["100.01","2"],["100.20","2"]])
        snapshot = snapshot_book(thin)
        self.assertIsNone(snapshot["bands_bps"]["100"]["imbalance"])
        self.assertIsNone(comparable_book(dict(book=snapshot, received_ms=3_599_100)))
        self.assertTrue(snapshot["bands_bps"]["5"]["complete"])

    def test_only_observable_full_books_export(self):
        raw = dict(T=3_599_000, lastUpdateId=3, bids=[["99.99","1"],["97","1"]],
                   asks=[["100.01","2"],["103","2"]])
        book = snapshot_book(raw)
        t, b = comparable_book(dict(book=book, received_ms=3_599_100))
        self.assertEqual(t, 3600)
        self.assertAlmostEqual(b["bid_near"], 99.99)
        self.assertAlmostEqual(b["ask_wide"], 200.02)
        self.assertIsNone(comparable_book(dict(book=book, received_ms=3_901_000)))
