"""Volatility-targeted trend on Binance spot BTC and ETH, with buy-and-hold and vol-target controls."""
import io
import json
from datetime import date, datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import numpy as np

from flow_data import fetch, persist, save_json
from wave_validation import write_csv

CAPITAL = 10_000.
LOOKS = (20, 60, 120)
VOL_WIN, TARGET_VOL, BAND = 30, .40, .10
FEE, SLIP = .001, .0002
WARM = 120 + 30  # days of history before the first decision
COINS = ("BTCUSDT", "ETHUSDT")
FIRST, LAST = (2018, 1), (2026, 10)
SEED, RESAMPLES, BLOCK = 20260101, 5000, 60
CACHE = Path("data/trend")
OUT = Path("research/trend")
ARCHIVE = "https://data.binance.vision/data/spot/monthly/klines"
RULES = ("trend", "vt", "bh")
DAY_MS = 86_400_000


def norm_ts(t):
    """Open time in ms; the archive switches to microseconds from 2025-01."""
    t = int(t)
    return t // 1000 if len(str(abs(t))) >= 16 else t


def month_rows(sym, y, m):
    name = f"{sym}-1d-{y}-{m:02d}"
    path = CACHE / sym / f"{name}.zip"
    if not path.exists():
        persist(path, fetch(f"{ARCHIVE}/{sym}/1d/{name}.zip"))
    with ZipFile(io.BytesIO(path.read_bytes())) as z:
        text = z.read(z.namelist()[0]).decode()
    return [(norm_ts(r[0]), *map(float, r[1:6])) for r in (l.split(",") for l in text.splitlines() if l)]


def load(sym, first=FIRST, last=LAST):
    rows, (y, m) = [], first
    while (y, m) <= last:
        rows += month_rows(sym, y, m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    a = np.array(rows)
    validate(a, sym)
    return a


def day(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date()


def validate(a, sym=""):
    t, o, h, l, c = (a[:, i] for i in range(5))
    gaps = np.flatnonzero(np.diff(t) != DAY_MS)
    if len(gaps) or (t % DAY_MS).any():
        raise ValueError(f"{sym} missing or misaligned days near {[day(t[i]).isoformat() for i in gaps[:5]]}")
    if not (np.isfinite(a).all() and (a[:, 1:5] > 0).all() and (h >= np.maximum(o, c)).all()
            and (l <= np.minimum(o, c)).all() and (a[:, 5] >= 0).all()):
        raise ValueError(f"{sym} failed OHLC sanity checks")


def signal(c):
    """Share of 20/60/120-day returns positive at each close; nan until 120 prior closes exist."""
    s = np.full(len(c), np.nan)
    for t in range(max(LOOKS), len(c)):
        s[t] = sum(c[t] > c[t - k] for k in LOOKS) / len(LOOKS)
    return s


def scale(c):
    """Target vol over the annualised sample std of the last 30 log returns, capped at 1."""
    r, s = np.diff(np.log(c)), np.full(len(c), np.nan)
    for t in range(VOL_WIN, len(c)):
        v = r[t - VOL_WIN:t].std(ddof=1) * np.sqrt(365)
        s[t] = 1. if v == 0 else min(1., TARGET_VOL / v)
    return s


def targets(c, rule):
    """Weight decided at the close of each day, from closes up to and including it."""
    sig, sc = signal(c), scale(c)
    w = {"trend": sig * sc, "vt": np.where(np.isnan(sig), np.nan, sc), "bh": np.where(np.isnan(sig), np.nan, 1.)}[rule]
    w[:WARM] = np.nan
    return w


def simulate(o, c, w, band=BAND, capital=CAPITAL):
    """Decide at close t-1, trade at open t, mark at close t. Returns equity at closes and the ledger."""
    n, first = len(c), int(np.flatnonzero(~np.isnan(w))[0]) + 1
    cash, q, eq, held = capital, 0., np.full(n, np.nan), np.zeros(n)
    fee_paid = slip_paid = 0.
    trades = []
    eq[first - 1] = capital
    for i in range(first, n):
        cur = q * c[i - 1] / eq[i - 1]
        if abs(w[i - 1] - cur) > band:
            d = w[i - 1] * (cash + q * o[i]) - q * o[i]  # notional to buy (+) or sell (-) at the open
            d = min(d, cash / (1 + FEE + SLIP)) if d > 0 else max(d, -q * o[i])
            cash -= d + abs(d) * (FEE + SLIP)
            q += d / o[i]
            fee_paid += abs(d) * FEE
            slip_paid += abs(d) * SLIP
            trades.append((i, d))
        eq[i] = cash + q * c[i]
        held[i] = q * c[i] / eq[i]
    return dict(eq=eq, held=held, first=first, fees=fee_paid, slip=slip_paid, trades=trades)


def sharpe(r):
    s = r.std(ddof=1)
    return float(r.mean() / s * np.sqrt(365)) if s > 0 else 0.


def stats(s, lo):
    """Metrics over the equity closes from index lo (the base) to the end; costs from trades after lo."""
    e, h = s["eq"][lo:], s["held"][lo + 1:]
    r = e[1:] / e[:-1] - 1
    yrs = len(r) / 365
    tr = sum(abs(d) for i, d in s["trades"] if i > lo)
    return dict(days=len(r), cagr=float((e[-1] / e[0]) ** (1 / yrs) - 1), vol=float(r.std(ddof=1) * np.sqrt(365)),
                sharpe=sharpe(r), maxdd=float((e / np.maximum.accumulate(e) - 1).min()),
                invested=float((h > 1e-6).mean()), turnover_per_year=float(tr / e.mean() / yrs), traded_usdt=float(tr),
                fees=float(tr * FEE), slippage=float(tr * SLIP), net_usdt=float(e[-1] - e[0]), final=float(e[-1]))


def periodic(s, dates, key):
    """Return per calendar bucket (key(date)) from the previous bucket's last close; first bucket from the base."""
    out, prev = {}, s["eq"][s["first"] - 1]
    for i in range(s["first"], len(dates)):
        if i + 1 == len(dates) or key(dates[i + 1]) != key(dates[i]):
            out[key(dates[i])] = float(s["eq"][i] / prev - 1)
            prev = s["eq"][i]
    return out


def episodes(s):
    """Runs of consecutive invested days; an episode wins when the compounded account return is positive."""
    wins = runs = 0
    cur = None
    for i in range(s["first"], len(s["eq"])):
        on = s["held"][i] > 1e-6
        if on:
            cur = s["eq"][i] / s["eq"][i - 1] * (1 if cur is None else cur)
        if (not on or i == len(s["eq"]) - 1) and cur is not None:
            runs, wins, cur = runs + 1, wins + (cur > 1), None
    return dict(episodes=runs, win_rate=wins / runs if runs else None)


def bootstrap(a, b, seed=SEED, n=RESAMPLES, block=BLOCK):
    """95% CI of Sharpe(a)-Sharpe(b) from moving-block resamples of the paired daily returns."""
    rng, m = np.random.default_rng(seed), len(a)
    k = -(-m // block)
    idx = (rng.integers(0, m - block + 1, (n, k))[:, :, None] + np.arange(block)).reshape(n, -1)[:, :m]
    sa, sb = a[idx], b[idx]
    d = (sa.mean(1) / sa.std(1, ddof=1) - sb.mean(1) / sb.std(1, ddof=1)) * np.sqrt(365)
    lo, hi = np.percentile(d, [2.5, 97.5])
    return dict(point=sharpe(a) - sharpe(b), lo=float(lo), hi=float(hi), share_above_zero=float((d > 0).mean()))


def study(sym, first=FIRST, last=LAST):
    a = load(sym, first, last)
    dates = [day(t) for t in a[:, 0]]
    o, c = a[:, 1], a[:, 4]
    tg = {k: targets(c, k) for k in RULES}
    sims = {k: simulate(o, c, tg[k]) for k in RULES}
    f = sims["trend"]["first"]
    sub = next(i for i in range(f, len(dates)) if dates[i] >= date(2024, 1, 1)) - 1  # base is the 2023-12-31 close
    res = dict(first_data=dates[0].isoformat(), last_data=dates[-1].isoformat(), first_decision=dates[f - 1].isoformat(),
               first_trade=dates[f].isoformat(), rules={}, monthly={})
    rets = {k: s["eq"][f:] / s["eq"][f - 1:-1] - 1 for k, s in sims.items()}
    for k, s in sims.items():
        res["rules"][k] = dict(full=stats(s, f - 1), since_2024=stats(s, sub), trades=len(s["trades"]),
                               calendar=periodic(s, dates, lambda d: d.year), **episodes(s))
        res["monthly"][k] = periodic(s, dates, lambda d: f"{d.year}-{d.month:02d}")
    j = sub - (f - 1)
    res["bootstrap"] = {f"trend_minus_{k}": bootstrap(rets["trend"], rets[k]) for k in ("bh", "vt")}
    res["bootstrap_since_2024"] = {f"trend_minus_{k}": bootstrap(rets["trend"][j:], rets[k][j:]) for k in ("bh", "vt")}
    return res, dict(dates=dates, sims=sims, targets=tg)


def verdict(res):
    ci = any(res[s]["bootstrap"]["trend_minus_bh"]["lo"] > 0 for s in COINS)
    late = all(res[s]["rules"]["trend"]["since_2024"]["sharpe"] >= res[s]["rules"]["bh"]["since_2024"]["sharpe"] for s in COINS)
    return dict(ci_above_zero_for_a_coin=ci, sharpe_2024_not_below_hold_both=late, passes=ci and late)


def plots(data, res):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    col = dict(trend="#1b6ca8", vt="#e08a1e", bh="#777777")
    names = dict(trend="trend", vt="vol-target hold", bh="buy and hold")
    fig, ax = plt.subplots(2, 2, figsize=(13, 8), sharex="col")
    for j, s in enumerate(COINS):
        d = data[s]
        f = d["sims"]["trend"]["first"]
        x = np.array(d["dates"][f - 1:], dtype="datetime64[D]")
        for k in RULES:
            e = d["sims"][k]["eq"][f - 1:]
            ax[0, j].plot(x, e, color=col[k], lw=1.2, label=names[k])
            ax[1, j].plot(x, (e / np.maximum.accumulate(e) - 1) * 100, color=col[k], lw=1)
        ax[0, j].set(title=f"{s} equity from 10,000 USDT (historical simulation)", yscale="log", ylabel="USDT")
        ax[1, j].set(title="Drawdown", ylabel="%")
        ax[0, j].legend()
        for a in ax[:, j]:
            a.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(OUT / "equity-drawdown.png", dpi=130)
    plt.close(fig)
    fig, ax = plt.subplots(2, 3, figsize=(16, 9))
    for i, s in enumerate(COINS):
        for j, k in enumerate(RULES):
            m = {tuple(map(int, kk.split("-"))): v for kk, v in res[s]["monthly"][k].items()}
            ys = sorted({y for y, _ in m})
            g = np.array([[m.get((y, mo), np.nan) for mo in range(1, 13)] for y in ys]) * 100
            im = ax[i, j].imshow(g, cmap="RdBu", vmin=-40, vmax=40, aspect="auto")
            ax[i, j].set(title=f"{s} {names[k]}: monthly %", xticks=range(12), xticklabels=list("JFMAMJJASOND"),
                         yticks=range(len(ys)), yticklabels=ys)
            ax[i, j].title.set_fontsize(10)
            for (r, cc), v in np.ndenumerate(g):
                if not np.isnan(v):
                    ax[i, j].text(cc, r, f"{v:.0f}", ha="center", va="center", fontsize=6)
    fig.colorbar(im, ax=ax, shrink=.6, label="%")
    fig.savefig(OUT / "monthly-heatmap.png", dpi=130)
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    res, data = {}, {}
    for s in COINS:
        res[s], data[s] = study(s)
    res["verdict"] = verdict(res)
    res["parameters"] = dict(lookbacks=LOOKS, vol_window=VOL_WIN, target_vol=TARGET_VOL, band=BAND, fee=FEE, slippage=SLIP,
                             warmup_days=WARM, capital=CAPITAL, seed=SEED, resamples=RESAMPLES, block=BLOCK)
    save_json(OUT / "results.json", res)
    rows = []
    for i, d in enumerate(data[COINS[0]]["dates"]):
        if np.isnan(data[COINS[0]]["sims"]["trend"]["eq"][i]):
            continue
        row = {"date": d.isoformat()}
        for s in COINS:
            for k in RULES:
                p, t = data[s]["sims"][k], data[s]["targets"][k][i]
                row[f"{s}_{k}_target"] = "" if np.isnan(t) else round(float(t), 6)
                row[f"{s}_{k}_held"] = round(float(p["held"][i]), 6)
                row[f"{s}_{k}_equity"] = round(float(p["eq"][i]), 2)
        rows.append(row)
    write_csv(OUT / "daily.csv", rows)
    plots(data, res)
    for s in COINS:
        print(s, res[s]["first_data"], res[s]["last_data"], "first trade", res[s]["first_trade"])
        for k in RULES:
            f = res[s]["rules"][k]["full"]
            print(f"  {k:5s} cagr {f['cagr']:.1%} sharpe {f['sharpe']:.2f} maxdd {f['maxdd']:.1%} inv {f['invested']:.0%} fees {f['fees'] + f['slippage']:.0f} net {f['net_usdt']:.0f}")
    print(json.dumps(res["verdict"]))


if __name__ == "__main__":
    main()
