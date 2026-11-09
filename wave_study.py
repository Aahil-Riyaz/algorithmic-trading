"""Walk forward one month at a time with a fixed pullback filter."""
import csv
import hashlib
import json
from datetime import date
from pathlib import Path

import joblib
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from flow_data import FIRST, LAST, epoch, prepare_range
from flow_replay import replay, summary
from train_flow import FIXED, RUN, dataset, in_period, ledger_rows, matrix, targets
from waves import wave_side


def run():
    end = date(2026, 7, 1)
    for feed in ("candles", "funding", "depth", "options"):
        prepare_range(feed, LAST, end)
    markets, rows, _ = dataset(end, FIRST)
    spec = json.loads(Path("research/flow-v1/freeze.json").read_bytes())["models"]["options_flow"]
    path = RUN / "options_flow.joblib"
    if hashlib.sha256(path.read_bytes()).hexdigest() != spec["model_sha256"]:
        raise ValueError("Original control model differs from published freeze")
    frozen = joblib.load(path)
    size = len(spec["features"])
    ledger = []
    reports = {}
    pooled = {name: [] for name in ("original", "refit", "wave")}
    for train, month, stop in [(date(2025,11,1), LAST, date(2026,6,1)),
                               (date(2025,12,1), date(2026,6,1), end)]:
        past = [d for d in rows if in_period(d, epoch(train), epoch(month))]
        future = [d for d in rows if in_period(d, epoch(month), epoch(stop))]
        model = HistGradientBoostingRegressor(max_leaf_nodes=spec["leaves"], **FIXED)
        model.fit(matrix(past, size), targets(past))
        x = matrix(future, size)
        scored = model.predict(x).reshape(-1, 2)
        filtered = scored.copy()
        for d, pair in zip(future, filtered):
            bars = markets[d.coin].hours
            i = d.start // 12
            side = wave_side([b.close for b in bars[i-72:i]], d.atr)
            for j, proposal in enumerate(d.proposals):
                if proposal.order.side != side:
                    pair[j] = float("-inf")
        report = dict(training_orders=2*len(past), eligible_coin_hours=len(future))
        for name, scores in [("original", frozen.predict(x).reshape(-1, 2)), ("refit", scored), ("wave", filtered)]:
            tickets = replay(future, scores, spec["cutoff"])
            pooled[name].extend(tickets)
            ledger.extend(dict(model=name, **row) for row in ledger_rows(tickets, markets))
            report[name] = summary(tickets)
        reports[str(month)] = report
    reports["pooled"] = {name: summary(t) for name, t in pooled.items()}
    out = Path("data/wave-run")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(reports, indent=2))
    with (out / "orders.csv").open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(ledger[0]))
        writer.writeheader()
        writer.writerows(ledger)
    for name, r in reports["pooled"].items():
        print(name, r["wins"], r["fills"], round(r["net_usdt"], 2))


if __name__ == "__main__":
    with threadpool_limits(limits=2):
        run()
