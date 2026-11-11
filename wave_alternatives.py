"""Four fixed 2025 alternative baselines using the Wave mandate and dated membership."""
from bisect import bisect_left
from collections import defaultdict
import csv
from datetime import date
import json
from itertools import groupby
from pathlib import Path

from backtest import FEE, SLIP, INITIAL
from flow_data import epoch
from wave_inputs import OUT, months, next_month
from wave_research import load_inputs, membership


def carry_cash(market, side, qty, entry_time, exit_time):
    # Positions open just before the next bar and flatten at the exit bar close.
    left = bisect_left(market.funding_times, entry_time*1000)
    right = bisect_left(market.funding_times, exit_time*1000)
    return -side*qty*sum(p.rate*p.mark for p in market.funding[left:right])


def trade(coin, side, start, end, entry, exit_price, qty, market=None, passive=False, spot=False):
    entry_exec = entry if passive else entry*(1+side*SLIP)
    exit_exec = exit_price*(1-side*SLIP)
    gross = side*qty*(exit_price-entry)
    slippage = side*qty*((exit_price-entry)-(exit_exec-entry_exec))
    fees = qty*FEE*(entry_exec+exit_exec)
    funding = carry_cash(market,side,qty,start,end) if market is not None else 0.
    return dict(coin=coin,instrument="spot" if spot else "perp",side=side,entry_time=start,exit_time=end,
                entry=entry_exec,exit=exit_exec,qty=qty,gross=gross,slippage=slippage,
                fees=fees,funding=funding,net=gross-slippage-fees+funding)


def resize(legs):
    """Compound using equity available before each nonoverlapping basket."""
    cash, peak, drawdown, available = INITIAL, INITIAL, 0., 0
    for t, group in groupby(sorted(legs,key=lambda r:r["entry_time"]),key=lambda r:r["entry_time"]):
        tranche=list(group)
        if t<available:
            raise ValueError("Overlapping basket cash accounting")
        scale=max(cash,0.)/INITIAL
        for leg in tranche:
            for field in ("qty","gross","fees","slippage","funding","net"):
                leg[field]*=scale
        cash+=sum(leg["net"] for leg in tranche)
        peak=max(peak,cash)
        drawdown=max(drawdown,1-cash/peak)
        available=max(leg["exit_time"] for leg in tranche)
    return drawdown


def momentum(markets, schedule, year_end):
    """Rotate only the net inventory change, paying fees on actual turnover."""
    cash=peak=INITIAL
    drawdown=0.
    holdings={}
    rows=[]
    for t, coins in sorted(schedule.items()):
        market=next(iter(markets.values()))
        i=(t-market.bars[0].time)//300
        j=min(i+288,(year_end-market.bars[0].time)//300-1)
        rank=sorted(coins,key=lambda c:markets[c].bars[i-1].close/markets[c].bars[i-1-7*288].close)
        target={}
        if len(rank)>=2 and cash>0:
            target={c:side*cash/(2*markets[c].bars[i].close) for c,side in ((rank[-1],1),(rank[0],-1))}
        for c in sorted(holdings.keys()|target.keys()):
            m=markets[c]
            entry=m.bars[i].close
            exit_price=m.bars[j].close
            qty=target.get(c,0.)
            delta=qty-holdings.get(c,0.)
            traded=abs(delta)*entry
            fees=traded*(1+direction(delta)*SLIP)*FEE
            gross=qty*(exit_price-entry)
            funding=carry_cash(m,1,qty,t+300,m.bars[j].time+300)
            if m.bars[j].time+300==year_end:
                traded+=abs(qty)*exit_price
                fees+=abs(qty)*exit_price*(1-direction(qty)*SLIP)*FEE
            slippage=traded*SLIP
            net=gross+funding-fees-slippage
            cash+=net
            rows.append(dict(strategy="momentum",coin=c,instrument="perp",side=direction(qty),
                        entry_time=t+300,exit_time=m.bars[j].time+300,entry=entry,exit=exit_price,
                        qty=abs(qty),gross=gross,slippage=slippage,fees=fees,funding=funding,net=net))
        holdings=target
        peak=max(peak,cash)
        drawdown=max(drawdown,1-cash/peak)
    return rows,drawdown


def direction(value):
    return (value>0)-(value<0)


def run():
    markets=load_inputs()
    ledger=[]
    def record(strategy,leg):
        ledger.append(dict(strategy=strategy,**leg))
    counters=defaultdict(int)
    schedule={}
    for m in months(date(2025,1,1),date(2026,1,1)):
        prev=date.fromordinal(m.toordinal()-1).replace(day=1)
        coins=[r["coin"] for r in membership(markets,prev) if r["member"]]
        start,end=epoch(m),epoch(next_month(m))
        schedule.update({t:coins for t in range(start,end,86400)})
        if not coins:
            continue
        context={c:json.loads((OUT/"context"/c/f"{m}.json").read_bytes()) for c in coins}
        first=markets[coins[0]].bars[0].time

        # Carry basket: weekly non-overlapping tranches, also flat at month end.
        for t in range(start+300,end,7*86400):
            end_trade=min(t+7*86400,end-300)
            if end_trade<=t+300:
                continue
            i=(t-first)//300
            j=(end_trade-first)//300
            for c in coins:
                market=markets[c]
                bars=market.bars
                spot=context[c]["spot"]
                last=bisect_left(market.funding_times,t*1000)-1
                observed=spot.get(str(t-300))
                if not observed or last<0 or market.funding[last].rate<=0 or bars[i-1].close<=observed:
                    continue
                entry_spot=spot.get(str(t))
                exit_spot=spot.get(str(end_trade-300))
                if not entry_spot or not exit_spot:
                    counters["carry_missing_execution_prices"]+=1
                    continue
                # Equal units hedge delta, including basis at entry. Each coin gets a fixed budget.
                qty=INITIAL/len(coins)/(entry_spot+bars[i].close)
                record("carry",trade(c,1,t+300,end_trade,entry_spot,exit_spot,qty,spot=True))
                record("carry",trade(c,-1,t+300,end_trade,bars[i].close,bars[j-1].close,qty,market))
        # Single-bar two-sided maker quotes, one pair per coin per hour.
        for c in coins:
            market=markets[c]
            bars=market.bars
            data=context[c]
            for t in range(start,end,3600):
                i=(t-first)//300
                window=bars[i-12:i]
                price=window[-1].close
                offset=max(price*.0005,(max(b.high for b in window)-min(b.low for b in window))/8)
                activation=bars[i+1]
                exit_price=bars[i+11].close
                for side in (1,-1):
                    entry=price-side*offset
                    counters["maker_quotes"]+=1
                    if side*(entry-activation.open)>=0:
                        counters["maker_postonly_rejections"]+=1
                        continue
                    extreme=activation.low if side==1 else activation.high
                    if side*(entry-extreme)<=0:
                        continue
                    # Half-budget on either side. Mark outstanding inventory out at the hour.
                    qty=INITIAL/(2*len(coins)*entry)
                    record("maker_proxy",trade(c,side,t+300,t+3600,entry,exit_price,qty,market,passive=True))
                # Liquidation observations cover only the free first day in each month.
                if not data["liq_covered"] or not start+3600<=t<=start+86400:
                    continue
                counters["fade_covered_coin_hours"]+=1
                notional=sum(b.quote for b in window)
                delta=sum(data["liquidations"].get(str(b.time),0.) for b in window)
                ret=price/window[0].open-1
                if not notional or abs(delta)/notional<.001 or abs(ret)<.005 or ret*delta<=0:
                    continue
                side=-1 if delta>0 else 1
                entry=bars[i].close
                record("cascade_fade",trade(c,side,t+300,t+3600,entry,exit_price,INITIAL/(len(coins)*entry),market))
    rotation,momentum_dd=momentum(markets,schedule,epoch(date(2026,1,1)))
    ledger.extend(rotation)
    results={}
    for name in ("carry","momentum","cascade_fade","maker_proxy"):
        legs=[r for r in ledger if r["strategy"]==name]
        drawdown=momentum_dd if name=="momentum" else resize(legs)
        totals={k:sum(r[k] for r in legs) for k in ("gross","slippage","fees","funding","net")}
        results[name]=dict(legs=len(legs),return_pct=100*totals["net"]/INITIAL,
                           realized_drawdown_pct=100*drawdown,**totals)
    folder=Path("data/alternative-audit")
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/"legs.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(ledger[0]))
        writer.writeheader()
        writer.writerows(ledger)
    payload=dict(initial_usdt=INITIAL,fee_per_leg=FEE,market_slip_per_leg=SLIP,counts=counters,results=results)
    (folder/"totals.json").write_text(json.dumps(payload,indent=2)+"\n",encoding="utf-8")
    return payload


if __name__=="__main__":
    print(json.dumps(run(),indent=2))
