"""Forward paper record for the trend rule on a fixed 30-coin basket, with a weight heatmap and optional Discord post.

Paper only. Nothing here can place an order. Rules: research/trend-basket-paper-plan.md.
"""
import argparse
import io
import json
import os
import time
from datetime import date
from pathlib import Path

import numpy as np

import trend as T
from flow_data import fetch, persist, save_json
from trend_fresh import LEVERED, STABLE
from trend_paper import post
from wave_validation import write_csv

ROOT = Path("data/trend-basket")
KLINES = "https://api.binance.com/api/v3/klines?symbol={}&interval=1d&limit=1000"
TICKER = "https://api.binance.com/api/v3/ticker/24hr"
SCREEN, SIZE, SLIP = 80, 30, .001
SHOW = 90


def candles(sym, now_ms=None):
    """Closed daily candles, keeping only the newest unbroken run of valid days: dates, open, close, quote volume."""
    now_ms = now_ms or time.time() * 1000
    rows = [r for r in json.loads(fetch(KLINES.format(sym))) if r[6] < now_ms]
    if not rows:
        return None
    a = np.array([[float(r[0]), *map(float, r[1:6]), float(r[7])] for r in rows])
    good = (np.isfinite(a).all(1) & (a[:, 1:5] > 0).all(1) & (a[:, 2] >= np.maximum(a[:, 1], a[:, 4]))
            & (a[:, 3] <= np.minimum(a[:, 1], a[:, 4])))
    start = 0 if good[0] else 1
    for i in range(len(a) - 1, 0, -1):
        if not good[i] or a[i, 0] - a[i - 1, 0] != T.DAY_MS:
            start = i + (not good[i])
            break
    a = a[start:]
    if not len(a):
        return None
    return [T.day(t) for t in a[:, 0]], a[:, 1], a[:, 4], a[:, 6]


def eligible(sym):
    b = sym[:-4]
    return sym.endswith("USDT") and b.isascii() and b.isalnum() and b not in STABLE and not b.endswith(LEVERED)


def choose(ticker, history):
    """The fixed universe: screen by 24h volume, then rank by 30-day quote volume among coins with enough history."""
    screened = sorted((t for t in ticker if eligible(t["symbol"])), key=lambda t: -float(t["quoteVolume"]))[:SCREEN]
    ranked = []
    for t in screened:
        h = history(t["symbol"])
        if h and len(h[0]) >= T.WARM + 1:
            ranked.append((float(h[3][-30:].sum()), t["symbol"], h[0][-1]))
    ranked.sort(reverse=True)
    picked = ranked[:SIZE]
    return [s for _, s, _ in picked], min(d for _, _, d in picked)


def sleeve(dates, o, c, start, cap):
    """Trend and hold equity by date from the start close for one coin."""
    w = T.targets(c, "trend")
    first = dates.index(start)
    w[:first] = np.nan
    if np.isnan(w[first]):
        raise ValueError("Not enough history before the start")
    sim = T.simulate(o, c, w, capital=cap)
    hold = c[first:] / c[first] * cap
    days = dates[first:]
    return dict(trend=dict(zip(days, sim["eq"][first:])), hold=dict(zip(days, hold)), held=float(sim["held"][-1]),
                target=float(w[-1]), signal=float(T.signal(c)[-1]), equity=float(sim["eq"][-1]),
                weights=dict(zip(dates[-SHOW:], np.nan_to_num(T.targets(c, "trend")[-SHOW:]))), last=dates[-1],
                trades=len(sim["trades"]))


def flat(start, trend, hold):
    """A sleeve whose coin no longer has usable data: cash at its last recorded values."""
    return dict(trend={start: trend}, hold={start: hold}, held=0., target=0., signal=0., equity=trend,
                weights={}, last=start, trades=0)


def combine(sleeves, day):
    """Basket totals on each date up to day, carrying a finished sleeve's last value forward."""
    days = sorted({d for s in sleeves.values() for d in s["trend"] if d <= day})
    out = {}
    for k in ("trend", "hold"):
        rows = []
        for s in sleeves.values():
            last, vals = None, []
            for d in days:
                last = s[k].get(d, last)
                vals.append(last)
            rows.append(vals)
        out[k] = np.array(rows, dtype=float).sum(0)
    return days, out


def message(day, totals, sleeves, start):
    moves = [f"{'BUY' if s['target'] > s['held'] else 'SELL'} {sym[:-4]} {s['held']:.0%}->{s['target']:.0%}"
             for sym, s in sorted(sleeves.items()) if s["last"] == day and abs(s["target"] - s["held"]) > T.BAND]
    invested = sum(s["held"] > 1e-6 for s in sleeves.values())
    t, h = totals["trend"], totals["hold"]
    lines = [f"**TREND BASKET PAPER · close {day} UTC** · {len(sleeves)} coins · paper record only, no orders placed",
             f"Basket {t[-1]:,.2f} vs hold {h[-1]:,.2f} USDT since {start} ({t[-1] / t[0] - 1:+.1%} vs {h[-1] / h[0] - 1:+.1%})",
             f"Holding a position in {invested} of {len(sleeves)} coins",
             "Next open: " + (", ".join(moves[:15]) + (f" and {len(moves) - 15} more" if len(moves) > 15 else "")
                              if moves else "no trades")]
    return "\n".join(lines)[:2000]


def chart(day, days, totals, sleeves):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    syms = sorted(sleeves, key=lambda s: -sleeves[s]["target"])
    cols = sorted({d for s in sleeves.values() for d in s["weights"]})[-SHOW:]
    grid = np.array([[sleeves[s]["weights"].get(d, np.nan) for d in cols] for s in syms])
    fig = plt.figure(figsize=(14, 12))
    g = fig.add_gridspec(3, 2, height_ratios=[1.2, 3, .1], width_ratios=[4, 1])
    e = fig.add_subplot(g[0, :])
    x = np.array(days, dtype="datetime64[D]")
    e.plot(x, totals["trend"], marker=".", color="#1b6ca8", label="trend basket (paper)")
    e.plot(x, totals["hold"], marker=".", color="#777", label="hold basket")
    e.set(ylabel="USDT", title=f"Trend basket paper record through {day} · no orders placed")
    e.legend(fontsize=8)
    e.grid(alpha=.3)
    h = fig.add_subplot(g[1, 0])
    im = h.imshow(grid, aspect="auto", cmap="Blues", vmin=0, vmax=1, interpolation="nearest")
    h.set_yticks(range(len(syms)), [s[:-4] for s in syms], fontsize=7)
    ticks = list(range(0, len(cols), 15))
    h.set_xticks(ticks, [cols[i].isoformat() for i in ticks], rotation=30, fontsize=7)
    h.set_title("Rule target weight by coin, last 90 closes", fontsize=9)
    fig.colorbar(im, cax=fig.add_subplot(g[2, 0]), orientation="horizontal", label="target weight")
    b = fig.add_subplot(g[1, 1], sharey=h)
    b.barh(range(len(syms)), [sleeves[s]["target"] for s in syms],
           color=["#2a9d58" if sleeves[s]["signal"] > .5 else "#e08a1e" if sleeves[s]["signal"] > 0 else "#c8423b"
                  for s in syms])
    b.set(xlim=(0, 1), title="Today's target")
    b.title.set_fontsize(9)
    b.tick_params(labelleft=False)
    b.grid(alpha=.3, axis="x")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100)
    plt.close(fig)
    return buf.getvalue()


def run(force=False, root=ROOT, history=candles, ticker=None):
    state_path = root / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    slip, T.SLIP = T.SLIP, SLIP
    try:
        if "universe" not in state:
            uni, start = choose(ticker if ticker is not None else json.loads(fetch(TICKER)), history)
            state.update(universe=uni, start=start.isoformat())
        start = date.fromisoformat(state["start"])
        cap = T.CAPITAL / len(state["universe"])
        frozen = state.setdefault("frozen", {})
        sleeves = {}
        for sym in state["universe"]:
            h = history(sym)
            if h and start in h[0]:
                s = sleeves[sym] = sleeve(h[0], h[1], h[2], start, cap)
                frozen[sym] = dict(trend=s["equity"], hold=float(list(s["hold"].values())[-1]))
            else:
                last = frozen.get(sym, dict(trend=cap, hold=cap))
                sleeves[sym] = flat(start, last["trend"], last["hold"])
        day = max(s["last"] for s in sleeves.values())
        days, totals = combine(sleeves, day)
    finally:
        T.SLIP = slip
    text, png = message(day, totals, sleeves, start), chart(day, days, totals, sleeves)
    persist(root / f"{day}.png", png)
    persist(root / f"{day}.txt", text.encode())
    if not any(r["date"] == day.isoformat() for r in state.setdefault("ledger", [])):
        state["ledger"].append(dict(date=day.isoformat(), trend=round(float(totals["trend"][-1]), 2),
                                    hold=round(float(totals["hold"][-1]), 2),
                                    invested=sum(s["held"] > 1e-6 for s in sleeves.values())))
    write_csv(root / "ledger.csv", state["ledger"])
    write_csv(root / "positions.csv", [dict(coin=k, target=round(s["target"], 4), held=round(s["held"], 4),
                                            equity=round(s["equity"], 2), last_close=s["last"].isoformat())
                                       for k, s in sorted(sleeves.items())])
    hook = os.environ.get("DISCORD_WEBHOOK_URL")
    if hook and (force or state.get("posted") != day.isoformat()):
        post(hook, text, png)
        state["posted"] = day.isoformat()
        print("posted to Discord")
    elif not hook:
        print(f"DISCORD_WEBHOOK_URL not set; saved {root / (day.isoformat() + '.png')} instead of posting")
    save_json(state_path, state)
    print(text)
    return state, totals


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true", help="post again even if this close was already posted")
    run(p.parse_args().force)
