"""Observe the displayed premium on BTC and ETH linear delivery futures versus spot."""
import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import json
import math
from pathlib import Path
from statistics import median
import time

import aiohttp

from dated_carry import COINS, net_per_unit
from flow_data import FUTURES, request_json, save_json
from perp_carry import HURDLE, WEIGHT
from spot_arb_scan import common_step, get, notional, timing

SPOT = "https://api.binance.com/api/v3"
SLEEVE = 5000.


def market_limits(spot, future):
    """Find a common legal base-quantity increment for marketable orders on both legs."""
    steps=[]
    minimum,maximum,min_usdt=0.,math.inf,0.
    for symbol in (spot,future):
        for f in symbol["filters"]:
            if f["filterType"] in ("LOT_SIZE","MARKET_LOT_SIZE"):
                step=Decimal(f["stepSize"])
                if step>0:
                    steps.append(step)
                minimum=max(minimum,float(f["minQty"]))
                if float(f["maxQty"])>0:
                    maximum=min(maximum,float(f["maxQty"]))
            elif f["filterType"] in ("MIN_NOTIONAL","NOTIONAL"):
                min_usdt=max(min_usdt,float(f.get("minNotional",f.get("notional",0))))
    return dict(step=str(common_step(steps)),min_qty=minimum,max_qty=maximum,min_usdt=min_usdt)


def contracts():
    spots={}
    for coin in COINS:
        pair=coin+"USDT"
        spot=request_json(SPOT+"/exchangeInfo",dict(symbol=pair))["symbols"][0]
        if spot["status"]=="TRADING":
            spots[pair]=spot
    futures=request_json(FUTURES+"/exchangeInfo",{})["symbols"]
    return {s["symbol"]:dict(pair=s["pair"],expiry_ms=int(s["deliveryDate"]),**market_limits(spots[s["pair"]],s))
            for s in futures if s["status"]=="TRADING" and s["pair"] in spots and s["marginAsset"]=="USDT"
            and s["contractType"] in ("CURRENT_QUARTER","NEXT_QUARTER")}


def server_clock(base):
    samples=[]
    for _ in range(3):
        start,end,r=get(base+"/time")
        samples.append((end-start,r["serverTime"]-(start+end)/2))
    rtt,offset=min(samples)
    if not 0<=rtt<=5000:
        raise ValueError("Invalid server clock calibration")
    return dict(offset=offset,uncertainty=rtt/2)


def estimate(spot,future,contract,days,sleeve=SLEEVE):
    """Assume the spot exit equals the delivery index, reserving USDT for the short."""
    if days<=0 or sleeve<=0:
        raise ValueError("expired_or_invalid_budget")
    ask,available=spot["ask"],spot["ask_qty"]
    best=future["bids"][0][0]
    step=Decimal(contract["step"])
    raw=min(WEIGHT*sleeve/max(ask,best),contract["max_qty"])
    qty=float((Decimal(str(raw))/step).to_integral_value(rounding=ROUND_DOWN)*step)
    if not qty or qty<contract["min_qty"]:
        raise ValueError("below_minimum_qty")
    if qty>available:
        raise ValueError("insufficient_displayed_spot_ask")
    sale=notional(future["bids"],qty)
    if min(ask*qty,sale)<contract["min_usdt"]:
        raise ValueError("below_minimum_notional")
    future_price=sale/qty
    gross,fee,slip,net=net_per_unit(ask,future_price,ask,ask)
    cash_hurdle=sleeve*HURDLE*days/365
    cushion=.0005*ask*qty
    stressed=net_per_unit(ask,future_price,ask*.9975,ask)[-1]*qty
    return dict(qty=qty,spot_ask=ask,futures_bid_vwap=future_price,days=days,
                premium_bps=10000*gross/ask,fees_usdt=fee*qty,slippage_usdt=slip*qty,
                conditional_net_usdt=qty*net,conditional_annual_simple_pct=100*qty*net/sleeve*365/days,
                capital_charge=cash_hurdle,buffer=cushion,excess_usdt=qty*net-cash_hurdle-cushion,
                net_if_exit_lags_index_25bps=stressed)


async def stream(session,url,latest,venue):
    async with session.ws_connect(url,heartbeat=15,compress=15) as ws:
        async for msg in ws:
            if msg.type!=aiohttp.WSMsgType.TEXT:
                break
            recv=time.time_ns()/1e6
            data=json.loads(msg.data)["data"]
            symbol=data["s"]
            if venue=="spot":
                ask,qty=float(data["a"]),float(data["A"])
                if not 0<float(data["b"])<ask<float("inf") or not 0<qty<float("inf"):
                    latest.pop(symbol,None)
                    continue
                quote=dict(event_ms=int(data["E"]),ask=ask,ask_qty=qty)
            else:
                bids=[(float(p),float(q)) for p,q in data["b"]]
                if (not bids or not data["a"] or any(min(p,q)<=0 or not math.isfinite(p*q) for p,q in bids)
                        or any(a[0]<=b[0] for a,b in zip(bids,bids[1:]))
                        or bids[0][0]>=float(data["a"][0][0])):
                    latest.pop(symbol,None)
                    continue
                quote=dict(event_ms=int(data["T"]),sequence=int(data["u"]),bids=bids)
            if symbol in latest and quote["event_ms"]<latest[symbol]["event_ms"]:
                continue
            latest[symbol]=dict(venue=venue,end_ms=recv,**quote)
    raise ConnectionError(f"{venue} public feed disconnected")


async def run(rounds,interval,sleeve):
    spec,spot_clock,fut_clock=await asyncio.gather(asyncio.to_thread(contracts),
        asyncio.to_thread(server_clock,SPOT),asyncio.to_thread(server_clock,FUTURES))
    if not spec:
        raise ValueError("No matching live delivery contracts")
    now=datetime.now(timezone.utc)
    path=Path("data/carry/quotes")/now.strftime("%Y%m%dT%H%M%S%fZ")
    path.mkdir(parents=True,exist_ok=False)
    clocks=dict(spot=spot_clock,futures=fut_clock)
    spot_stream="/".join(s.lower()+"@ticker" for s in sorted({c["pair"] for c in spec.values()}))
    fut_stream="/".join(s.lower()+"@depth10@500ms" for s in spec)
    save_json(path/"config.json",dict(contracts=spec,clocks=clocks,sleeve=sleeve,spot_stream=spot_stream,
                                      futures_stream=fut_stream))
    latest,seen,counts={},{},Counter()
    accepted=defaultdict(list)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as session:
        tasks=[asyncio.create_task(stream(session,host+names,latest,venue)) for host,names,venue in
               (("wss://stream.binance.com:443/stream?streams=",spot_stream,"spot"),
                ("wss://fstream.binance.com/public/stream?streams=",fut_stream,"futures"))]
        try:
            for i in range(rounds):
                await asyncio.sleep(interval)
                for task in tasks:
                    if task.done():
                        await task
                ts=time.time_ns()/1e6
                audit={}
                for symbol,c in spec.items():
                    try:
                        a,b=latest[c["pair"]],latest[symbol]
                        age,skew=timing(a,b,clocks,ts)
                        ids=(a["event_ms"],b["sequence"])
                        if symbol in seen and any(x<=y for x,y in zip(ids,seen[symbol])):
                            raise ValueError("repeated_or_out_of_sequence")
                        seen[symbol]=ids
                        days=(c["expiry_ms"]-ts-fut_clock["offset"])/86400000
                        row=estimate(a,b,c,days,sleeve)
                        accepted[symbol].append(dict(round=i+1,age_ms=age,skew_ms=skew,**row))
                        audit[symbol]=accepted[symbol][-1]
                    except KeyError:
                        audit[symbol]="waiting_for_books"
                    except ValueError as error:
                        audit[symbol]=str(error)
                    if isinstance(audit[symbol],str):
                        counts[audit[symbol]]+=1
                save_json(path/f"round-{i+1:03}.json",dict(observed_ms=ts,books=latest,checks=audit))
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    report=dict(start=now.isoformat(),end=datetime.now(timezone.utc).isoformat(),sleeve=sleeve,
                rounds=rounds,rejected=dict(counts),contracts={})
    for symbol in spec:
        rows=accepted[symbol]
        report["contracts"][symbol]=dict(accepted=len(rows),clear=sum(r["excess_usdt"]>0 for r in rows),
            median_conditional_net=median(r["conditional_net_usdt"] for r in rows) if rows else None,
            best=max(rows,key=lambda r:r["excess_usdt"]) if rows else None)
    save_json(path/"summary.json",report)
    print(path,json.dumps(report,indent=2))


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rounds",type=int,default=24)
    p.add_argument("--interval",type=float,default=2)
    p.add_argument("--sleeve",type=float,default=SLEEVE)
    args=p.parse_args()
    if args.rounds<1 or not 1<=args.interval<float("inf") or not 0<args.sleeve<float("inf"):
        p.error("Provide positive rounds and capital, and at least a one-second interval")
    asyncio.run(run(args.rounds,args.interval,args.sleeve))
