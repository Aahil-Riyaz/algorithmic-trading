"""Selection diagnostics on synchronized, walk-forward, daily strategy R (equal fixed risk)."""
import argparse
import csv
from datetime import date, timedelta
from itertools import combinations
import json
from pathlib import Path

import numpy as np
from scipy.stats import kurtosis, norm, rankdata, skew


def sharpe(a):
    volatility = a.std(axis=0,ddof=1)
    return np.divide(a.mean(axis=0),volatility,out=np.full(a.shape[1],np.nan),where=volatility>0)


def evaluate(path, blocks=8):
    with Path(path).open() as f:
        reader=csv.DictReader(f)
        columns=[k for k in reader.fieldnames if k!="date"]
        rows=list(reader)
    dates=[date.fromisoformat(r["date"]) for r in rows]
    if any(b-a!=timedelta(days=1) for a,b in zip(dates,dates[1:])):
        raise ValueError("Daily observations must be aligned, contiguous and ordered")
    x=np.array([[float(r[k]) for k in columns] for r in rows])
    if len(x)<blocks*2 or blocks%2 or not np.isfinite(x).all():
        raise ValueError("Incomplete daily strategy panel")
    ratios=sharpe(x)
    live=np.isfinite(ratios)
    if live.sum()<2:
        return dict(status="insufficient nonconstant variants",columns=columns)
    names=np.array(columns)[live]
    x,ratios=x[:,live],ratios[live]
    n=len(names)
    best=int(ratios.argmax())
    r=ratios[best]
    null=ratios.std(ddof=1)*((1-np.euler_gamma)*norm.ppf(1-1/n)+np.euler_gamma*norm.ppf(1-1/(n*np.e)))
    denom=1-skew(x[:,best],bias=False)*r+(kurtosis(x[:,best],fisher=False,bias=False)-1)*r*r/4
    dsr=float(norm.cdf((r-null)*np.sqrt((len(x)-1)/denom))) if denom>0 else None
    chunks=np.array_split(np.arange(len(x)),blocks)
    failures=[]
    mean_failures=[]
    for train in combinations(range(blocks),blocks//2):
        first=x[np.concatenate([chunks[i] for i in train])]
        other=x[np.concatenate([chunks[i] for i in range(blocks) if i not in train])]
        chosen=np.isclose(first.mean(axis=0),first.mean(axis=0).max(),atol=1e-12,rtol=0)
        q=rankdata(other.mean(axis=0))[chosen]/(n+1)
        mean_failures.append(float(np.mean((q<.5)+.5*(q==.5))))
        si,so=sharpe(first),sharpe(other)
        if not (np.isfinite(si).all() and np.isfinite(so).all()):
            continue
        winners=np.isclose(si,si.max(),rtol=0,atol=1e-12)
        # Rank ties receive their average rank. Report below-median fraction, half weight for a tie.
        quantile=rankdata(so)[winners]/(n+1)
        failures.append(float(np.mean((quantile<.5)+.5*(quantile==.5))))
    return dict(days=len(x),variants=list(names),winner=names[best],daily_sharpe=float(r),
                assumed_independent_trials=n,null_max_daily_sharpe=float(null),deflated_sharpe_probability=dsr,
                sharpe_partitions=len(failures),sharpe_pbo=float(np.mean(failures)) if failures else None,
                mean_daily_r_partitions=len(mean_failures),mean_daily_r_pbo=float(np.mean(mean_failures)),
                limitations="Fixed-risk daily exit P&L omits intratrade marks. Recorded variants only. "
                            "DSR assumes independent trials and observations; overlapping and informal searches are unmeasured.")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("daily",nargs="?",default="research/aahil-wave/strategy-days.csv")
    print(json.dumps(evaluate(p.parse_args().daily),indent=2))
