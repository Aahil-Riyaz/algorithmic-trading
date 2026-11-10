import unittest
from datetime import date
from discord_audit import add_payoffs, costed_r, parse, printed_match, summary, utc


def alert(entry="100.0000",time="Yesterday at 23:50",coin="BTC"):
    return f"""{coin}USDT LONG [CRYPTO]
Confidence
●●●●○
Entry
{entry}
Stop
99.0000
Target
101.5000
Disclaimer
Alert invalid after 8 hours from the alert.
{coin}USDT LONG [CRYPTO]
Price 101.6000•{time}
"""


class DiscordAuditTest(unittest.TestCase):
    day = date(2026,11,11)

    def test_mixed_dates_utc(self):
        self.assertEqual(utc("Today at 01:00",self.day),"2026-11-10T21:00:00+00:00")
        self.assertEqual(utc("Yesterday at 23:50",self.day),utc("10/11/2026, 23:50",self.day))
        self.assertTrue(printed_match("76929.0000","7.693e+04"))
        self.assertFalse(printed_match("76920.0000","7.693e+04"))

    def test_duplicates_and_partial_history(self):
        update = "✅ TP Hit — BTCUSDT LONG\nTarget 101.5 reached\nEntry 100 → +1.50R\nToday at 01:01\n"
        rows,stats,issues = parse(alert()+alert()+update+update+alert(coin="ETH"),self.day)
        add_payoffs(rows,2,5,1)
        self.assertEqual((len(rows),len(issues),len(stats)),(2,2,0))
        self.assertEqual(rows[0]["outcome"],"TP")
        self.assertEqual(rows[1]["maker_taker_stop"],"")
        self.assertEqual(summary(rows)["fill_rate_upper"],1.)

    def test_ambiguous_invalidations_stay_unmatched(self):
        invalid = "❌ Setup Invalidated — BTCUSDT LONG\nPrice overlapped Wave 1 (102) before filling\nToday at 00:02"
        rows,_,issues = parse(alert()+alert("100.0100","Today at 00:01")+invalid,self.day)
        self.assertEqual(issues[0]["reason"],"ambiguous")
        self.assertTrue(all(r["outcome"]=="unresolved" for r in rows))

    def test_all_cumulative_posts_and_costs(self):
        block = "Trade Stats — CRYPTO\nClosed\n10\nWins\n5\n"
        _,stats,_ = parse(block+"Yesterday at 04:00\n"+block.replace("10","12")+"Today at 04:05",self.day)
        self.assertEqual([s["Closed"] for s in stats],["10","12"])
        for side,stop in (("LONG",99),("SHORT",101)):
            self.assertLess(costed_r(100,stop,100,side,"BE","maker_taker_stop"),0)
            self.assertAlmostEqual(costed_r(100,stop,100,side,"BE","maker_maker"),-.04)
