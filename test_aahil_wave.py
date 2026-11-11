"""Prospective append-only paper lifecycle, pricing, and portfolio risk acceptance."""
import sqlite3
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import patch

from aahil_wave import (advance, append, checkpoint, connect, propose, render,
                        scoreboard, states, TTL)
from wave_paper_service import catch_up


class WavePaperTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db = connect(Path(directory.name)/"events.db")
        self.addCleanup(self.db.close)
        self.t = 180000
        self.candidate = dict(coin="BTC",decision=self.t,quote_time=self.t,model_id="model-1",
                              side=1,entry=100.,stop=98.,target=103.,atr=1.,
                              wave1=97.,bid=100.99,ask=101.,expected_net_r=.1,
                              p_fill=.4,p_tp_given_fill=.55)

    def signal(self, **changes):
        c = dict(self.candidate,**changes)
        c["quote_time"] = c["decision"]
        return propose(self.db,c,c["decision"])

    def bar(self,key,minutes,ohlc=(101.,102.,100.1,101.),settlements=()):
        t = self.t+300+60*minutes
        advance(self.db,key,(t,*ohlc),settlements)

    def test_idempotent_signal_and_no_rewriting(self):
        key = self.signal()
        self.assertEqual(key,self.signal())
        s = states(self.db)[key]
        self.assertEqual((s["status"],s["expires"]-s["active"]),("pending",TTL))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM events WHERE id=?",(key,))
        message = render(self.db.execute("SELECT * FROM events WHERE kind='signal'").fetchone())
        self.assertIn("UTC",message)
        self.assertIn("P(TP before SL | fill)",message)

    def test_replacement_keeps_earliest_cancel_deadline(self):
        first = self.signal()
        second = self.signal(decision=self.t+60)
        third = self.signal(decision=self.t+120)
        orders = states(self.db)
        self.assertEqual(orders[first]["replace_at"],orders[second]["active"])
        self.assertEqual(orders[second]["replace_at"],orders[third]["active"])
        self.bar(first,0)
        self.bar(first,1)
        self.assertEqual(states(self.db)[first]["status"],"replaced")

    def test_filled_order_blocks_queued_replacement(self):
        first = self.signal()
        replacement = self.signal(decision=self.t+60)
        self.bar(first,0,(101.,101.,99.5,100.))
        self.bar(first,1)
        self.bar(replacement,1)
        self.assertEqual(states(self.db)[replacement]["status"],"position_busy")
        self.assertEqual(states(self.db)[first]["status"],"filled")

    def test_pending_order_cannot_escape_loss_through_invalidation(self):
        key = self.signal()
        self.bar(key,0,(101.,102.,96.,100.))
        s = states(self.db)[key]
        self.assertEqual(s["status"],"sl")
        self.assertAlmostEqual(s["net_r"],-1.)

    def test_six_hour_expiry_and_retry(self):
        key = self.signal()
        for i in range(360):
            self.bar(key,i)
        self.bar(key,359)
        self.assertEqual(states(self.db)[key]["status"],"expired")
        self.assertEqual(self.db.execute("SELECT ts FROM events WHERE kind='expired'").fetchone()[0],
                         self.t+300+TTL)

    def test_funding_and_break_even_after_costs(self):
        key = self.signal()
        self.bar(key,0,(101.,101.,99.8,100.))
        self.bar(key,1,(100.,102.5,99.9,102.1),[(self.t+361,.0001,100.)])
        self.assertEqual(states(self.db)[key]["status"],"be_armed")
        self.bar(key,2,(101.,102.,99.9,100.))
        self.bar(key,2,(101.,102.,99.9,100.))
        s = states(self.db)[key]
        self.assertEqual(s["status"],"be")
        self.assertLess(s["net_r"],0)
        self.assertAlmostEqual(s["funding_paid"],-s["qty"]*.01)
        self.assertEqual(scoreboard(self.db)["closed"],1)

    def test_correlated_cap_and_zero_lower_bound(self):
        for coin in ("BTC","ETH","SOL","AVAX"):
            self.signal(coin=coin,stop=99.,atr=.5,bid=100.4,ask=100.41)
        orders = states(self.db)
        self.assertLessEqual(sum(s["qty"]*s["entry"] for s in orders.values()),7500.)
        key = self.signal(coin="AVAX",decision=self.t+60,kelly_lower_fraction=0.)
        self.assertEqual(self.db.execute("SELECT kind FROM events WHERE id=?",(key,)).fetchone()[0],"skip")

    def test_kill_cancels_pending_and_stays_latched(self):
        key = self.signal(coin="ETH")
        append(self.db,"account","account",self.t-120,equity=12000.,daily=False,kill=False)
        self.assertTrue(checkpoint(self.db,self.t+60)["kill"])
        self.assertEqual(states(self.db)[key]["status"],"risk_cancelled")
        self.assertTrue(checkpoint(self.db,self.t+86400)["kill"])

    def test_daily_halt_cancels_pending_then_resets_next_day(self):
        key = self.signal(coin="SOL")
        append(self.db,"account","account",self.t//86400*86400-60,equity=10200.,daily=False,kill=False)
        state = checkpoint(self.db,self.t+60)
        self.assertTrue(state["daily"])
        self.assertFalse(state["kill"])
        self.assertEqual(states(self.db)[key]["status"],"risk_cancelled")
        self.assertFalse(checkpoint(self.db,self.t+86400)["daily"])

    def test_gap_does_not_advance_cursor(self):
        key = self.signal()
        with self.assertRaises(ValueError):
            self.bar(key,1)
        self.assertEqual(states(self.db)[key]["last"],self.t+240)

    def test_atomic_portfolio_minute(self):
        keys = [self.signal(coin=c) for c in ("BTC","ETH")]
        t = self.t+300
        def api(url,params):
            if "fundingRate" in url:
                return []
            # Second symbol has an impossible OHLC. The first advancement rolls back.
            low = 99.5 if params["symbol"]=="BTCUSDT" else 104.
            return [[t*1000,101,102,low,100,0,(t+60)*1000-1]]
        with patch("wave_paper_service.request_json",side_effect=api):
            with self.assertRaises(ValueError):
                catch_up(self.db,t+62)
        for key in keys:
            self.assertEqual(states(self.db)[key]["last"],t-60)
