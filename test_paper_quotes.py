import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from paper_quotes import decisions, paper_coin


class ForwardTests(unittest.TestCase):
    def test_replay_ignores_late_and_duplicate_rescores(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for i,(ms,status) in enumerate(((301000,"neutral"),(305000,"qualifies"),(600000,"qualifies"))):
                path = Path(folder)/f"{i}.json"
                path.write_text(json.dumps(dict(cutoff=300, coins={"SOL": dict(scored_ms=ms,status=status)})))
                paths.append(path)
            self.assertEqual(decisions(reversed(paths))[("SOL",300)]["status"],"neutral")
            self.assertEqual(decisions([paths[-1]]), {})

    @patch("paper_quotes.request_json", return_value=[])
    @patch("paper_quotes.rest_candles")
    def test_live_signals_replay_one_coin_and_one_pending_entry(self, candles, funding):
        candles.return_value = [[t*1000,101,102,100,101,1,0,101,0,0,50] for t in (300,600,900)]
        proposal = dict(status="qualifies",entry=99,stop=95,target=105,risk=4.3,expected_r=.1)
        history = {("BTC",300): proposal, ("BTC",600): proposal, ("SOL",300): proposal}
        rows = paper_coin("BTC", history, 1200)
        self.assertEqual([r["status"] for r in rows], ["replaced","working"])
        self.assertEqual(rows[0]["replaced_by"], 600)
        candles.assert_called_once_with("BTC",300,1200)
        self.assertEqual(paper_coin("XRP",history,1200), [])
