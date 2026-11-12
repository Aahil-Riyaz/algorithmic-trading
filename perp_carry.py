"""Test a lagged-funding hedge, passive carry and cash on identical dated markets."""
from bisect import bisect_left
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta
import json
from pathlib import Path

import numpy as np

from carry_prices import BAR, perp_mark_highs, perp_month, spot_month
from flow_data import ROOT, epoch, funding_file, save_json
from wave_inputs import COINS, months, next_month, prepare
from wave_research import membership_for_month
from wave_validation import write_csv

CAPITAL = 10_000.
WEIGHT = .4
SPOT_FEE, PERP_FEE, SLIP = .001, .0005, .0002
HURDLE = .04
OUT = Path("research/carry")
PERIODS = {"development":(date(2024,1,1),date(2026,1,1)),
           "later":(date(2026,1,1),date(2026,10,1))}


@dataclass
class Panel:
    closes: np.ndarray
    spot: np.ndarray
    perp: np.ndarray
    traded: np.ndarray
    mark_high: np.ndarray
    unit_funding: np.ndarray
    stressed_funding: np.ndarray
    times_ms: list
    rates: list


def load_panel(coin, start, end):
    # One preceding month supplies strictly lagged rates at the first decision.
    prior = (start-timedelta(days=1)).replace(day=1)
    stamps,spot,perp,traded,funding,highs = [],[],[],[],[],[]
    for month in months(prior,end):
        funding_file((coin,month))
        funding.extend(json.loads((ROOT/"funding"/coin/f"{month:%Y-%m}.json").read_bytes()))
        if month==prior:
            continue
        prepare((coin,month))
        a,b=spot_month(coin,month),perp_month(coin,month)
        mark=perp_mark_highs(coin,month)
        opens=range(epoch(month),epoch(next_month(month)),BAR)
        if set(a)!=set(opens) or set(b)!=set(opens):
            raise ValueError(f"{coin} non-contiguous spot/perp grid in {month}")
        for t in opens:
            stamps.append(t+BAR)
            spot.append(a[t].price)
            perp.append(b[t].price)
            traded.append(min(a[t].qty,b[t].qty)>0 and min(a[t].trades,b[t].trades)>0)
            highs.append(mark[t])
    ts=[int(r["fundingTime"]) for r in funding]
    rates=[float(r["fundingRate"]) for r in funding]
    marks=[float(r["markPrice"]) for r in funding]
    if ts!=sorted(set(ts)) or any(not np.isfinite(v) for v in rates+marks) or min(marks)<=0:
        raise ValueError(f"{coin} inconsistent funding series")
    closes=np.array(stamps,dtype=np.int64)
    # A holding from close A to close B pays/receives settlements in [A,B).
    ix=np.searchsorted(closes*1000,ts,side="right")
    keep=(np.array(ts)>=epoch(start)*1000)&(ix<len(closes))
    flows=(np.array(rates)*marks)[keep]
    normal=np.zeros(len(closes))
    stress=np.zeros(len(closes))
    np.add.at(normal,ix[keep],flows)
    np.add.at(stress,ix[keep],np.where(flows>0,flows*.5,flows))
    return Panel(closes,np.array(spot),np.array(perp),np.array(traded),np.array(highs),normal,stress,ts,rates)


def funding_projection(m,decision,days):
    start=(decision-30*86400)*1000
    lo,hi=bisect_left(m.times_ms,start),bisect_left(m.times_ms,decision*1000)
    window=m.times_ms[lo:hi]
    if not window or max(np.diff([start]+window+[decision*1000]))>9*3600_000:
        return None
    return sum(m.rates[lo:hi])*days/30


def clears_costs(forecast,spot,perp,days):
    costs=2*((SPOT_FEE+SLIP)*spot+(PERP_FEE+SLIP)*perp)
    capital=max(spot,perp)/WEIGHT
    return forecast is not None and forecast*perp>costs+capital*HURDLE*days/365


def trade_cost(delta, spot, perp):
    # Increasing means buying spot while selling futures. Pay fees on slipped prices.
    signed_slip=np.sign(delta)*SLIP
    fees=abs(delta)*(spot*(1+signed_slip)*SPOT_FEE+perp*(1-signed_slip)*PERP_FEE)
    return fees,abs(delta)*(spot+perp)*SLIP


def sleeve(coin,m,start,end,members,rule):
    equity=CAPITAL/len(COINS)
    path=np.full(len(m.closes),equity)
    qty=0.
    cycle_start=None
    cycles=[]
    ledger=[]
    totals=Counter()
    for month in months(start,end):
        decision=epoch(month)+BAR
        i=int(np.searchsorted(m.closes,decision+BAR))
        exit_ts=epoch(end) if next_month(month)==end else epoch(next_month(month))+2*BAR
        j=int(np.searchsorted(m.closes,exit_ts))
        if m.closes[i-1]!=decision or m.closes[i]!=decision+BAR or m.closes[j]!=exit_ts:
            raise ValueError("Decision or holding boundary missing")
        days=(next_month(month)-month).days
        forecast=funding_projection(m,decision,days)
        eligible=coin in members[month]
        take=eligible and (rule=="passive" or clears_costs(forecast,m.spot[i-1],m.perp[i-1],days))
        # Size uses only decision-time marks. The later paired closes determine fills and costs.
        decision_equity=path[i-1]
        new_qty=max(decision_equity,0.)*WEIGHT/max(m.spot[i-1],m.perp[i-1]) if take else 0.
        old=qty
        if (new_qty!=old and not m.traded[i]) or (eligible and not m.traded[i-1]):
            raise ValueError(f"{coin} illiquid/missing boundary {month}")
        fee,slip=trade_cost(new_qty-old,m.spot[i],m.perp[i])
        if old==0 and new_qty>0:
            cycle_start=(int(m.closes[i]),equity)
        equity-=fee+slip
        if old>0 and new_qty==0:
            cycles.append(dict(coin=coin,start=cycle_start[0],end=int(m.closes[i]),net=equity-cycle_start[1]))
            cycle_start=None
        qty=new_qty
        path[i]=equity
        held=slice(i+1,j+1)
        basis=qty*((m.spot[held]-m.spot[i])-(m.perp[held]-m.perp[i]))
        funding=qty*np.cumsum(m.unit_funding[held])
        min_margin=None
        if qty:
            marks=m.mark_high[held]
            collateral=equity-qty*m.spot[i]
            adverse_carry=funding-qty*np.maximum(m.unit_funding[held],0)
            margin_ratio=(collateral+qty*(m.perp[i]-marks)+adverse_carry)/(qty*marks)
            min_margin=float(np.min(margin_ratio))
            if min_margin<.01:
                raise ValueError(f"Margin stress breached on {coin} in {month}; liquidation replay needed")
            totals["deployed_hurdle"]+=equity*HURDLE*(exit_ts-m.closes[i])/(365*86400)
        stress=qty*sum(m.stressed_funding[held])
        path[held]=equity+basis+funding
        equity=float(path[j])
        turnover=abs(new_qty-old)*(m.spot[i]+m.perp[i])
        if exit_ts==epoch(end) and qty>0:
            if not m.traded[j]:
                raise ValueError("Missing final executable prices")
            exit_fee,exit_slip=trade_cost(-qty,m.spot[j],m.perp[j])
            fee+=exit_fee
            slip+=exit_slip
            turnover+=qty*(m.spot[j]+m.perp[j])
            equity-=exit_fee+exit_slip
            path[j]=equity
            cycles.append(dict(coin=coin,start=cycle_start[0],end=int(m.closes[j]),net=equity-cycle_start[1]))
        totals.update(dict(basis=basis[-1],funding=funding[-1],stress_funding=stress,fees=fee,slippage=slip,turnover=turnover))
        ledger.append(dict(coin=coin,month=str(month),member=eligible,decision_utc=decision,active_utc=int(m.closes[i]),
                           projected_rate=forecast,qty=qty,entry_spot=m.spot[i],entry_perp=m.perp[i],
                           basis_pnl=basis[-1],funding=funding[-1],fees=fee,slippage=slip,turnover=turnover,
                           min_intrabar_short_margin_ratio=min_margin,
                           net=basis[-1]+funding[-1]-fee-slip))
    if not np.isclose(equity-CAPITAL/len(COINS),sum(v["net"] for v in cycles),atol=1e-7):
        raise ValueError("Round-trip ledger does not reconcile")
    return path,totals,ledger,cycles


def pnl_interval(days):
    rng=np.random.default_rng(93)
    groups=(len(days)+6)//7
    indices=(rng.integers(len(days),size=(5000,groups,1))+np.arange(7))%len(days)
    indices=indices.reshape(5000,-1)[:,:len(days)]
    return np.quantile(days[indices].sum(axis=1),[.025,.975]).tolist()


def run():
    OUT.mkdir(parents=True,exist_ok=True)
    report={}
    ledger=[]
    cycles=[]
    for period,(start,end) in PERIODS.items():
        members={m:{r["coin"] for r in membership_for_month(m) if r["member"]} for m in months(start,end)}
        results={}
        data={c:load_panel(c,start,end) for c in COINS}
        quality={}
        for c,p in data.items():
            bp=10000*(p.perp/p.spot-1)
            quality[c]=dict(bars=len(bp),both_traded=int(p.traded.sum()),basis_bps_p01_p50_p99=np.quantile(bp,[.01,.5,.99]).tolist(),
                            abs_basis_above_100bps=int((np.abs(bp)>100).sum()))
        days=(end-start).days
        for rule in ("lagged","passive"):
            totals=Counter()
            paths=[]
            episodes=[]
            for coin,p in data.items():
                path,costs,rows,ends=sleeve(coin,p,start,end,members,rule)
                paths.append(path)
                totals.update(costs)
                ledger.extend(dict(period=period,rule=rule,**r) for r in rows)
                episodes.extend(ends)
            cycles.extend(dict(period=period,rule=rule,**r) for r in episodes)
            curve=sum(paths)
            daily=np.diff(np.r_[CAPITAL,curve[287::288]])
            profit=float(curve[-1]-CAPITAL)
            if not np.isclose(profit,totals["basis"]+totals["funding"]-totals["fees"]-totals["slippage"]):
                raise ValueError("Portfolio P&L mismatch")
            peaks=np.maximum.accumulate(curve)
            results[rule]=dict(**totals,net=profit,return_pct=100*profit/CAPITAL,
                excess_4pct_cash_usdt=profit-CAPITAL*days/365*HURDLE,
                excess_over_deployed_hurdle=profit-totals["deployed_hurdle"],
                positive_funding_halved_net=profit+totals["stress_funding"]-totals["funding"],
                max_drawdown_pct=float(np.max((peaks-curve)/peaks)*100),
                seven_day_bootstrap_net_usdt=pnl_interval(daily),episodes=len(episodes),
                winning_episodes=sum(int(r["net"]>0) for r in episodes),
                additional_friction_break_even_bps=10000*profit/totals["turnover"] if totals["turnover"] else None)
        report[period]=dict(start=str(start),end_exclusive=str(end),rules=results,quality=quality)
        print(period, {k:(round(v["net"],2),v["episodes"]) for k,v in results.items()},flush=True)
    write_csv(OUT/"perp-months.csv",ledger)
    write_csv(OUT/"perp-episodes.csv",cycles)
    save_json(OUT/"perp-results.json",report)


if __name__=="__main__":
    run()
