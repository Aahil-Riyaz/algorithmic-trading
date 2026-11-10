"""Train a small probability table on past fills, then replay the frozen filter."""
import csv
import json
from bisect import bisect_right
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import quantiles

from backtest import FEE, INITIAL, SLIP
from compare import COINS, DATA, END, START, check_period, download
from prices import load
from limit_orders import Outcome, Setup, resolve, setup, unit_pnl


FINAL = int(datetime(2026, 2, 1, tzinfo=timezone.utc).timestamp())
HORIZON = 25   # latest exit inclusive is decision hour + 24
OUT = Path("data/limit-run")


def markets(first, last, folder):
    folder.mkdir(parents=True, exist_ok=True)
    data = {}
    for coin in COINS:
        path = folder / f"{coin}.csv"
        if not path.exists():
            download(coin, path, first, last)
        data[coin] = load(path)
        check_period(data[coin], first, last)
    return data


@dataclass
class Example:
    coin: str
    i: int
    order: Setup
    outcome: Outcome


def examples(data, start, end):
    rows = []
    for coin, bars in data.items():
        for i in range(max(24, start), end - HORIZON + 1):
            order = setup(bars, i)
            if order:
                rows.append(Example(coin, i, order, resolve(order, bars, i)))
    return rows


def cell(cuts, features):
    return ",".join(str(bisect_right(edges, val)) for edges, val in zip(cuts, features))


@dataclass
class Model:
    cuts: list
    rates: dict
    prior: float

    def score(self, order):
        return self.rates.get(cell(self.cuts, order.features), self.prior)


def fit(rows, bins):
    fills = [r for r in rows if r.outcome.fill is not None]
    cuts = [quantiles(col, n=bins, method="inclusive")
            for col in zip(*(r.order.features for r in fills))]
    counts = defaultdict(lambda: [0, 0])
    for r in fills:
        bucket = counts[cell(cuts, r.order.features)]
        bucket[0] += unit_pnl(r.order, r.outcome) > 0
        bucket[1] += 1
    prior = sum(w for w, _ in counts.values()) / len(fills)
    rates = {k: (w + 50 * prior) / (n + 50) for k, (w, n) in counts.items()}
    return Model(cuts, rates, prior)


def replay(rows, model, cutoff):
    cash = dict.fromkeys(COINS, INITIAL)
    available = dict.fromkeys(COINS, 0)
    ledger = []
    for r in rows:
        if r.i < available[r.coin]:
            continue
        score = model.score(r.order)
        if score < cutoff:
            continue
        o, result = r.order, r.outcome
        available[r.coin] = result.end + 1
        pnl = 0
        if result.fill is not None:
            cost = o.limit * (1 + FEE)
            risk = cost - o.stop * (1 - SLIP) * (1 - FEE)
            qty = min(cash[r.coin] / cost, cash[r.coin] * 0.005 / risk)
            pnl = qty * unit_pnl(o, result)
            cash[r.coin] += pnl
        ledger.append(dict(coin=r.coin, hour=r.i, fill=result.fill, end=result.end,
                           limit=o.limit, stop=o.stop, target=o.target, exit=result.price,
                           reason=result.reason, score=score, pnl=pnl))
    return ledger


def metrics(ledger):
    pnl = [r["pnl"] for r in ledger if r["fill"] is not None]
    wins = [p for p in pnl if p > 0]
    return dict(orders=len(ledger), fills=len(pnl), wins=len(wins),
                win_pct=100 * len(wins) / len(pnl) if pnl else None,
                net_usdt=sum(pnl), return_pct=100 * sum(pnl) / (len(COINS) * INITIAL))


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    training = markets(START, END, DATA)
    n = len(training["BTC"])
    whole = examples(training, 0, n)
    candidates = defaultdict(list)
    for fold in range(3):
        start = n * (fold + 3) // 6
        end = n * (fold + 4) // 6
        past = [r for r in whole if r.i + HORIZON <= start]
        future = [r for r in whole if start <= r.i and r.i + HORIZON <= end]
        for bins in (2, 4, 6):
            model = fit(past, bins)
            for cutoff in (0.35, 0.40, 0.45, 0.50):
                candidates[bins, cutoff].append(metrics(replay(future, model, cutoff)))
    eligible = [key for key, folds in candidates.items() if min(f["fills"] for f in folds) >= 20]
    if not eligible:
        raise ValueError("No candidate reached 20 filled trades in every validation fold")
    bins, cutoff = max(eligible, key=lambda k: sum(f["net_usdt"] for f in candidates[k]))
    model = fit(whole, bins)
    frozen = dict(bins=bins, cutoff=cutoff, **asdict(model))
    (OUT / "model.json").write_text(json.dumps(frozen, indent=2))
    (OUT / "validation.json").write_text(json.dumps({str(k): v for k, v in candidates.items()}, indent=2))
    test = markets(END, FINAL, Path("data/kucoin-2026-01"))
    combined = {coin: training[coin][-24:] + test[coin] for coin in COINS}
    rows = examples(combined, 24, len(combined["BTC"]))
    print("Frozen settings:", bins, cutoff)
    for name, threshold in (("unfiltered", 0), ("model", cutoff)):
        ledger = replay(rows, model, threshold)
        print(name, json.dumps(metrics(ledger)))
        with (OUT / f"{name}.csv").open("w", newline="") as file:
            fields = ["coin","hour","fill","end","limit","stop","target","exit","reason","score","pnl"]
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for entry in ledger:
                for key in ("hour", "fill", "end"):
                    if entry[key] is not None:
                        entry[key] = combined[entry["coin"]][entry[key]].time
                writer.writerow(entry)


if __name__ == "__main__":
    run()
