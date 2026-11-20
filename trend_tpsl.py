"""Long-only stop-and-target trades taken only when the trend signal is fully on. Rules: research/trend-tpsl-plan.md."""
import csv
from datetime import date

import numpy as np

import trend as T
from flow_data import save_json
from trend_fresh import candles, summary
from trend_improve import months
from wave_validation import write_csv

COST = .002  # 10 bp fee plus 10 bp slippage per side
RISK, MAX_LEV, BORROW = .02, 2., .0003
ATR_N, STOP_ATR, TP1_R, TP2_R, TIMEOUT = 14, 2., 1., 3., 30
SEED = 20261121
OUT = T.OUT.parent / "trend-tpsl"


def true_range(h, l, c):
    prev = np.r_[c[0], c[:-1]]
    return np.maximum(h - l, np.maximum(abs(h - prev), abs(l - prev)))


def simulate(o, h, l, c, sig, capital=T.CAPITAL):
    """Daily equity at closes from the first possible decision, and one record per closed trade.

    Decisions use the close; entries and trend exits fill at the next open. Within a day the stop is checked first."""
    n, tr = len(c), true_range(h, l, c)
    first = max(int(np.flatnonzero(~np.isnan(sig))[0]), ATR_N)
    eq, held = np.full(n, np.nan), np.zeros(n)
    eq[first] = capital
    state = dict(cash=capital, qty=0.)
    pos, trades, gaps, enter, leave = None, [], 0, False, False

    def sell(units, px, day, why):
        state["cash"] += units * px * (1 - COST)
        state["qty"] -= units
        pos["pnl"] += units * (px * (1 - COST) - pos["basis"])
        pos["exits"].append(why)
        if state["qty"] <= 1e-12 * pos["units"]:
            state["qty"] = 0.
            trades.append(dict(entry_day=pos["day"], exit_day=day, r=pos["pnl"] / pos["risk"],
                               exits="+".join(pos["exits"]), tp1=pos["tp1"], tp2="tp2" in pos["exits"]))
            return True
        return False

    for i in range(first + 1, n):
        if pos and leave:
            sell(state["qty"], o[i], i, "trend")
            pos = None
        elif pos is None and enter:
            atr = tr[i - ATR_N:i].mean()
            stop = o[i] - STOP_ATR * atr
            if stop > 0:
                e = state["cash"] + state["qty"] * c[i - 1]
                units = min(RISK * e / (o[i] - stop), MAX_LEV * e / o[i])
                state["cash"] -= units * o[i] * (1 + COST)
                state["qty"] = units
                pos = dict(day=i, entry=o[i], stop=stop, r=o[i] - stop, atr=atr, high=-np.inf, tp1=False, pnl=0.,
                           basis=o[i] * (1 + COST), risk=units * (o[i] - stop), units=units, exits=[])
                if l[i] <= stop:
                    sell(state["qty"], stop, i, "stop")
                    pos = None
        elif pos:
            gaps += o[i] < .5 * c[i - 1]
            if l[i] <= pos["stop"]:
                sell(state["qty"], min(pos["stop"], o[i]), i, "trail" if pos["tp1"] else "stop")
                pos = None
            else:
                if not pos["tp1"] and h[i] >= pos["entry"] + TP1_R * pos["r"]:
                    sell(state["qty"] / 2, pos["entry"] + TP1_R * pos["r"], i, "tp1")
                    pos["tp1"] = True
                if h[i] >= pos["entry"] + TP2_R * pos["r"]:
                    sell(state["qty"], pos["entry"] + TP2_R * pos["r"], i, "tp2")
                    pos = None
                elif i - pos["day"] >= TIMEOUT:
                    sell(state["qty"], c[i], i, "timeout")
                    pos = None
        if pos:
            pos["high"] = max(pos["high"], c[i])
            if pos["tp1"]:  # the trail set at this close applies from the next day
                pos["stop"] = max(pos["stop"], pos["entry"], pos["high"] - STOP_ATR * pos["atr"])
        state["cash"] -= BORROW * max(0., -state["cash"])
        eq[i] = state["cash"] + state["qty"] * c[i]
        held[i] = state["qty"] * c[i] / eq[i]
        enter = pos is None and sig[i] == 1
        leave = pos is not None and sig[i] <= 1 / 3
    return dict(eq=eq, held=held, first=first, trades=trades, gaps=int(gaps))


def sharpe_interval(r, seed=SEED, n=5000, block=60):
    """95% moving-block bootstrap interval for the annualised Sharpe of one daily return series."""
    rng, m = np.random.default_rng(seed), len(r)
    idx = (rng.integers(0, m - block + 1, (n, -(-m // block)))[:, :, None] + np.arange(block)).reshape(n, -1)[:, :m]
    s = r[idx].mean(1) / r[idx].std(1, ddof=1) * np.sqrt(365)
    return dict(point=T.sharpe(r), lo=float(np.percentile(s, 2.5)), hi=float(np.percentile(s, 97.5)))


def main():
    with open(T.OUT.parent / "trend-fresh" / "coins.csv", encoding="utf-8") as f:
        coins = [r["coin"] for r in csv.DictReader(f)]
    slip, T.SLIP = T.SLIP, .001
    daily = {k: {} for k in ("tpsl", "trend", "hold")}
    trades, invested, gaps = [], [], 0
    for sym in coins:
        a = candles(sym, months(sym))
        if len(a) < T.WARM + 1 + 365:
            continue
        dates = [T.day(t) for t in a[:, 0]]
        o, h, l, c = a[:, 1], a[:, 2], a[:, 3], a[:, 4]
        sig = T.signal(c)
        sig[:T.WARM] = np.nan
        s = simulate(o, h, l, c, sig)
        base = T.simulate(o, c, T.targets(c, "trend"))
        f = base["first"]
        if s["first"] + 1 != f:
            raise ValueError(f"{sym} start mismatch")
        series = dict(tpsl=s["eq"][f:] / s["eq"][f - 1:-1] - 1, trend=base["eq"][f:] / base["eq"][f - 1:-1] - 1,
                      hold=c[f:] / c[f - 1:-1] - 1)
        for k, r in series.items():
            for d, x in zip(dates[f:], r):
                daily[k].setdefault(d, []).append(x)
        trades += [dict(coin=sym, entry=dates[t["entry_day"]].isoformat(), exit=dates[t["exit_day"]].isoformat(),
                        r=round(t["r"], 4), exits=t["exits"], tp1=t["tp1"], tp2=t["tp2"]) for t in s["trades"]]
        invested.append(float((s["held"][f:] > 1e-9).mean()))
        gaps += s["gaps"]
    T.SLIP = slip
    rs = np.array([t["r"] for t in trades])
    res = dict(coins=len(invested), trades=len(trades), gap_days_over_50pct=gaps,
               trade_stats=dict(win_rate=float((rs > 0).mean()), mean_r=float(rs.mean()), median_r=float(np.median(rs)),
                                tp1_rate=float(np.mean([t["tp1"] for t in trades])),
                                tp2_rate=float(np.mean([t["tp2"] for t in trades])),
                                time_in_trade=float(np.mean(invested))))
    for k in daily:
        days = sorted(daily[k])
        r = np.array([np.mean(daily[k][d]) for d in days])
        later = np.array([d >= date(2024, 1, 1) for d in days])
        res[k] = dict(full=summary(r), since_2024=summary(r[later]))
        if k == "tpsl":
            res["sharpe_interval"] = sharpe_interval(r)
    res["passes"] = res["sharpe_interval"]["lo"] > 0 and res["tpsl"]["since_2024"]["cagr"] > 0
    OUT.mkdir(parents=True, exist_ok=True)
    save_json(OUT / "results.json", res)
    write_csv(OUT / "trades.csv", trades)
    print(res)


if __name__ == "__main__":
    main()
