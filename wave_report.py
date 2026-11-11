"""Calibration and day-block resampling for the published walk-forward experiment."""
import csv
from datetime import date,datetime,timezone
import json
import numpy as np

from flow_data import dates
from wave_validation import REPORT,OUT,write_csv


def read(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def diagnostics():
    rows=read(OUT/"predictions.csv")
    reliability=[]
    brier={}
    for name,target in (("p_fill","fill"),("p_tp_given_fill","tp")):
        applicable=[r for r in rows if name=="p_fill" or r["fill"]=="1"]
        y=np.array([float(r[target]) for r in applicable])
        p=np.array([float(r[name]) for r in applicable])
        brier[name]=dict(n=len(y),brier=float(np.mean((p-y)**2)),
                         observed=float(y.mean()),predicted=float(p.mean()))
        for i in range(10):
            take=(p>=i/10)&(p<=(i+1)/10 if i==9 else p<(i+1)/10)
            reliability.append(dict(model=name,bin_lo=i/10,n=int(take.sum()),observed=y[take].mean() if take.any() else "",
                                    predicted=p[take].mean() if take.any() else ""))
    write_csv(REPORT/"calibration.csv",reliability)
    fills=[r for r in read(REPORT/"wave-orders.csv") if r["status"]=="filled"]
    calendar=dates(date(2025,1,1),date(2026,1,1))
    nets=np.zeros(len(calendar));counts=np.zeros(len(calendar))
    for r in fills:
        day=datetime.fromtimestamp(int(r["end"])-1,timezone.utc).date()
        k=(day-calendar[0]).days
        nets[k]+=float(r["net_r"]);counts[k]+=1
    rng=np.random.default_rng(17);draws=[]
    for _ in range(5000):
        idx=(rng.integers(len(calendar),size=53)[:,None]+np.arange(7))%len(calendar)
        idx=idx.ravel()[:len(calendar)]
        if counts[idx].sum():
            draws.append(nets[idx].sum()/counts[idx].sum())
    brier["mean_r_per_fill"]=nets.sum()/counts.sum()
    brier["weekly_bootstrap_95"]=np.quantile(draws,[.025,.975]).tolist()
    brier["bootstrap_valid"]=len(draws)
    (REPORT/"uncertainty.json").write_text(json.dumps(brier,indent=2)+"\n")
    print(json.dumps(brier,indent=2))


if __name__=="__main__":
    diagnostics()
