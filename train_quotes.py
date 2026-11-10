"""Train the frozen October expiring-limit experiment, then replay all four policies."""
import csv
from collections import Counter
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

from xgboost import XGBClassifier, XGBRegressor
import numpy as np

from compare import COINS
from flow_data import ROOT, epoch
from perp_market import load_market
from backtest import INITIAL
from perp_orders import HOLD_BARS, funding_payments, make_order, net_r, resolve, trade_pnl
from quote_replay import Proposal, replay_quotes
from regime_data import FIRST, LAST, october_repair, prepare, spots
from regime_filters import observation, rolling_atr
from train_limits import OUT as CLASSIFIERS

END = date(2026, 11, 1)
TTL = 3
MODELS = Path("data/expiring-quotes")
REPORT = Path("research/october-quotes")


def setup(bars, i, atr):
    swing = min(b.low for b in bars[i-144:i])
    return make_order(1, bars[i-1].close, atr[i], swing, 0)


def examples(market, spot):
    bars = market.bars
    atr, baseline = rolling_atr(bars)
    features, targets, evaluation = [], [], []
    coverage = Counter()
    cutoff = epoch(LAST)
    for i in range(1, len(bars) - HOLD_BARS - TTL + 1):
        decision = bars[i].time
        # A full worst-case label horizon plus one clear day before October.
        if decision < cutoff and decision + (TTL+HOLD_BARS)*300 > cutoff-86400:
            continue
        reading = observation(market, spot, atr, baseline, i)
        if decision >= cutoff:
            coverage[("missing" if reading is None else reading.block) or "eligible"] += 1
        if reading is None:
            continue
        if decision >= cutoff and reading.block:
            continue
        o = setup(bars, i, atr)
        if o is None:
            continue
        if decision >= cutoff:
            evaluation.append((i, o, reading.values))
        else:
            label = 0.
            if o.entry < bars[i+1].open:
                label = net_r(o, resolve(market, o, i+1, entry_bars=TTL))
            features.append(reading.values)
            targets.append(label)
    return features, targets, evaluation, coverage


def metrics(rows):
    fills = [r for r in rows if r["status"] == "filled"]
    submitted = sum(r["status"] not in ("position_busy", "kept_first") for r in rows)
    net = sum(r["pnl"] for r in fills)
    return dict(signals=len(rows), submitted=submitted, fills=len(fills),
                wins=sum(int(r["pnl"] > 0) for r in fills), net=net,
                statuses=dict(Counter(r["status"] for r in rows)))


def equity_curve(market, rows):
    """Coin account equity at each candle close, marked with both trading fees."""
    curve = np.full(len(market.bars), INITIAL, dtype=float)
    first = market.bars[0].time
    for r in rows:
        if r["status"] != "filled":
            continue
        fill = (r["fill"]-first)//300
        end = (r["ended"]-first)//300-1
        carry = dict(funding_payments(market,r["side"],fill,end))
        paid = 0.
        for i in range(fill, end):
            paid += carry.get(i, 0.)
            curve[i] += r["qty"]*(trade_pnl(r["side"],r["entry"],market.bars[i].close)+paid)
        curve[end:] += r["pnl"]
        r["next_close_markout_bps"] = 10000*r["side"]*(market.bars[fill+1].close/r["entry"]-1)
    return curve


def run():
    prepare(FIRST, END)
    if any(not (CLASSIFIERS/f"{c}-fold2.json").exists() for c in COINS):
        from train_limits import run as train_benchmark
        train_benchmark()
    MODELS.mkdir(exist_ok=True, parents=True)
    REPORT.mkdir(exist_ok=True, parents=True)
    ledger, report, equity = [], {}, {}
    for coin in COINS:
        m = load_market(coin, FIRST, END, ROOT/"depth-5m", include_options=False,
                        candle_repairs=october_repair(coin))
        spot = spots(coin, FIRST, END)
        x, y, test, coverage = examples(m, spot)
        model = XGBRegressor(n_estimators=100, max_depth=3, learning_rate=.04,
                             tree_method="hist", n_jobs=2, random_state=17)
        model.fit(x, y)
        model.save_model(MODELS/f"{coin}.json")
        old = XGBClassifier()
        old.load_model(CLASSIFIERS/f"{coin}-fold2.json")
        signals, benchmark = [], []
        if test:
            values = [v for _, _, v in test]
            for (i, o, _), r, prob in zip(test, model.predict(values), old.predict_proba(values)[:, 1]):
                if r > 0:
                    signals.append(Proposal(i, o, float(r)))
                if prob >= .5:
                    benchmark.append(Proposal(i, o, float(prob)))
        policies = dict(replace=replay_quotes(m, signals),
                        keep=replay_quotes(m, signals, replace=False),
                        deeper=replay_quotes(m, signals, penetration_bps=2),
                        benchmark=replay_quotes(m, benchmark, ttl=1, replace=False, legacy=True))
        report[coin] = dict(train_rows=len(y), train_zero=sum(int(v == 0) for v in y),
                            coverage=coverage, market_sha256=m.fingerprint,
                            spot_sha256=sha256(json.dumps(sorted(spot.items())).encode()).hexdigest(),
                            model_sha256=sha256((MODELS/f"{coin}.json").read_bytes()).hexdigest(),
                            policies={k: metrics(v) for k,v in policies.items()})
        for policy, rows in policies.items():
            curve = equity_curve(m, rows)
            equity[policy] = equity.get(policy, 0) + curve
            ledger.extend(dict(coin=coin, policy=policy, **row) for row in rows)
        print(coin, report[coin]["policies"]["replace"], flush=True)
    (REPORT/"results.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    if ledger:
        with (REPORT/"signals.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(dict.fromkeys(k for r in ledger for k in r)))
            writer.writeheader()
            writer.writerows(ledger)
    totals = {}
    for name, curve in equity.items():
        peak = np.maximum.accumulate(curve)
        totals[name] = dict(**metrics([r for r in ledger if r["policy"] == name]),
                            max_drawdown_pct=float(max((peak-curve)/peak)*100))
    (REPORT/"totals.json").write_text(json.dumps(totals, indent=2)+"\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    run()
