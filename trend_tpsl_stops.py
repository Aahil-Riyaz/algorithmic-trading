"""Choose a stop rule for the trend TP/SL trades on half the coins and confirm it on the other half."""
import csv

import numpy as np

import trend as T
import trend_tpsl as S
from flow_data import save_json
from trend_fresh import candles, summary
from trend_improve import months, split

OUT = T.OUT.parent / "trend-tpsl-stops"


def run_half(coins):
    daily = {k: {} for k in S.STOPS}
    trades = {k: [] for k in S.STOPS}
    for sym in coins:
        a = candles(sym, months(sym))
        if len(a) < T.WARM + 1 + 365:
            continue
        dates = [T.day(t) for t in a[:, 0]]
        o, h, l, c = a[:, 1], a[:, 2], a[:, 3], a[:, 4]
        sig = T.signal(c)
        sig[:T.WARM] = np.nan
        for k, (init, trail, be) in S.STOPS.items():
            s = S.simulate(o, h, l, c, sig, stop_atr=init, trail_atr=trail, breakeven=be)
            f = s["first"] + 1
            for d, x in zip(dates[f:], s["eq"][f:] / s["eq"][f - 1:-1] - 1):
                daily[k].setdefault(d, []).append(x)
            trades[k] += s["trades"]
    out = {}
    for k in S.STOPS:
        days = sorted(daily[k])
        r = np.array([np.mean(daily[k][d]) for d in days])
        rs = np.array([t["r"] for t in trades[k]])
        runners = [t for t in trades[k] if t["tp1"] and t["exits"].endswith("trail")]
        out[k] = dict(days=days, ret=r, stats=dict(**summary(r), trades=len(rs), win_rate=float((rs > 0).mean()),
                      mean_r=float(rs.mean()), tp1_rate=float(np.mean([t["tp1"] for t in trades[k]])),
                      runner_near_entry=float(np.mean([abs(t["r"] - .5) <= .1 for t in runners])) if runners else None))
    return out


def main():
    with open(T.OUT.parent / "trend-fresh" / "coins.csv", encoding="utf-8") as f:
        coins = [r["coin"] for r in csv.DictReader(f)]
    dev, conf = split(coins)
    slip, T.SLIP = T.SLIP, .001
    halves = {"development": run_half(dev), "confirmation": run_half(conf)}
    T.SLIP = slip
    res = {h: {k: v["stats"] for k, v in halves[h].items()} for h in halves}
    pick = max(S.STOPS, key=lambda k: res["development"][k]["sharpe"])
    res["chosen_on_development"] = pick
    res["adopt"] = False
    if pick != "base":
        c = halves["confirmation"]
        if c[pick]["days"] != c["base"]["days"]:
            raise ValueError("Confirmation baskets cover different days")
        res["confirmation_sharpe_diff"] = T.bootstrap(c[pick]["ret"], c["base"]["ret"], seed=S.SEED)
        res["adopt"] = res["confirmation_sharpe_diff"]["lo"] > 0
    OUT.mkdir(parents=True, exist_ok=True)
    save_json(OUT / "results.json", res)
    for h in halves:
        for k, v in res[h].items():
            print(h[:4], k.ljust(18), "sharpe", round(v["sharpe"], 2), "cagr", round(v["cagr"], 4), "win", round(v["win_rate"], 3),
                  "meanR", round(v["mean_r"], 3), "runner~BE", v["runner_near_entry"] and round(v["runner_near_entry"], 2))
    print("chosen", pick, "adopt", res["adopt"], res.get("confirmation_sharpe_diff"))


if __name__ == "__main__":
    main()
