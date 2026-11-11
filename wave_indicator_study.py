"""Evaluate fixed RSI and Bollinger feature sets against the archived Aahil Wave policy."""
from collections import defaultdict
import csv
import json
from pathlib import Path

import numpy as np

from backtest import INITIAL, SLIP
from perp_orders import trade_pnl
from quote_replay import Proposal, replay_quotes
from train_quotes import equity_curve
from wave_indicators import indicator_series
from wave_research import COINS, FAMILIES, MAIN, MIN_EV, events, fit, load_inputs, matrix, scores
from wave_validation import FOLDS, REPORT as BASE_REPORT, chronological, write_csv

OUTPUT = Path("research/indicator-test")
ARMS = {"baseline": (), "rsi": ("rsi",), "bands": ("bands",), "both": ("rsi","bands")}


def add_features(rows, markets):
    for coin, market in markets.items():
        values = indicator_series([b.close for b in market.bars])
        for row in rows:
            if row["coin"] == coin:
                i = row["index"] - 1
                if market.bars[i].time+300 != row["time"]:
                    raise ValueError("Indicator cutoff differs from decision time")
                features = {k: float(v[i]) for k, v in values.items()}
                if not all(np.isfinite(list(features.values()))):
                    raise ValueError("Indicator unavailable on a baseline row")
                row["values"].update(features)


def replay_arm(markets, proposals):
    ledger = []
    days = np.zeros((FOLDS[-1]-FOLDS[0])//86400)
    equity = None
    for c in COINS:
        market = markets[c]
        orders = replay_quotes(market, proposals[c])
        curve = equity_curve(market, orders)
        equity = curve if equity is None else equity+curve
        for order in orders:
            reward = 0.
            if order["status"] == "filled":
                stop_fill = order["stop"]*(1-order["side"]*SLIP)
                unit_risk = -trade_pnl(order["side"],order["entry"],stop_fill)
                reward = order["pnl"]/(order["qty"]*unit_risk)
                days[(order["ended"]-1-FOLDS[0])//86400] += reward
            ledger.append(dict(coin=c,decision=order["decision"],status=order["status"],fill=order["fill"],
                               end=order["ended"],net_r=reward,net_usdt=order["pnl"]))
    filled = [r for r in ledger if r["status"]=="filled"]
    submitted = sum(r["status"]!="position_busy" for r in ledger)
    wins = sum(int(r["net_r"]>0) for r in filled)
    net = sum(r["net_usdt"] for r in filled)
    peak = np.maximum.accumulate(equity)
    summary = dict(qualified=len(ledger),submitted=submitted,fills=len(filled),wins=wins,
                   win_pct=100*wins/len(filled) if filled else None,net_r=float(days.sum()),
                   r_per_submission=float(days.sum())/submitted if submitted else None,
                   net_usdt=net,return_pct=100*net/(INITIAL*len(COINS)),max_drawdown_pct=float(100*max((peak-equity)/peak)))
    return ledger, days, summary


def check_baseline(ledger):
    with (BASE_REPORT/"wave-orders.csv").open() as f:
        expected = list(csv.DictReader(f))
    if len(ledger)!=len(expected):
        raise ValueError("Baseline order count differs from original replay")
    for a,b in zip(ledger,expected):
        for k in ("coin","decision","status","fill","end"):
            if str(a[k])!=b[k]:
                raise ValueError(f"Original order differs at {k}: {a}")
        for k in ("net_r","net_usdt"):
            if not np.isclose(a[k],float(b[k]),rtol=0,atol=1e-9):
                raise ValueError(f"Original payoff differs at {k}: {a}")


def run():
    markets = load_inputs()
    rows = [r for r in events(markets)[0] if r["main"]]
    add_features(rows,markets)
    # Extend the feature registry in this study process so all arms reuse the frozen fitter.
    FAMILIES.update(rsi=["rsi14"],bands=["bb_percent_b","bb_bandwidth"])
    proposals = {arm:defaultdict(list) for arm in ARMS}
    for start,end in zip(FOLDS,FOLDS[1:]):
        train,test = chronological(rows,start,end)
        for arm,extra in ARMS.items():
            model = fit(train,MAIN+extra)
            _,_,ev = scores(model,matrix(test,model["columns"]))
            for r,score in zip(test,ev):
                if score>MIN_EV:
                    proposals[arm][r["coin"]].append(Proposal(r["index"],r["order"],float(score)))
    reports, ledgers, daily = {}, [], {}
    for arm,quotes in proposals.items():
        ledger,daily[arm],reports[arm] = replay_arm(markets,quotes)
        if arm=="baseline":
            check_baseline(ledger)
        ledgers.extend(dict(arm=arm,**r) for r in ledger)
    size=len(daily["baseline"])
    starts=np.random.default_rng(17).integers(size,size=(5000,(size+6)//7,1))
    blocks=((starts+np.arange(7))%size).reshape(5000,-1)[:,:size]
    for arm,days in daily.items():
        delta = days-daily["baseline"]
        reports[arm]["delta_total_r"] = float(delta.sum())
        reports[arm]["delta_total_r_95"] = np.quantile(delta[blocks].sum(axis=1),[.025,.975]).tolist()
    OUTPUT.mkdir(parents=True,exist_ok=True)
    write_csv(OUTPUT/"orders.csv",ledgers)
    (OUTPUT/"results.json").write_text(json.dumps(reports,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(reports,indent=2))


if __name__=="__main__":
    run()
