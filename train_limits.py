"""Independent per-asset XGBoost training and five-minute long-limit replay."""
import argparse
from collections import Counter
import csv
from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path

from compare import COINS
from legacy_limits import Example, Model, replay  # original study's public imports
from flow_data import ROOT, epoch
from perp_market import load_market
from perp_orders import HOLD_BARS, make_order, resolve, trade_pnl
from purged_cv import purged_folds
from regime_data import FIRST, LAST, prepare, spots

OUT = Path("data/regime-limits")
HORIZON = (1 + HOLD_BARS)*300
WINDOWS = [(epoch(date(2026,8,1)),epoch(date(2026,9,1))), (epoch(date(2026,9,1)),epoch(LAST))]


@dataclass
class Sample:
    start: int
    end: int
    values: tuple
    block: str | None
    filled: bool
    unit_pnl: float
    entry: float
    risk: float


def examples(coin):
    from regime_filters import observation, rolling_atr
    m = load_market(coin,FIRST,LAST,ROOT/"depth-5m",include_options=False)
    spot = spots(coin)
    atr, baseline = rolling_atr(m.bars)
    rows, counts = [], Counter()
    for i in range(1,len(m.bars)-HOLD_BARS):
        reading = observation(m,spot,atr,baseline,i)
        if reading is None:
            counts["warmup_or_missing"] += 1
            continue
        counts[reading.block or "eligible"] += 1
        swing = min(b.low for b in m.bars[i-144:i])
        o = make_order(1,m.bars[i-1].close,atr[i],swing,0)
        if o is None:
            continue
        x = resolve(m,o,i+1,entry_bars=1)
        pnl = trade_pnl(1,o.entry,x.price)+x.funding if x.fill is not None else 0.0
        rows.append(Sample(m.bars[i].time,m.bars[x.end].time+300,reading.values,reading.block,
                           x.fill is not None,pnl,o.entry,o.risk))
    return rows,counts


def run():
    from xgboost import XGBClassifier
    from regime_filters import NAMES
    from backtest import INITIAL,FEE
    prepare()
    OUT.mkdir(parents=True,exist_ok=True)
    report, ledger = {}, []
    for coin in COINS:
        rows, coverage = examples(coin)
        folds = []
        for n,(train,valid) in enumerate(purged_folds(rows,WINDOWS,HORIZON)):
            past = [rows[i] for i in train if rows[i].filled]
            if len({s.unit_pnl > 0 for s in past}) < 2:
                raise ValueError(f"{coin}: insufficient two-class training history")
            model = XGBClassifier(n_estimators=100,max_depth=3,learning_rate=0.04,
                                  tree_method="hist",n_jobs=2,random_state=17)
            model.fit([s.values for s in past],[int(s.unit_pnl>0) for s in past])
            model.save_model(OUT/f"{coin}-fold{n+1}.json")
            test = [rows[i] for i in valid]
            probabilities = model.predict_proba([s.values for s in test])[:,1]
            metrics = {}
            for filtered in (False,True):
                cash,free,wins,fills,orders = INITIAL,0,0,0,0
                name = "filtered" if filtered else "control"
                for s,p in zip(test,probabilities):
                    if s.start < free or p < 0.5 or (filtered and s.block is not None):
                        continue
                    qty = min(cash*0.005/s.risk,cash/(s.entry*(1+FEE)))
                    pnl = qty*s.unit_pnl
                    cash += pnl
                    free = s.end
                    wins += int(pnl>0)
                    fills += s.filled
                    orders += 1
                    ledger.append(dict(coin=coin,fold=n+1,variant=name,start=s.start,end=s.end,
                                       probability=float(p),filled=s.filled,pnl=pnl,gate=s.block or "eligible"))
                metrics[name] = dict(orders=orders,fills=fills,wins=wins,net=cash-INITIAL)
            folds.append(dict(train_fills=len(past),train_win_rate=sum(s.unit_pnl>0 for s in past)/len(past),
                              validation_samples=len(test),**metrics))
        report[coin] = dict(features=NAMES,coverage=coverage,folds=folds)
        print(coin,metrics,flush=True)
    (OUT/"results.json").write_text(json.dumps(report,indent=2))
    with (OUT/"orders.csv").open("w",newline="") as file:
        writer=csv.DictWriter(file,fieldnames=["coin","fold","variant","start","end","probability","filled","pnl","gate"])
        writer.writeheader()
        writer.writerows(ledger)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy",action="store_true",help="reproduce the pooled January baseline")
    if parser.parse_args().legacy:
        from legacy_limits import run as old_run
        old_run()
    else:
        run()
