import csv
import tempfile
import unittest
from pathlib import Path

from wave_sealed import START, review
from wave_selection import evaluate


class SelectionTests(unittest.TestCase):
    def test_future_period_stays_closed(self):
        self.assertEqual(review(START)["status"],"sealed")

    def test_constant_candidate_panel_is_uninformative(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"days.csv"
            with p.open("w",newline="") as f:
                w=csv.writer(f)
                w.writerow(["date","first","second"])
                w.writerows([[f"2025-01-{i:02}",0,0] for i in range(1,17)])
            self.assertEqual(evaluate(p)["status"],"insufficient nonconstant variants")

    def test_missing_calendar_days_raise(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/"days.csv"
            p.write_text("date,first,second\n2025-01-01,1,2\n2025-01-04,1,2\n")
            with self.assertRaisesRegex(ValueError,"contiguous"):
                evaluate(p)
