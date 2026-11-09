"""Fit on earlier months, freeze the model files, then separately evaluate two later months."""
import argparse
import csv
import gzip
import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timezone

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from backtest import FEE, INITIAL
from compare import COINS
from flow_data import FIRST, HOLDOUT, LAST, ROOT, epoch, prepare
from flow_features import FEATURES, decisions
from flow_replay import max_drawdown, replay, stop_diagnostic, stress_pnl, summary
from perp_market import load_market
from perp_orders import HORIZON, net_r


RUN = ROOT / "run"
FOLDS = [date(2025, 12, 1), date(2026, 1, 1), date(2026, 2, 1), HOLDOUT]
LEAVES = (7, 15, 31)
CUTOFFS = (0.0, 0.05, 0.10)
FIXED = dict(max_iter=120, learning_rate=0.04, min_samples_leaf=100, l2_regularization=2.0,
             random_state=17, early_stopping=False)


def write_report(name, obj):
    (RUN / name).write_text(json.dumps(obj, allow_nan=False, indent=2) + "\n", encoding="utf-8")


def inputs(stage):
    for feed in ("candles", "funding", "depth", "options"):
        prepare(feed, stage)


def dataset(last, start_decisions):
    markets, coverage, rows = {}, {}, []
    for coin in COINS:
        market = load_market(coin, FIRST, last)
        batch, counts = decisions(coin, market, epoch(start_decisions), epoch(last))
        rows.extend(batch)
        coverage[coin] = counts
        markets[coin] = market
    rows.sort(key=lambda d: (d.time, d.coin))
    return markets, rows, coverage


def in_period(d, first, last):
    return first <= d.time and d.time + 300 + HORIZON * 300 <= last


def matrix(rows, size):
    return np.array([p.features[:size] for d in rows for p in d.proposals], dtype=float)


def targets(rows):
    return np.array([net_r(p.order, p.outcome) for d in rows for p in d.proposals])


def candidate_returns(rows, folds, name):
    size = len(FEATURES[name])
    scoreboard = {(leaves, cut): [] for leaves in LEAVES for cut in CUTOFFS}
    for first, last in zip(folds, folds[1:]):
        past = [d for d in rows if in_period(d, epoch(FIRST), epoch(first))]
        future = [d for d in rows if in_period(d, epoch(first), epoch(last))]
        x, y = matrix(past, size), targets(past)
        x_val = matrix(future, size)
        for leaves in LEAVES:
            model = HistGradientBoostingRegressor(max_leaf_nodes=leaves, **FIXED).fit(x, y)
            scores = model.predict(x_val).reshape(-1, 2)
            for cut in CUTOFFS:
                metrics = summary(replay(future, scores, cut))
                scoreboard[leaves, cut].append(dict(month=first.isoformat(), train_orders=len(y),
                                                     eligible_coin_hours=len(future), **metrics))
    candidates = []
    for (leaves, cut), results in scoreboard.items():
        candidates.append(dict(leaves=leaves, cutoff=cut, folds=results,
                               validation_pnl=sum(s["net_usdt"] for s in results),
                               min_fills=min(s["fills"] for s in results)))
    eligible = [c for c in candidates if c["min_fills"] >= 20]
    if eligible:
        chosen = max(eligible, key=lambda c: c["validation_pnl"])
    else:
        chosen = max(candidates, key=lambda c: (c["min_fills"], c["validation_pnl"]))
    return candidates, chosen


def fit():
    inputs("train")
    markets, rows, coverage = dataset(HOLDOUT, FIRST)
    freeze = dict(sklearn=sklearn.__version__, train_start=str(FIRST), train_end_exclusive=str(HOLDOUT),
                  holdout_end_exclusive=str(LAST), fixed=FIXED, candidate_leaves=LEAVES, cutoffs=CUTOFFS,
                  feature_cutoffs="hourly UTC; orders activate five minutes later",
                  training_fingerprints={c: m.fingerprint for c, m in markets.items()},
                  coverage=coverage, coin_hours=len(rows), proposed_orders=2 * len(rows), models={})
    validation = {}
    y = targets(rows)
    for name, names in FEATURES.items():
        candidates, chosen = candidate_returns(rows, FOLDS, name)
        validation[name] = candidates
        model = HistGradientBoostingRegressor(max_leaf_nodes=chosen["leaves"], **FIXED)
        model.fit(matrix(rows, len(names)), y)
        path = RUN / f"{name}.joblib"
        joblib.dump(model, path, compress=3)
        freeze["models"][name] = dict(features=names, leaves=chosen["leaves"], cutoff=chosen["cutoff"],
                                      validation_pnl=chosen["validation_pnl"], min_fills=chosen["min_fills"],
                                      model_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        print(name, chosen["leaves"], chosen["cutoff"], "validation USDT", round(chosen["validation_pnl"], 2), flush=True)
    write_report("validation.json", validation)
    write_report("freeze.json", freeze)


def ledger_rows(ledger, markets):
    for t in ledger:
        d, p = t.decision, t.proposal
        m = markets[d.coin]
        o, x = p.order, p.outcome
        yield dict(coin=d.coin, side="long" if o.side == 1 else "short", feature_cutoff=d.time,
                   active=m.bars[d.start].time, score_r=t.score, entry=o.entry, stop=o.stop, target=o.target,
                   qty=t.quantity, fill=m.bars[x.fill].time if x.fill is not None else None,
                   end=m.bars[x.end].time, exit_px=x.price, reason=x.reason, net_usdt=t.pnl,
                   funding_usdt=x.funding * t.quantity)


def win_interval(ledger, markets):
    """Circular 7-day block bootstrap across all coins; individual trades overlap in time."""
    n = (LAST - HOLDOUT).days
    wins_fills = np.zeros((n, 2), dtype=int)
    for t in ledger:
        x = t.proposal.outcome
        if x.fill is not None:
            stamp = markets[t.decision.coin].bars[x.end].time
            i = (stamp - epoch(HOLDOUT)) // 86400
            wins_fills[i] += (t.pnl > 0, 1)
    rng = np.random.default_rng(17)
    out = []
    for _ in range(2000):
        starts = rng.integers(n, size=(n + 6) // 7)
        days = ((starts[:, None] + np.arange(7)) % n).flatten()[:n]
        wins, fills = wins_fills[days].sum(axis=0)
        if fills:
            out.append(100 * wins / fills)
    return np.percentile(out, [2.5, 97.5]).tolist() if out else None


def evaluate():
    freeze = json.loads((RUN / "freeze.json").read_text())
    if sklearn.__version__ != freeze["sklearn"]:
        raise ValueError("Use the scikit-learn version recorded at fit time")
    # Verify the training history before joining lookbacks across the holdout boundary.
    for coin in COINS:
        if load_market(coin, FIRST, HOLDOUT).fingerprint != freeze["training_fingerprints"][coin]:
            raise ValueError(f"Training input changed for {coin}; start a separately versioned run")
    inputs("test")
    markets, rows, coverage = dataset(LAST, HOLDOUT)
    freeze_id = hashlib.sha256(json.dumps(freeze, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
    results = dict(test_start=str(HOLDOUT), test_end_exclusive=str(LAST), cash_return_pct=0, freeze_id=freeze_id,
                   coverage=coverage, combined_input_fingerprints={c: m.fingerprint for c, m in markets.items()},
                   models={})
    for name, spec in freeze["models"].items():
        if spec["features"] != FEATURES[name]:
            raise ValueError("Feature definition changed since the freeze")
        path = RUN / f"{name}.joblib"
        if hashlib.sha256(path.read_bytes()).hexdigest() != spec["model_sha256"]:
            raise ValueError(f"Frozen model changed: {name}")
        model = joblib.load(path)  # only local fit artifacts with verified freeze hashes
        scores = model.predict(matrix(rows, len(spec["features"]))).reshape(-1, 2)
        ledger = replay(rows, scores, spec["cutoff"])
        result = summary(ledger)
        fills = [t for t in ledger if t.proposal.outcome.fill is not None]
        gross = sum(t.quantity * t.proposal.order.side * (t.proposal.outcome.price - t.proposal.order.entry)
                    for t in fills)
        fees = sum(t.quantity * FEE * (t.proposal.order.entry + t.proposal.outcome.price) for t in fills)
        if abs(gross - fees + result["funding_usdt"] - result["net_usdt"]) > 1e-5:
            raise ValueError("Fees, funding and price P&L do not reconcile")
        result.update(gross_price_pnl_usdt=gross, trading_fees_usdt=fees)
        result.update(return_pct=100 * result["net_usdt"] / (INITIAL * len(COINS)),
                      max_drawdown_pct=max_drawdown(ledger, markets),
                      double_cost_pnl=stress_pnl(ledger), win_pct_block_interval=win_interval(ledger, markets))
        result["by_coin"] = {coin: summary([t for t in ledger if t.decision.coin == coin]) for coin in COINS}
        result["by_side"] = {label: summary([t for t in ledger if t.proposal.order.side == side])
                             for label, side in (("long", 1), ("short", -1))}
        months = defaultdict(list)
        for t in ledger:
            stamp = markets[t.decision.coin].bars[t.proposal.outcome.end].time
            months[datetime.fromtimestamp(stamp, timezone.utc).strftime("%Y-%m")].append(t)
        result["by_exit_month"] = {month: summary(tickets) for month, tickets in months.items()}
        if name == "options_flow":
            result["paired_stops"] = stop_diagnostic(ledger, markets)
        results["models"][name] = result
        records = list(ledger_rows(ledger, markets))
        with gzip.open(RUN / f"{name}-orders.csv.gz", "wt", newline="", encoding="utf-8") as file:
            fields = ["coin", "side", "feature_cutoff", "active", "score_r", "entry", "stop", "target",
                      "qty", "fill", "end", "exit_px", "reason", "net_usdt", "funding_usdt"]
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(records)
        print(name, result["wins"], "/", result["fills"], "net USDT", round(result["net_usdt"], 2), flush=True)
    write_report("holdout.json", results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("fit", "evaluate"))
    args = parser.parse_args()
    RUN.mkdir(parents=True, exist_ok=True)
    with threadpool_limits(limits=2):
        if args.stage == "fit":
            fit()
        else:
            evaluate()
