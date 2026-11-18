"""Forward paper record for the frozen trend rule, with an annotated chart and an optional Discord webhook post.

Paper only. Nothing here can place an order. The record starts on the first run and is replayed from closed
daily candles each time, so rerunning on the same day changes nothing.
"""
import argparse
import io
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

import numpy as np

import trend as T
from flow_data import fetch, persist, save_json
from wave_validation import write_csv

ROOT = Path("data/trend-paper")
URL = "https://api.binance.com/api/v3/klines?symbol={}&interval=1d&limit=1000"
SHOW = 180


def closed_candles(sym, now_ms=None):
    """Daily candles whose close time has passed: (dates, open, high, low, close)."""
    now_ms = now_ms or time.time() * 1000
    rows = [r for r in json.loads(fetch(URL.format(sym))) if r[6] < now_ms]
    a = np.array([[float(r[0]), *map(float, r[1:5]), float(r[5])] for r in rows])
    T.validate(a, sym)
    return [T.day(t) for t in a[:, 0]], a[:, 1], a[:, 2], a[:, 3], a[:, 4]


def levels(c):
    """Prices tomorrow's close must beat for each lookback to count as up (tomorrow's c[t+1-k])."""
    return {k: float(c[-k]) for k in T.LOOKS}


def replay(dates, o, c, start):
    """Run the frozen rule from the start date; earlier days only supply history."""
    w = T.targets(c, "trend")
    first = dates.index(start)
    w[:first] = np.nan
    if np.isnan(w[first]):
        raise ValueError("Not enough history before the paper start date")
    sim = T.simulate(o, c, w)
    bh = c[first:] / c[first] * T.CAPITAL
    return w, sim, first, bh


def summary(sym, dates, o, c, start):
    w, sim, first, bh = replay(dates, o, c, start)
    held, target, eq = float(sim["held"][-1]), float(w[-1]), float(sim["eq"][-1])
    action = "HOLD" if abs(target - held) <= T.BAND else ("BUY" if target > held else "SELL")
    return dict(coin=sym, date=dates[-1].isoformat(), close=float(c[-1]), signal=float(T.signal(c)[-1]),
                scale=float(T.scale(c)[-1]), target=target, held=held, action=action,
                change_usdt=(target - held) * eq, equity=eq, hold_equity=float(bh[-1]),
                trades=len(sim["trades"]), levels=levels(c), start=start.isoformat()), (w, sim, first, bh)


def message(rows):
    lines = [f"**TREND PAPER · daily close {rows[0]['date']} UTC** · paper record only, no orders placed"]
    for r in rows:
        lv = " / ".join(f"{k}d {v:,.2f}" for k, v in r["levels"].items())
        move = ("no trade at next open" if r["action"] == "HOLD" else
                f"{r['action']} {abs(r['change_usdt']):,.0f} USDT of spot at next open")
        lines += [f"**{r['coin']}** close {r['close']:,.2f} · signal {r['signal'] * 3:.0f}/3 · vol scale {r['scale']:.2f}",
                  f"Target {r['target']:.0%} vs held {r['held']:.0%} -> {move}",
                  f"Trend levels for tomorrow's close: {lv}",
                  f"Paper equity {r['equity']:,.2f} vs hold {r['hold_equity']:,.2f} USDT since {r['start']} ({r['trades']} trades)"]
    lines.append("Historical test failed its 95% bar; this forward record is the evidence that counts.")
    return "\n".join(lines)


def chart(panels):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(3, len(panels), figsize=(7 * len(panels), 10), sharex="col",
                           gridspec_kw=dict(height_ratios=[3, 1, 1.2]), squeeze=False)
    for j, (r, dates, o, h, l, c, (w, sim, first, bh)) in enumerate(panels):
        n = len(c)
        lo = max(0, n - SHOW)
        x = np.arange(lo, n)
        colour = np.where(c[lo:] >= o[lo:], "#2a9d58", "#c8423b")
        p = ax[0, j]
        p.vlines(x, l[lo:], h[lo:], color=colour, lw=.8)
        p.bar(x, np.abs(c[lo:] - o[lo:]), bottom=np.minimum(o[lo:], c[lo:]), width=.7, color=colour)
        for (k, v), col in zip(r["levels"].items(), ("#1b6ca8", "#e08a1e", "#7b3fa0")):
            p.axhline(v, color=col, ls="--", lw=1)
            p.annotate(f"{k}d level {v:,.0f}", (n - 1, v), xytext=(4, 2), textcoords="offset points",
                       color=col, fontsize=8)
        if first >= lo:
            p.axvline(first, color="#555", lw=1, ls=":")
            p.annotate("paper start", (first, p.get_ylim()[1]), fontsize=8, va="top", color="#555")
        p.set(title=f"{r['coin']} daily · {r['action']} · target {r['target']:.0%} · signal {r['signal'] * 3:.0f}/3",
              ylabel="USDT")
        q = ax[1, j]
        q.step(x, np.nan_to_num(T.targets(c, "trend")[lo:]), where="post", color="#1b6ca8", label="rule target")
        q.fill_between(x, sim["held"][lo:], step="post", color="#1b6ca8", alpha=.2, label="paper held")
        q.set(ylim=(0, 1.05), ylabel="weight")
        q.legend(fontsize=8, loc="upper left")
        e = ax[2, j]
        xs = np.arange(first, n)
        e.plot(xs, sim["eq"][first:], color="#1b6ca8", marker=".", label="paper trend")
        e.plot(xs, bh, color="#777", marker=".", label="hold")
        e.set(ylabel="USDT")
        e.legend(fontsize=8, loc="upper left")
        ticks = x[::30]
        e.set_xticks(ticks, [dates[i].isoformat() for i in ticks], rotation=30, fontsize=8)
        for a in ax[:, j]:
            a.grid(alpha=.3)
    fig.suptitle("Paper record only. No orders placed.", fontsize=9, color="#555")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    plt.close(fig)
    return buf.getvalue()


def multipart(text, png):
    boundary = uuid.uuid4().hex
    payload = json.dumps(dict(content=text[:2000], allowed_mentions=dict(parse=[])))
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="payload_json"\r\n'
             f'Content-Type: application/json\r\n\r\n{payload}\r\n'.encode(),
             f'--{boundary}\r\nContent-Disposition: form-data; name="files[0]"; filename="trend.png"\r\n'
             'Content-Type: image/png\r\n\r\n'.encode(), png, f"\r\n--{boundary}--\r\n".encode()]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def post(url, text, png):
    body, kind = multipart(text, png)
    with urlopen(Request(url, data=body, method="POST", headers={"Content-Type": kind,
                 "User-Agent": "algorithmic-trading-research/1.0"}), timeout=30) as r:
        return r.status


def run(force=False, start=None, root=ROOT):
    state_path = root / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    panels, rows = [], []
    for sym in T.COINS:
        dates, o, h, l, c = closed_candles(sym)
        state.setdefault("start", start or dates[-1].isoformat())
        r, sim = summary(sym, dates, o, c, datetime.fromisoformat(state["start"]).date())
        rows.append(r)
        panels.append((r, dates, o, h, l, c, sim))
    day = rows[0]["date"]
    text, png = message(rows), chart(panels)
    persist(root / f"{day}.png", png)
    persist(root / f"{day}.txt", text.encode())
    if not any(row["date"] == day for row in state.setdefault("ledger", [])):
        state["ledger"].append({"date": day, **{f"{r['coin']}_{k}": round(r[k], 6)
                                               for r in rows for k in ("target", "held", "equity", "hold_equity")}})
    write_csv(root / "ledger.csv", state["ledger"])
    hook = os.environ.get("DISCORD_WEBHOOK_URL")
    if hook and (force or state.get("posted") != day):
        post(hook, text, png)
        state["posted"] = day
        print("posted to Discord")
    elif not hook:
        print(f"DISCORD_WEBHOOK_URL not set; saved {root / (day + '.png')} instead of posting")
    save_json(state_path, state)
    print(text)
    return rows


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true", help="post again even if today's close was already posted")
    p.add_argument("--start", help="paper start date (YYYY-MM-DD), only used on the very first run")
    a = p.parse_args()
    run(a.force, a.start)
