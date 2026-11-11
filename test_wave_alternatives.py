import unittest
from types import SimpleNamespace

from perp_market import Bar, Funding
from wave_alternatives import carry_cash, momentum, resize, trade


class AlternativeBenchmarkTest(unittest.TestCase):
    def test_momentum_charges_only_changed_holdings(self):
        bars=[Bar(t,100,101,99,100,1,100,50) for t in range(0,11*86400,300)]
        market=SimpleNamespace(bars=bars,funding=[],funding_times=[])
        schedule={day*86400:["A","B"] for day in (8,9,10)}
        legs,_=momentum({"A":market,"B":market},schedule,11*86400)
        self.assertEqual(len(legs),6)
        # Flat marks, equal weights, three days. Only entry, tiny resizes and
        # final liquidation incur costs, about 20 USDT of fees plus 4 slippage.
        self.assertAlmostEqual(sum(r["gross"] for r in legs),0.)
        self.assertAlmostEqual(sum(r["net"] for r in legs),-24.,delta=.1)

    def test_funding_only_during_open_interval(self):
        events=[Funding(t*1000,.001,100) for t in (99,100,199,200)]
        market=SimpleNamespace(funding_times=[r.ms for r in events],funding=events)
        self.assertAlmostEqual(carry_cash(market,-1,2,100,200),.4)
        self.assertAlmostEqual(carry_cash(market,1,2,100,200),-.4)

    def test_spot_perp_delta_neutral_before_costs(self):
        spot=trade("ETH",1,0,300,100,105,10,spot=True)
        perp=trade("ETH",-1,0,300,101,106,10)
        self.assertEqual(spot["gross"]+perp["gross"],0)
        for row in (spot,perp):
            self.assertAlmostEqual(row["net"],row["gross"]-row["fees"]-row["slippage"])

    def test_resize_uses_only_closed_equity(self):
        legs=[trade("ETH",1,t,t+300,100,105,10) for t in (0,300)]
        gain=legs[0]["net"]
        resize(legs)
        self.assertAlmostEqual(legs[1]["net"],gain*(1+gain/10000))
        legs=[trade("ETH",1,t,t+600,100,105,10) for t in (0,300)]
        with self.assertRaises(ValueError):
            resize(legs)
