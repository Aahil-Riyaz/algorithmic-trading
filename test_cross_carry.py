import unittest
from datetime import date

import numpy as np

import cross_carry as cc

BASE = cc.dnum(date(2020, 11, 1))
N = cc.dnum(date(2021, 3, 1)) - BASE
JAN = date(2021, 1, 1)


def bars(price=100., high=None, last=None, start=0, vol=1e6, path=None):
    out = {}
    for i in range(start, (last if last is not None else N)):
        p = path(i) if path else price
        out[BASE + i] = (p, high(i) if high else p, p, p, vol)
    return out


def funding(rate, last=N, hours=8.):
    return [((BASE + i // 3) * cc.DAY_MS + (i % 3) * 8 * 3600_000, rate, hours) for i in range(3 * last)]


def sym(name="AAAUSDT", rate=.001, **kw):
    f = kw.pop("f", None) or funding(rate)
    return cc.make_sym(name, BASE, N, kw.pop("perp", None) or bars(**kw), kw.pop("spot", None) or bars(**kw), f)


def run(syms, mode="ew", **kw):
    return cc.run({s.name: s for s in syms}, BASE, N, [JAN], mode, **kw)


class CrossCarry(unittest.TestCase):
    def test_short_perp_receives_positive_funding(self):
        pos, neg = run([sym(rate=.001)]), run([sym(rate=-.001)])
        self.assertGreater(pos["led"][:, 0].sum(), 0)
        self.assertLess(neg["led"][:, 0].sum(), 0)
        q = .025 * cc.CAPITAL / 2 / 100
        events = 2 + 3 * 29  # strictly after the Jan-2 open entry, through the Jan-31 close
        self.assertAlmostEqual(pos["led"][:, 0].sum(), q * .001 * 100 * events, places=6)

    def test_halved_positive_funding(self):
        full, half = run([sym(rate=.001)]), run([sym(rate=.001)], halve=True)
        self.assertAlmostEqual(half["led"][:, 0].sum(), full["led"][:, 0].sum() / 2, places=6)
        neg, negh = run([sym(rate=-.001)]), run([sym(rate=-.001)], halve=True)
        self.assertAlmostEqual(neg["led"][:, 0].sum(), negh["led"][:, 0].sum(), places=9)

    def test_hurdle_filter(self):
        self.assertAlmostEqual(cc.round_trip(1), .005)
        self.assertTrue(cc.clears(.15, 1))
        self.assertFalse(cc.clears(.14, 1))
        self.assertFalse(cc.clears(.15, 2))
        low, high = sym("LOWUSDT", rate=.00010), sym("HIGHUSDT", rate=.0005)
        uni = cc.decide({s.name: s for s in (low, high)}, BASE, cc.dnum(JAN))
        self.assertEqual([u["sym"] for u in cc.picks(uni, "top10")], ["HIGHUSDT"])
        self.assertEqual(len(cc.picks(uni, "ew")), 2)

    def test_top10_cap_and_order(self):
        coins = [sym(f"C{i:02d}USDT", rate=.0003 + i * 1e-5) for i in range(15)]
        uni = cc.decide({s.name: s for s in coins}, BASE, cc.dnum(JAN))
        chosen = cc.picks(uni, "top10")
        self.assertEqual(len(chosen), 10)
        self.assertEqual(chosen[0]["sym"], "C14USDT")

    def test_decision_is_strictly_lagged(self):
        first = cc.dnum(JAN)
        a = sym()
        base_dec = cc.decide({a.name: a}, BASE, first)
        b = sym()
        for arr in (b.pq, b.sq):
            arr[first - BASE:] = 1e15
        b.pc[first - BASE:] = 1e9
        b.fr[b.ft >= first * cc.DAY_MS] = 5.
        self.assertEqual(base_dec, cc.decide({b.name: b}, BASE, first))
        c = sym()
        c.sc[first - BASE - 1] = np.nan
        self.assertEqual(cc.decide({c.name: c}, BASE, first), [])
        cut = first * cc.DAY_MS
        gap = [t for t in funding(.001) if t[0] >= cut - 29 * 8 * 3600_000 or t[0] < cut - 30 * cc.DAY_MS]
        d = sym(f=gap)
        self.assertEqual(cc.decide({d.name: d}, BASE, first), [])
        ok = sym(f=[t for t in funding(.001) if t[0] >= cut - 30 * 8 * 3600_000 or t[0] < cut - 30 * cc.DAY_MS])
        self.assertEqual(len(cc.decide({ok.name: ok}, BASE, first)), 1)

    def test_score_uses_each_prints_interval(self):
        f = [(t, r, 4.) for t, r, _ in funding(.0001)]
        s = sym(f=f)
        uni = cc.decide({s.name: s}, BASE, cc.dnum(JAN))
        self.assertAlmostEqual(uni[0]["score"], .0001 * 8760 / 4)

    def test_liquidation_trigger(self):
        spike = cc.dnum(date(2021, 1, 10)) - BASE
        quiet = run([sym(high=lambda i: 142. if i == spike else 100.)], liq_margin=.5)
        hit = run([sym(high=lambda i: 143.5 if i == spike else 100.)], liq_margin=.5)
        self.assertEqual(sum(r["liquidated"] for r in quiet["cm"].values()), 0)
        self.assertEqual(sum(r["liquidated"] for r in hit["cm"].values()), 1)
        one = run([sym(high=lambda i: 143.5 if i == spike else 100.)], liq_margin=1.)
        self.assertEqual(sum(r["liquidated"] for r in one["cm"].values()), 0)
        # buyback at the high plus 20 bp, spot sold at the close: loss = q*(100 - 143.5*1.002) on the perp leg
        q = .025 * cc.CAPITAL / 2 / 100
        self.assertAlmostEqual(hit["led"][:, 1].sum(), q * (100 - 143.5 * 1.002), places=6)
        # slot sits in cash afterwards: funding stops after the liquidation day
        self.assertLess(hit["led"][:, 0].sum(), quiet["led"][:, 0].sum())
        self.assertAlmostEqual(hit["led"][spike + 1 - (cc.dnum(JAN) - BASE):, 0].sum(), 0, places=9)

    def test_delisting_closes_at_last_close(self):
        last = cc.dnum(date(2021, 1, 15)) - BASE
        path = lambda i: 100. + i % 3
        s = sym(perp=bars(path=path, last=last + 1), spot=bars(path=path, last=last + 1))
        res = run([s])
        r = res["cm"][(JAN, "AAAUSDT")]
        self.assertEqual(r["delisted"], 1)
        self.assertEqual(r["liquidated"], 0)
        k = last - (cc.dnum(JAN) - BASE)
        self.assertEqual(res["led"][k + 1:, :2].sum(), 0)
        self.assertGreater(res["led"][k + 1, 2], 0)
        self.assertEqual(res["led"][k + 2:, 2].sum(), 0)
        self.assertAlmostEqual(res["eq"][-1], res["eq"][k + 1], places=9)

    def test_fee_and_slippage_math(self):
        res = run([sym(rate=0.)], weight=.1)
        r = res["cm"][(JAN, "AAAUSDT")]
        q = .1 * cc.CAPITAL / 2 / 100
        leg = q * 100
        fees = leg * cc.SPOT_FEE + leg * cc.PERP_FEE
        slip = 2 * leg * cc.SLIP
        self.assertAlmostEqual(r["fees"], 2 * fees, places=9)
        self.assertAlmostEqual(r["slippage"], 2 * slip, places=9)
        self.assertAlmostEqual(res["eq"][-1] - cc.CAPITAL, -(r["fees"] + r["slippage"]), places=9)
        # coins outside the top 20 by volume pay doubled slippage
        self.assertEqual((cc.slip_mult(20), cc.slip_mult(21), cc.slip_mult(None)), (1, 2, 2))
        self.assertAlmostEqual(cc.trade_cost(1000, 1000, 2)[1], 2000 * .0005 * 2)
        self.assertAlmostEqual(cc.trade_cost(1000, 2000, 1)[0], 1000 * .001 + 2000 * .0005)

    def test_ledger_reconciles_on_random_walks(self):
        rng = np.random.default_rng(1)
        coins = []
        for k in range(6):
            w = 100 * np.exp(np.cumsum(rng.normal(0, .03, N)))
            hi = w * 1.04
            perp = {BASE + i: (w[i], hi[i], w[i], w[i] * (1 + rng.normal(0, .002)), 1e6 * (k + 1)) for i in range(N)}
            spot = {BASE + i: (w[i], w[i], w[i], w[i], 1e6 * (k + 1)) for i in range(N)}
            coins.append(cc.make_sym(f"R{k}USDT", BASE, N, perp, spot, funding(.0004 * (k + 1))))
        res = run(coins)
        led = res["led"]
        self.assertAlmostEqual(res["eq"][-1] - cc.CAPITAL, led[:, 0].sum() + led[:, 1].sum() - led[:, 2].sum() - led[:, 3].sum(), places=6)
        s = cc.period_stats(res, JAN, date(2021, 2, 1))
        self.assertAlmostEqual(s["net_usdt"], s["funding"] + s["basis"] - s["fees"] - s["slippage"], places=6)

    def test_parsers(self):
        import io
        from zipfile import ZipFile
        def z(text):
            b = io.BytesIO()
            with ZipFile(b, "w") as f:
                f.writestr("x.csv", text)
            return b.getvalue()
        spot = cc.parse_klines(z("1740787200000000,1,2,0.5,1.5,9,0,77,0\n"))
        perp = cc.parse_klines(z("open_time,open,high,low,close,volume,close_time,quote_volume\n1740787200000,1,2,0.5,1.5,9,0,77,0\n"))
        self.assertEqual(spot, perp)
        self.assertEqual(cc.parse_funding(z("calc_time,funding_interval_hours,last_funding_rate\n5,4,-1.4E-7\n")), [(5, -1.4e-7, 4.)])
        self.assertEqual(cc.parse_klines(b""), {})


if __name__ == "__main__":
    unittest.main()
