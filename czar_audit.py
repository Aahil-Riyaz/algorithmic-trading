"""Replay pasted four-target BTC alerts on Binance USD-M minute candles and compare with the reported target hits."""
import csv
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

import numpy as np

from discord_market import interval_data
from flow_data import save_json
from wave_validation import write_csv

DIR = Path("research/czar")
CACHE = Path("data/czar")
VALID, TIMEOUT = 24 * 3600, 7 * 86400
MAKER, TAKER, SLIP = 2e-4, 5e-4, 1e-4
OFFSETS = range(-6, 7)
RESOLVED = ("SL", "BE", "TP4", "timeout")


def read(name):
    with (DIR / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def stamp(local, offset):
    """Discord display time to UTC seconds, given the display zone's offset from UTC in hours."""
    t = datetime.strptime(local, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp()
    return int(t) - offset * 3600


def reached(bar, side, level):
    """A favourable level (target) traded in this minute."""
    return bar.high >= level if side == 1 else bar.low <= level


def hit_stop(bar, side, level):
    return bar.low <= level if side == 1 else bar.high >= level


def calibrate(bars, start, alerts, hits):
    """Share of reported hits whose level traded in the 30 minutes before the post, for each display offset."""
    by_id = {a["id"]: a for a in alerts}
    out = {}
    for h in OFFSETS:
        ok = 0
        for x in hits:
            a = by_id[x["alert_id"]]
            side, level = (1 if a["side"] == "LONG" else -1), float(a[f"tp{x['target']}"])
            i = (stamp(x["posted_local"], h) - start) // 60
            ok += any(reached(b, side, level) for b in bars[max(0, i - 30):max(0, i + 1)])
        out[h] = ok / len(hits)
    return out


def replay(bars, start, a, t, breakeven=False, market=False):
    """One alert: limit entry (or market at the next open), four equal parts at the targets, stop first in shared minutes."""
    side = 1 if a["side"] == "LONG" else -1
    entry, stop = float(a["entry"]), float(a["stop"])
    tps = [float(a[f"tp{k}"]) for k in range(1, 5)]
    i, end = (t - start) // 60 + 1, len(bars)
    fill = price = None
    if market and i < end:
        fill, price = i, bars[i].open
    for j in range(i, min(end, i + VALID // 60)):
        if fill is not None:
            break
        b = bars[j]
        if hit_stop(b, side, entry):  # the limit trades when price comes back to entry
            fill, price = j, (min(entry, b.open) if side == 1 else max(entry, b.open))
            break
    if fill is None:
        return dict(status="expired" if i + VALID // 60 <= end else "pending", best_tp=0, fill_utc="", r=0.)
    risk = side * (entry - stop)
    left, exits, best_tp, sl, status = [0, 1, 2, 3], [], 0, stop, "timeout"
    for j in range(fill, min(end, fill + TIMEOUT // 60)):
        b = bars[j]
        if hit_stop(b, side, sl):
            px = min(sl, b.open) if side == 1 else max(sl, b.open)
            exits += [(px, TAKER + SLIP) for _ in left]
            status, left = ("SL" if sl == stop else "BE"), []
            break
        if j == fill:
            continue  # targets count from the minute after the fill
        for k in list(left):
            if reached(b, side, tps[k]):
                exits.append((tps[k], MAKER))
                left.remove(k)
                best_tp = max(best_tp, k + 1)
        if breakeven and best_tp:
            sl = entry
        if not left:
            status = "TP4"
            break
    else:
        if fill + TIMEOUT // 60 > end:
            status = "open"
    if left:
        last = bars[min(end, fill + TIMEOUT // 60) - 1].close
        exits += [(last, TAKER + SLIP) for _ in left]
    pnl = [side * (px - price) - fee * px - MAKER * price for px, fee in exits]
    return dict(status=status, best_tp=best_tp, fill_utc=datetime.fromtimestamp(start + fill * 60, timezone.utc).isoformat(),
                fill_price=price, r=mean(pnl) / risk, stop_pct=risk / entry * 100,
                margin_return_20x_pct=mean(pnl) / price * 20 * 100)


def stats(rows, key):
    done = [r for r in rows if r[f"{key}_status"] in RESOLVED]
    rs = [r[f"{key}_r"] for r in done]
    draws = np.random.default_rng(1119).choice(rs, (5000, len(rs))).mean(1)
    return dict(resolved=len(rs), total_r=sum(rs), mean_r=mean(rs), mean_r_95=np.percentile(draws, [2.5, 97.5]).tolist(),
                profitable=sum(x > 0 for x in rs),
                tp1_before_exit=sum(r[f"{key}_best_tp"] >= 1 for r in done),
                stopped=sum(r[f"{key}_status"] == "SL" for r in done),
                margin_return_20x_pct_total=sum(r[f"{key}_margin_return_20x_pct"] for r in done))


def main():
    alerts, hits = read("alerts.csv"), read("hits.csv")
    first = min(stamp(a["posted_local"], 6) for a in alerts) // 86400 * 86400
    now = int(datetime.now(timezone.utc).timestamp()) // 60 * 60 - 120
    bars, _, digest = interval_data("BTC", first, now, CACHE)
    fit = calibrate(bars, first, alerts, hits)
    offset = max(fit, key=fit.get)
    reported = {}
    for x in hits:
        reported[x["alert_id"]] = max(reported.get(x["alert_id"], 0), int(x["target"]))
    rows = []
    for a in alerts:
        t = stamp(a["posted_local"], offset)
        base, be = replay(bars, first, a, t), replay(bars, first, a, t, breakeven=True)
        mk = replay(bars, first, a, t, market=True)
        fill_t = datetime.fromisoformat(base["fill_utc"]).timestamp() if base["fill_utc"] else float("inf")
        early = sum(stamp(x["posted_local"], offset) < fill_t for x in hits if x["alert_id"] == a["id"])
        rows.append(dict(id=a["id"], posted_utc=datetime.fromtimestamp(t, timezone.utc).isoformat(), side=a["side"],
                         entry=a["entry"], stop=a["stop"], reported_max_tp=reported.get(a["id"], 0),
                         tp1_r=round(abs(float(a["tp1"]) - float(a["entry"])) / abs(float(a["entry"]) - float(a["stop"])), 3),
                         **{f"posted_stop_{k}": v for k, v in base.items()},
                         reported_hits_before_limit_fill=early,
                         **{f"breakeven_{k}": be.get(k, 0) for k in ("status", "best_tp", "r", "margin_return_20x_pct")},
                         **{f"market_{k}": mk.get(k, 0) for k in ("status", "best_tp", "r", "margin_return_20x_pct")}))
    write_csv(DIR / "replay.csv", rows)
    res = dict(source_sha256=digest, through_utc=datetime.fromtimestamp(now, timezone.utc).isoformat(),
               display_offset_hours=offset, offset_fit=fit, alerts=len(rows),
               fills=sum(bool(r["posted_stop_fill_utc"]) for r in rows),
               status={s: sum(r["posted_stop_status"] == s for r in rows)
                       for s in ("SL", "TP4", "timeout", "open", "expired", "pending")},
               reported_any_tp=sum(r["reported_max_tp"] > 0 for r in rows),
               stopped_alerts_with_a_reported_tp=sum(r["posted_stop_status"] == "SL" and r["reported_max_tp"] > 0 for r in rows),
               median_tp1_r=float(np.median([r["tp1_r"] for r in rows])),
               median_stop_pct=float(np.median([r["posted_stop_stop_pct"] for r in rows if r["posted_stop_fill_utc"]])),
               reported_hits=len(hits), reported_hits_before_limit_fill=sum(r["reported_hits_before_limit_fill"] for r in rows),
               posted_stop=stats(rows, "posted_stop"), breakeven_after_tp1=stats(rows, "breakeven"),
               market_entry=stats(rows, "market"),
               costs=dict(maker=MAKER, taker=TAKER, slip=SLIP), valid_hours=VALID // 3600, timeout_days=TIMEOUT // 86400)
    save_json(DIR / "results.json", res)
    plot(bars, first, rows)
    print({k: v for k, v in res.items() if k != "offset_fit"}, "\nfit", {k: round(v, 2) for k, v in fit.items()})


def plot(bars, start, rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    close = np.array([b.close for b in bars])[::15]
    x = (start + np.arange(len(close)) * 900).astype("datetime64[s]")
    fig, ax = plt.subplots(2, 1, figsize=(14, 9), gridspec_kw=dict(height_ratios=[3, 1.4]))
    ax[0].plot(x, close, color="#888", lw=.7)
    colour = dict(SL="#c8423b", TP4="#2a9d58", timeout="#e08a1e", open="#1b6ca8")
    for r in rows:
        if not r["posted_stop_fill_utc"]:
            continue
        t = np.datetime64(r["posted_stop_fill_utc"][:19])
        c = colour.get(r["posted_stop_status"], "#555")
        ax[0].scatter(t, float(r["entry"]), marker="^" if r["side"] == "LONG" else "v", color=c, s=60, zorder=3)
        ax[0].hlines(float(r["stop"]), t, t + np.timedelta64(36, "h"), color="#c8423b", lw=1, ls=":")
        ax[0].annotate(f"#{r['id']} {r['posted_stop_status']} {r['posted_stop_r']:+.2f}R", (t, float(r["entry"])),
                       xytext=(4, 6), textcoords="offset points", fontsize=7, color=c)
    ax[0].set(title="Pasted BTC alerts replayed on Binance minute candles (entry markers, dotted stops)", ylabel="USDT")
    for key, col, name in (("posted_stop", "#1b6ca8", "posted stop"), ("breakeven", "#e08a1e", "stop to entry after TP1")):
        rs = [r[f"{key}_r"] for r in rows if r[f"{key}_status"] in RESOLVED]
        ax[1].plot(range(1, len(rs) + 1), np.cumsum(rs), marker=".", color=col, label=name)
    ax[1].axhline(0, color="#444", lw=.8)
    ax[1].set(xlabel="resolved trade", ylabel="cumulative R after costs")
    ax[1].legend()
    for a in ax:
        a.grid(alpha=.3)
    fig.tight_layout()
    fig.savefig(DIR / "replay.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
