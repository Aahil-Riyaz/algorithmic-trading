import io
from datetime import date
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

import numpy as np

from carry_prices import close_bars, perp_mark_highs
from carry_watch import estimate, market_limits
from dated_carry import expiries, net_per_unit, projected_edge, replay
from flow_data import epoch
from perp_carry import BAR, CAPITAL, Panel, clears_costs, funding_projection, sleeve, trade_cost
from spot_arb_scan import route, timing


class FundingCarryTests(unittest.TestCase):
    def test_forecast_uses_past_settlements_and_detects_gaps(self):
        decision=30*86400
        times=list(range(0,decision*1000,8*3600_000))+[decision*1000]
        rates=[.0001]*(len(times)-1)+[99.]
        market=SimpleNamespace(times_ms=times,rates=rates)
        self.assertAlmostEqual(funding_projection(market,decision,30),.009)
        self.assertTrue(clears_costs(.05,100,100,30))
        self.assertFalse(clears_costs(.002,100,100,30))
        del market.times_ms[3]
        self.assertIsNone(funding_projection(market,decision,30))

    def test_round_trip_charges_both_books_and_both_directions(self):
        open_fee,open_slip=trade_cost(2,100,102)
        close_fee,close_slip=trade_cost(-2,100,102)
        self.assertAlmostEqual(open_fee+close_fee,4*(100*.001+102*.0005))
        self.assertAlmostEqual(open_slip+close_slip,4*(100+102)*.0002)

    def test_flat_hedge_cannot_make_directional_profit(self):
        first,end=date(2024,1,1),date(2024,2,1)
        times=np.arange(epoch(first)+BAR,epoch(end)+BAR,BAR)
        prices=np.linspace(100.,150.,len(times))
        zero=np.zeros(len(times))
        funds=zero.copy()
        funds[0]=50.    # Before entry
        funds[-1]=.5    # Inside holding
        panel=Panel(times,prices,prices,np.ones(len(times),dtype=bool),prices,funds,funds,[],[])
        path,totals,ledger,episodes=sleeve("BTC",panel,first,end,{first:{"BTC"}},"passive")
        self.assertAlmostEqual(totals["basis"],0.)
        qty=ledger[0]["qty"]
        self.assertAlmostEqual(qty,1000/prices[0])  # Uses the decision close
        self.assertAlmostEqual(totals["funding"],qty*.5)
        self.assertAlmostEqual(path[-1]-CAPITAL/4,totals["funding"]-totals["fees"]-totals["slippage"])
        self.assertEqual(len(episodes),1)
        filtered,_,_,episodes=sleeve("BTC",panel,first,end,{first:{"BTC"}},"lagged")
        np.testing.assert_equal(filtered,np.full(len(times),CAPITAL/4))
        self.assertFalse(episodes)

    def test_mark_repair_uses_checked_daily_file(self):
        start=epoch(date(2026,6,1))
        month=[(t,100,99) for t in range(start,start+30*86400,300)]
        def rows(symbol,period,daily=False):
            return iter(month[:288] if daily else month[288:])
        with patch("carry_prices.mark_rows",side_effect=rows):
            highs=perp_mark_highs("BTC",date(2026,6,1))
        self.assertEqual(len(highs),30*288)
        self.assertEqual(highs[start],100)

    def test_close_times_accept_both_archive_units_and_reject_duplicate(self):
        t=epoch(date(2025,1,1))
        def data(scale, repeat):
            row=f"{t*scale},5,5,5,5,1,{(t+300)*scale-1},5,1\n"
            file=io.BytesIO()
            with ZipFile(file,"w") as z:
                z.writestr("candles.csv",row*repeat)
            return file.getvalue()
        for scale in (1000,1000000):
            self.assertEqual(close_bars(data(scale,1),t,t+300)[t].price,5)
            with self.assertRaises(ValueError):
                close_bars(data(scale,2),t,t+300)


class DeliveryTests(unittest.TestCase):
    def test_expiries_and_capital_hurdle(self):
        days=list(expiries(date(2026,1,1),date(2026,10,1)))
        self.assertEqual(days,[date(2026,3,27),date(2026,6,26),date(2026,9,25)])
        self.assertGreater(projected_edge(100,104,84),0)
        self.assertLess(projected_edge(100,101,84),0)

    def test_index_mismatch_and_settlement_fees(self):
        gross,fees,slip,net=net_per_unit(100,104,80,81)
        self.assertEqual(gross,3)
        self.assertGreater(fees,0)
        self.assertAlmostEqual(slip,.0002*(100+104+80))
        self.assertAlmostEqual(net,gross-fees-slip)

    def test_missing_delivery_leaves_a_bound_and_never_a_realized_win(self):
        row=dict(coin="BTC",expiry="2026-03-27",issue="",gate=True,decision_spot=100,
                 decision_future=105,entry_spot=102,entry_future=106,spot_exit=104,index_low=103.,
                 index_high=105.,settlement_status="missing",entry_volume_proxy=1000,exit_spot_volume=1000,
                 min_short_margin_ratio=1.)
        ledger,summary=replay([row],date(2026,1,1),date(2026,4,1),True)
        self.assertIsNone(summary["exact_net"])
        self.assertEqual((ledger[0]["action"],summary["settled_pairs"]),("bounded_settlement",0))
        self.assertLess(*summary["net_range"])
        ledger,summary=replay([dict(row,exit_spot_volume=.001)],date(2026,1,1),date(2026,4,1),True)
        self.assertIsNone(summary["net_range"])
        self.assertEqual(ledger[0]["action"],"unpriced_unwind")


class LiveBookTests(unittest.TestCase):
    def test_spot_arbitrage_pays_on_both_legs_and_walks_depth(self):
        buy=dict(asks=[(100,5),(101,6)],coin="BTC",venue="a")
        sell=dict(bids=[(102,5),(101,6)],venue="b")
        limits=dict(step="1",min_base=1,min_quote=1)
        r=route(buy,sell,limits,fee_bps=10,budget=1000)
        self.assertEqual((r["qty"],r["buy_cost"],r["proceeds"]),(9,904.,914.))
        self.assertAlmostEqual(r["net_usdt"],10-1.818)
        with self.assertRaisesRegex(ValueError,"insufficient_depth"):
            route(buy,dict(sell,bids=[(102,1)]),limits)

    def test_capture_rejects_stale_samples_at_decision(self):
        q=dict(end_ms=1000.,event_ms=910.,venue="a")
        clocks={"a":dict(offset=0.,uncertainty=20.)}
        self.assertEqual(timing(q,q,clocks,1100.),(210.,40.))
        with self.assertRaisesRegex(ValueError,"stale"):
            timing(q,q,clocks,4000.)

    def test_common_lot_size_and_terminal_costs(self):
        def instrument(step):
            return dict(filters=[dict(filterType="LOT_SIZE",stepSize=step,minQty=step,maxQty="99999")])
        filters=market_limits(instrument(".02"),instrument(".05"))
        self.assertEqual(float(filters["step"]),.1)
        spot=dict(ask=100,ask_qty=40)
        future=dict(bids=[(104,4.),(103,50.)])
        r=estimate(spot,future,filters,84)
        self.assertAlmostEqual(r["qty"]*10,round(r["qty"]*10))
        self.assertLess(r["futures_bid_vwap"],104)
        self.assertLess(r["net_if_exit_lags_index_25bps"],r["conditional_net_usdt"])
        self.assertAlmostEqual(r["excess_usdt"],r["conditional_net_usdt"]-r["capital_charge"]-r["buffer"])
        with self.assertRaisesRegex(ValueError,"insufficient_displayed"):
            estimate(dict(spot,ask_qty=1),future,filters,84)
