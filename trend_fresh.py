"""The frozen trend rule on every older Binance USDT spot pair that no earlier study touched."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from math import comb
from urllib.error import HTTPError

import numpy as np

import trend as T
from flow_data import fetch, save_json
from wave_validation import write_csv

LISTING = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision?delimiter=/"
LAST_FIRST_MONTH = (2021, 12)
SEEN = {"BTC", "ETH", "BNB", "XRP", "ADA", "LTC", "LINK", "DOGE", "SOL"}
STABLE = {"USDC", "BUSD", "TUSD", "USDP", "PAX", "DAI", "FDUSD", "SUSD", "UST", "USTC", "USDS", "USDSB", "EUR", "GBP",
          "AUD", "BRL", "TRY", "RUB", "NGN", "UAH", "BIDR", "IDRT", "BVND", "BKRW", "ZAR", "AEUR", "EURI", "XUSD", "USD1",
          "USDE", "PYUSD", "RLUSD", "USDT"}
LEVERED = ("UP", "DOWN", "BULL", "BEAR")
SLIP = .001
SEED = 20261119
OUT = T.OUT.parent / "trend-fresh"


def listing(prefix):
    keys, marker = [], ""
    while True:
        xml = fetch(f"{LISTING}&prefix={prefix}&marker={marker}").decode()
        found = re.findall(r"<Prefix>([^<]+)</Prefix>", xml)[1:] + re.findall(r"<Key>([^<]+)</Key>", xml)
        keys += found
        if "<IsTruncated>true</IsTruncated>" not in xml or not found:
            return keys
        marker = found[-1]


def eligible(sym):
    b = sym[:-4]
    return sym.endswith("USDT") and b.isascii() and b.isalnum() and b not in SEEN | STABLE and not b.endswith(LEVERED)


def universe():
    syms = sorted(p.rstrip("/").split("/")[-1] for p in listing("data/spot/monthly/klines/"))

    def months(s):
        keys = listing(f"data/spot/monthly/klines/{s}/1d/")
        return s, sorted({(int(y), int(m)) for k in keys for y, m in re.findall(r"-1d-(\d{4})-(\d{2})\.zip$", k)})
    with ThreadPoolExecutor(16) as pool:
        found = dict(pool.map(months, [s for s in syms if eligible(s)]))
    return {s: m for s, m in found.items() if m and m[0] <= LAST_FIRST_MONTH}


def candles(sym, months):
    """Daily candles up to the first gap or invalid row; later rows are dropped."""
    with ThreadPoolExecutor(8) as pool:
        parts = list(pool.map(lambda ym: T.month_rows(sym, *ym), [m for m in months if m <= T.LAST]))
    a = np.array(sorted({r[0]: r for part in parts for r in part}.values()))
    good = (np.isfinite(a).all(1) & (a[:, 1:5] > 0).all(1) & (a[:, 2] >= np.maximum(a[:, 1], a[:, 4]))
            & (a[:, 3] <= np.minimum(a[:, 1], a[:, 4])) & (a[:, 5] >= 0))
    end = len(a)
    for stops in (np.flatnonzero(~good), np.flatnonzero(np.diff(a[:, 0]) != T.DAY_MS) + 1):
        if len(stops):
            end = min(end, int(stops[0]))
    return a[:end]


def sleeves(a):
    """Daily returns of the trend and hold sleeves from the first trade day, or None if under a year."""
    o, c = a[:, 1], a[:, 4]
    if len(c) < T.WARM + 1 + 365:
        return None
    sims = {k: T.simulate(o, c, T.targets(c, k)) for k in ("trend", "bh")}
    f = sims["trend"]["first"]
    if sims["bh"]["first"] != f:
        raise ValueError("Sleeves start on different days")
    out = {k: dict(ret=s["eq"][f:] / s["eq"][f - 1:-1] - 1, costs=s["fees"] + s["slip"], trades=len(s["trades"]))
           for k, s in sims.items()}
    out["days"] = [T.day(t) for t in a[f:, 0]]
    return out


def summary(r):
    eq = np.cumprod(1 + r)
    return dict(sharpe=T.sharpe(r), cagr=float(eq[-1] ** (365 / len(r)) - 1), vol=float(r.std(ddof=1) * np.sqrt(365)),
                maxdd=float((eq / np.maximum.accumulate(eq) - 1).min()), days=len(r))


def basket(daily):
    days = sorted(daily)
    return days, {k: np.array([np.mean(daily[d][k]) for d in days]) for k in ("trend", "bh")}


def sign_p(wins, n):
    return sum(comb(n, j) for j in range(wins, n + 1)) / 2 ** n


def main():
    T.SLIP = SLIP
    uni = universe()
    print(len(uni), "candidate pairs", flush=True)
    per, daily, skipped = {}, {}, {}
    for i, (sym, months) in enumerate(sorted(uni.items())):
        try:
            s = sleeves(candles(sym, months))
        except HTTPError as e:
            skipped[sym] = f"download {e.code}"
            continue
        if s is None:
            skipped[sym] = "under a year after warm-up"
            continue
        for k in ("trend", "bh"):
            for d, r in zip(s["days"], s[k]["ret"]):
                daily.setdefault(d, {}).setdefault(k, []).append(r)
        per[sym] = dict(first_trade=s["days"][0].isoformat(), last_day=s["days"][-1].isoformat(),
                        trend=summary(s["trend"]["ret"]), bh=summary(s["bh"]["ret"]),
                        trend_costs=s["trend"]["costs"], trend_trades=s["trend"]["trades"])
        if i % 25 == 0:
            print(i, sym, flush=True)
    days, b = basket(daily)
    live = [len(daily[d]["trend"]) for d in days]
    later = np.array([d >= date(2024, 1, 1) for d in days])
    wins, n = sum(v["trend"]["sharpe"] > v["bh"]["sharpe"] for v in per.values()), len(per)
    res = dict(coins=n, skipped=skipped, first_day=days[0].isoformat(), last_day=days[-1].isoformat(),
               coins_live_min_median_max=[min(live), int(np.median(live)), max(live)],
               basket={k: summary(v) for k, v in b.items()},
               basket_since_2024={k: summary(v[later]) for k, v in b.items()},
               sharpe_diff=T.bootstrap(b["trend"], b["bh"], seed=SEED),
               sharpe_diff_since_2024=T.bootstrap(b["trend"][later], b["bh"][later], seed=SEED),
               coins_trend_sharpe_above_hold=wins, sign_test_one_sided_p=sign_p(wins, n),
               ended_before_2026_10_31=sum(v["last_day"] < "2026-10-31" for v in per.values()), per_coin=per)
    res["passes"] = res["sharpe_diff"]["lo"] > 0
    OUT.mkdir(parents=True, exist_ok=True)
    save_json(OUT / "results.json", res)
    write_csv(OUT / "coins.csv", [dict(coin=k, first_trade=v["first_trade"], last_day=v["last_day"],
                                       **{f"{r}_{m}": round(v[r][m], 4) for r in ("trend", "bh")
                                          for m in ("sharpe", "cagr", "maxdd")}) for k, v in per.items()])
    plot(days, b, live)
    print({k: v for k, v in res.items() if k not in ("per_coin", "skipped")})


def plot(days, b, live):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    x = np.array(days, dtype="datetime64[D]")
    fig, ax = plt.subplots(3, 1, figsize=(11, 9), sharex=True, gridspec_kw=dict(height_ratios=[3, 1.3, 1]))
    for k, col, name in (("trend", "#1b6ca8", "trend basket"), ("bh", "#777777", "hold basket")):
        eq = np.cumprod(1 + b[k])
        ax[0].plot(x, eq, color=col, label=name)
        ax[1].plot(x, (eq / np.maximum.accumulate(eq) - 1) * 100, color=col)
    ax[0].set(yscale="log", ylabel="growth of 1", title="Untouched coins, equal-weight daily basket (historical simulation)")
    ax[0].legend()
    ax[1].set(ylabel="drawdown %")
    ax[2].plot(x, live, color="#444")
    ax[2].set(ylabel="coins live")
    for a in ax:
        a.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(OUT / "basket.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
