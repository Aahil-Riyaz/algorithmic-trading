import io
import unittest
from datetime import date
from zipfile import ZipFile

from flow_data import depth_samples, epoch, summarize_options


class FeedTests(unittest.TestCase):
    def test_depth_schema_change_keeps_common_bands_and_latest_complete_snapshot(self):
        day = date(2025, 10, 1)
        data = ["timestamp,percentage,depth,notional"]
        for sec, fmt, count in [(42, ".0f", 4), (48, ".2f", 4), (55, ".2f", 3)]:
            for pct in (-1, 1, -2, 2)[:count]:
                data.append(f"{day} 14:59:{sec},{pct:{fmt}},1,{100 + sec}")
        archive = io.BytesIO()
        with ZipFile(archive, "w") as file:
            file.writestr("depth.csv", "\n".join(data))
        samples = depth_samples(archive.getvalue(), day)
        ts = epoch(day) + 15 * 3600
        self.assertEqual(set(samples), {ts})
        self.assertEqual(samples[ts]["observed"], ts - 12)
        self.assertEqual(samples[ts]["bid_near"], 148)

    def test_signed_option_premium_and_crossed_blocks(self):
        call = dict(trade_id="1", instrument_name="BTC-1JAN26-80000-C",
                    direction="sell", amount=2, price=0.01, index_price=80_000)
        put = dict(call, trade_id="2", instrument_name="BTC-1JAN26-80000-P", direction="buy")
        block = dict(call, trade_id="3", block_trade_id="block")
        sample = summarize_options([call, put, block], "BTC")
        self.assertEqual((sample["call_sell"], sample["put_buy"]), (1600, 1600))
        self.assertEqual((sample["trades"], sample["excluded"]), (2, 1))
        with self.assertRaises(ValueError):
            summarize_options([call, call], "BTC")
