"""Walk-forward training, calibrated ablations, and CPCV on common calendar blocks."""
import csv
from collections import defaultdict
from datetime import date,datetime,timezone
from itertools import combinations
import json
from pathlib import Path

import joblib
import numpy as np
from xgboost import DMatrix

from backtest import SLIP
from flow_data import dates, epoch
from perp_orders import Order,trade_pnl
from quote_replay import Proposal,replay_quotes
from wave_research import (COINS,GAP,HORIZON,MAIN,MIN_EV,OUT,events,fit,load_inputs,matrix,scores)

REPORT=Path("research/aahil-wave")
FOLDS=[epoch(date(2025,m,1)) for m in (1,4,7,10)]+[epoch(date(2026,1,1))]


def write_csv(path,rows):
    if not rows:
        return
    with path.open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def chronological(rows, start, stop):
    return [r for r in rows if r["end"]+GAP<start], [r for r in rows if start<=r["time"] and r["time"]+HORIZON<=stop]


def cpcv(rows):
    blocks=list(zip(FOLDS,FOLDS[1:]))
    summaries=[]
    paths=[[] for _ in range(3)]
    appearances=[0]*4
    for pair in combinations(range(4),2):
        hold=[blocks[i] for i in pair]
        valid=[r for r in rows if any(a<=r["time"] and r["time"]+HORIZON<=b for a,b in hold)]
        # Leave room for the 72h pivot window and its ATR warmup after a held block.
        train=[r for r in rows if all(r["end"]<a-GAP or r["time"]-878*300>=b+GAP for a,b in hold)]
        model=fit(train,MAIN)
        _,_,ev=scores(model,matrix(valid,model["columns"]))
        selected=[r for r,e in zip(valid,ev) if e>MIN_EV]
        summaries.append(dict(held_quarters="/".join(str(i+1) for i in pair),train=len(train),held=len(valid),
                         selected=len(selected),mean_r_per_selected=np.mean([r["r"] for r in selected]) if selected else None))
        for q in pair:
            a,b=blocks[q]
            paths[appearances[q]].extend(r["r"] for r in selected if a<=r["time"]<b)
            appearances[q]+=1
    write_csv(REPORT/"cpcv-paths.csv",[dict(path=i+1,selected=len(p),net_r=sum(p),
              mean_r_per_selected=np.mean(p) if p else "") for i,p in enumerate(paths)])
    return summaries


def shifted(r,market,rng):
    """Seeded random decision time later in the same hour; preserve original relative geometry."""
    i=r["index"]+int(rng.integers(0,12))
    if i+361>=len(market.bars):
        return None
    original=r["order"]
    ratio=market.bars[i-1].close/market.bars[r["index"]-1].close
    return Proposal(i,Order(original.side,original.entry*ratio,original.stop*ratio,
                          original.target*ratio,original.risk*ratio),0.)


def run(rebuild=False):
    REPORT.mkdir(exist_ok=True,parents=True)
    markets=load_inputs()
    cache=OUT/"events.joblib"
    if rebuild or not cache.exists():
        joblib.dump(events(markets),cache)
    rows,members=joblib.load(cache)
    write_csv(REPORT/"membership.csv",members)
    main=[r for r in rows if r["main"]]
    forecasts,attributions,sparse=[],[],[]
    strategies=defaultdict(lambda:defaultdict(list))
    generator=np.random.default_rng(17)
    for fold,(a,b) in enumerate(zip(FOLDS,FOLDS[1:]),1):
        train,test=chronological(main,a,b)
        for idx,family in enumerate(MAIN):
            model=fit(train,MAIN[:idx+1])
            x=matrix(test,model["columns"])
            pf,pt,ev=scores(model,x)
            for j,r in enumerate(test):
                if ev[j]>MIN_EV:
                    strategies[family][r["coin"]].append(Proposal(r["index"],r["order"],float(ev[j])))
                    if family=="lead":
                        alt=shifted(r,markets[r["coin"]],generator)
                        if alt:
                            strategies["random"][r["coin"]].append(alt)
                if family=="lead":
                    forecasts.append(dict(time=r["time"],coin=r["coin"],fold=fold,
                                     fill=int(r["fill"]),tp=int(r["tp"]),r=r["r"],
                                     p_fill=pf[j],p_tp_given_fill=pt[j],ev=ev[j],
                                     offset_bps=abs(r["order"].entry/markets[r["coin"]].bars[r["index"]-1].close-1)*10000,
                                     atr_frac=r["values"]["atr_frac"]))
            if family=="lead":
                for role in ("fill","direction"):
                    booster=model[role][0].get_booster()
                    contrib=booster.predict(DMatrix(x[::8]),pred_contribs=True)[:,:-1]
                    for k,v in zip(model["columns"],np.abs(contrib).mean(axis=0)):
                        attributions.append(dict(fold=fold,role=role,feature=k,mean_abs_shap=float(v)))
        for extra,key in (("ofi","ofi"),("micro","microprice_bps"),("oi","oi_change"),("liquidation","liquidation_delta")):
            subset=[r for r in rows if key in r["values"]]
            tr,va=chronological(subset,a,b)
            for added in (False,True):
                record=dict(fold=fold,family=extra,added=added,train=len(tr),valid=len(va),selected=0,
                            sum_r=0.,brier_fill=None,brier_tp=None,status="insufficient")
                if len(tr)>=80 and va:
                    try:
                        mod=fit(tr,MAIN+((extra,) if added else ()))
                    except ValueError as err:
                        if "both classes" not in str(err):
                            raise
                    else:
                        p,q,ev=scores(mod,matrix(va,mod["columns"]))
                        filled=[j for j,r in enumerate(va) if r["fill"]]
                        used=[r["r"] for r,v in zip(va,ev) if v>MIN_EV]
                        record.update(status="evaluated",selected=len(used),sum_r=sum(used),
                            brier_fill=np.mean([(x-r["fill"])**2 for x,r in zip(p,va)]),
                            brier_tp=np.mean([(q[j]-va[j]["tp"])**2 for j in filled]) if filled else None)
                sparse.append(record)
        print("finished fold",fold,flush=True)
    families=(*MAIN,"random")
    by_date={str(d):dict.fromkeys(families,0.) for d in dates(date(2025,1,1),date(2026,1,1))}
    results={}
    ledger=[]
    for family in families:
        pnl=[]
        statuses=defaultdict(int)
        for c in COINS:
            orders=replay_quotes(markets[c],strategies[family][c])
            for row in orders:
                statuses[row["status"]]+=1
                if row["status"]=="filled":
                    risk=-trade_pnl(row["side"],row["entry"],row["stop"]*(1-row["side"]*SLIP))
                    reward=row["pnl"]/(row["qty"]*risk)
                    pnl.append(reward)
                    day=datetime.fromtimestamp(row["ended"]-1,timezone.utc).date()
                    by_date[str(day)][family]+=reward
                else:
                    reward=0.
                ledger.append(dict(strategy=family,coin=c,decision=row["decision"],status=row["status"],
                                   fill=row["fill"],end=row["ended"],net_r=reward,net_usdt=row["pnl"]))
        results[family]=dict(statuses=dict(statuses),wins=sum(int(x>0) for x in pnl),fills=len(pnl),
                             net_r=sum(pnl),net_usdt=sum(x["net_usdt"] for x in ledger if x["strategy"]==family))
    write_csv(REPORT/"strategy-days.csv",[dict(date=d,**v) for d,v in by_date.items()])
    write_csv(REPORT/"sparse-ablations.csv",sparse)
    write_csv(REPORT/"shap.csv",attributions)
    write_csv(REPORT/"cpcv.csv",cpcv(main))
    write_csv(OUT/"predictions.csv",forecasts)
    write_csv(OUT/"policy-ledger.csv",ledger)
    write_csv(REPORT/"wave-orders.csv",[r for r in ledger if r["strategy"]=="lead"])
    final_model=fit(main,MAIN)
    joblib.dump(final_model,OUT/"model.joblib")
    (REPORT/"results.json").write_text(json.dumps(results,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(results,indent=2))


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rebuild",action="store_true")
    run(parser.parse_args().rebuild)
