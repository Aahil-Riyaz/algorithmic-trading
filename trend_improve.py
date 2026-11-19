"""Pick a trend-basket change on half the untouched coins and confirm it on the other half."""
import csv
import re
from datetime import date

import numpy as np

import trend as T
from flow_data import save_json
from trend_fresh import SLIP, candles, summary

SEED = 20261120
MIN_QUOTE = 1_000_000
CANDIDATES = ("base", "regime", "liquidity", "both")
OUT = T.OUT.parent / "trend-improve"


def split(coins, seed=SEED):
    order = np.random.default_rng(seed).permutation(len(coins))
    half = len(coins) // 2
    return [coins[i] for i in order[:half]], [coins[i] for i in order[half:]]


def months(sym):
    return sorted({(int(y), int(m)) for p in (T.CACHE / sym).glob("*.zip")
                   for y, m in re.findall(r"-1d-(\d{4})-(\d{2})\.zip$", p.name)})


def regime(btc_dates, btc_close):
    """BTC trend signal decided at each close, by date."""
    return dict(zip(btc_dates, T.signal(btc_close)))


def liquid(close, volume, floor=MIN_QUOTE):
    """True where the mean of base volume times close over the last 30 closes, through this one, reaches the floor."""
    qv = close * volume
    out = np.zeros(len(qv), bool)
    for i in range(29, len(qv)):
        out[i] = qv[i - 29:i + 1].mean() >= floor
    return out


def weights(dates, close, volume, btc, name):
    w = T.targets(close, "trend")
    keep = np.ones(len(w), bool)
    if name in ("regime", "both"):
        keep &= np.array([btc.get(d, 0) > 0 for d in dates])
    if name in ("liquidity", "both"):
        keep &= liquid(close, volume)
    return np.where(np.isnan(w), np.nan, w * keep)


def run_half(coins, btc):
    """Equal-weight daily basket returns for each candidate, averaging the coins live on each day."""
    daily = {k: {} for k in CANDIDATES}
    invested = {k: [] for k in CANDIDATES}
    for sym in coins:
        a = candles(sym, months(sym))
        if len(a) < T.WARM + 1 + 365:
            continue
        dates = [T.day(t) for t in a[:, 0]]
        o, c, v = a[:, 1], a[:, 4], a[:, 5]
        sims = {k: T.simulate(o, c, weights(dates, c, v, btc, k)) for k in CANDIDATES}
        f = sims["base"]["first"]
        for k, s in sims.items():
            if s["first"] != f:
                raise ValueError(f"{sym} candidates start on different days")
            for d, x in zip(dates[f:], s["eq"][f:] / s["eq"][f - 1:-1] - 1):
                daily[k].setdefault(d, []).append(x)
            invested[k].append(float((s["held"][f:] > 1e-6).mean()))
    out = {}
    for k in CANDIDATES:
        days = sorted(daily[k])
        out[k] = dict(days=days, ret=np.array([np.mean(daily[k][d]) for d in days]), invested=float(np.mean(invested[k])))
    return out


def report(half):
    return {k: dict(**summary(v["ret"]), invested=v["invested"]) for k, v in half.items()}


def main():
    T.SLIP = SLIP
    with open(T.OUT.parent / "trend-fresh" / "coins.csv", encoding="utf-8") as f:
        coins = [r["coin"] for r in csv.DictReader(f)]
    dev, conf = split(coins)
    b = T.load("BTCUSDT")
    btc = regime([T.day(t) for t in b[:, 0]], b[:, 4])
    halves = {"development": run_half(dev, btc), "confirmation": run_half(conf, btc)}
    res = dict(seed=SEED, development_coins=dev, confirmation_coins=conf,
               development=report(halves["development"]), confirmation=report(halves["confirmation"]))
    pick = max(CANDIDATES, key=lambda k: res["development"][k]["sharpe"])
    res["chosen_on_development"] = pick
    if pick != "base":
        c = halves["confirmation"]
        if c[pick]["days"] != c["base"]["days"]:
            raise ValueError("Confirmation baskets cover different days")
        res["confirmation_sharpe_diff"] = T.bootstrap(c[pick]["ret"], c["base"]["ret"], seed=SEED)
        res["adopt"] = res["confirmation_sharpe_diff"]["lo"] > 0
    else:
        res["adopt"] = False
    later = {h: np.array([d >= date(2024, 1, 1) for d in halves[h]["base"]["days"]]) for h in halves}
    res["since_2024"] = {h: {k: summary(v["ret"][later[h]]) for k, v in halves[h].items()} for h in halves}
    OUT.mkdir(parents=True, exist_ok=True)
    save_json(OUT / "results.json", res)
    for h in ("development", "confirmation"):
        print(h, {k: (round(v["sharpe"], 2), round(v["cagr"], 3), round(v["maxdd"], 2), round(v["invested"], 2))
                  for k, v in res[h].items()})
    print("chosen", pick, "adopt", res["adopt"], res.get("confirmation_sharpe_diff"))


if __name__ == "__main__":
    main()
