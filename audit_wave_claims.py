"""Reconcile earlier repository claims against the tracked ledgers and public replay inputs."""
import csv
import json
from collections import Counter
from pathlib import Path
from runpy import run_path

import numpy as np

from compare import COINS
from flow_data import ROOT
from perp_market import load_market
from perp_orders import make_order, net_r, resolve
from regime_data import FIRST, LAST
from regime_filters import rolling_atr


def run():
    rows = list(csv.DictReader(Path("research/regime/orders.csv").open()))
    summary = {}
    for arm in ("control", "filtered"):
        group = [r for r in rows if r["variant"] == arm]
        pnl = sorted(float(r["pnl"]) for r in group if r["filled"] == "True")
        summary[arm] = dict(signals=len(group), fills=len(pnl), wins=sum(x>0 for x in pnl),
                            net=sum(pnl), top_three=sum(pnl[-3:]))
    samples, exits = [], Counter()
    for coin in COINS:
        filled = [r for r in rows if r["variant"]=="filtered" and r["coin"]==coin and r["filled"]=="True"]
        if not filled:
            continue
        m = load_market(coin,FIRST,LAST,ROOT/"depth-5m",include_options=False)
        atr,_ = rolling_atr(m.bars)
        for row in filled:
            i = (int(row["start"])-m.bars[0].time)//300
            o = make_order(1,m.bars[i-1].close,atr[i],min(b.low for b in m.bars[i-144:i]),0)
            result = resolve(m,o,i+1,1)
            assert result.fill is not None and m.bars[result.end].time+300 == int(row["end"])
            r = net_r(o,result)
            assert (r>0) == (float(row["pnl"])>0)
            samples.append(r)
            exits[(result.reason, r>0)] += 1
    rng = np.random.default_rng(17)
    ci = np.quantile(rng.choice(samples,(20000,len(samples))).mean(axis=1),[.025,.975])
    summary.update(filtered_mean_r=np.mean(samples), iid_fill_bootstrap=ci.tolist(),
                   closed_by_reason={f"{k[0]}_{'green' if k[1] else 'red'}":v for k,v in exits.items()},
                   march_april=run_path("research/flow-v1/audit.py")["audit"]())
    print(json.dumps(summary,indent=2))


if __name__ == "__main__":
    run()
