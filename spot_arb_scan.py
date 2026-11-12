"""Read-only, prefunded KuCoin/Gate spot USDT depth comparison. Sends no orders."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import json
import math
from pathlib import Path
from statistics import median
import time
from urllib.request import Request, urlopen

from flow_data import save_json

COINS = ("BTC", "ETH", "SOL")
VENUES = ("kucoin", "gate")
KU = "https://api.kucoin.com"
GATE = "https://api.gateio.ws/api/v4"
MAX_AGE_MS = 2500
MAX_SKEW_MS = 1500
BUDGET = 1000.0
FEE_BPS = 10.0


def get(url):
    start = time.time_ns() / 1e6
    with urlopen(Request(url, headers={"User-Agent": "AahilWave-research/1"}), timeout=5) as response:
        body = response.read()
    end = time.time_ns() / 1e6
    return start, end, json.loads(body)


def clock(venue):
    """Minimum-RTT midnight-independent UTC clock estimate, with half-RTT uncertainty."""
    observations = []
    for _ in range(3):
        if venue == "kucoin":
            start, end, data = get(KU + "/api/v1/timestamp")
            stamp = int(data["data"])
        else:
            start, end, data = get(GATE + "/spot/time")
            stamp = int(data["server_time"])
        if stamp < 10**12 or not 0 <= end-start <= 5000:
            raise ValueError("Invalid clock calibration")
        observations.append((end-start, stamp-(start+end)/2))
    rtt, offset = min(observations)
    return {"offset": offset, "uncertainty": rtt/2}


def rules(coin):
    _, _, k = get(KU + "/api/v2/symbols/" + coin + "-USDT")
    _, _, g = get(GATE + "/spot/currency_pairs/" + coin + "_USDT")
    k = k["data"]
    if not k["enableTrading"] or g["trade_status"] != "tradable":
        raise ValueError(f"Both venues must allow trading in {coin}")
    def ceiling(kucoin_field, gate_fields):
        limits=[float(k[kucoin_field])]
        limits.extend(float(g[field]) for field in gate_fields if g.get(field) and float(g[field])>0)
        return min(limits)
    step = common_step([Decimal(k["baseIncrement"]), Decimal(1).scaleb(-int(g["amount_precision"]))])
    return dict(step=str(step), min_base=max(float(k["baseMinSize"]), float(g["min_base_amount"] or 0)),
                min_quote=max(float(k["minFunds"]),float(k["quoteMinSize"]),float(g["min_quote_amount"] or 0)),
                max_base=ceiling("baseMaxSize",("max_base_amount","market_order_max_stock")),
                max_quote=ceiling("quoteMaxSize",("max_quote_amount","market_order_max_money")))


def common_step(steps):
    scale=10**max(0,max(-s.as_tuple().exponent for s in steps))
    return Decimal(math.lcm(*(int(s*scale) for s in steps)))/scale


def book(venue, coin):
    if venue == "kucoin":
        start, end, data = get(KU + "/api/v1/market/orderbook/level2_20?symbol=" + coin + "-USDT")
        data = data["data"]
        stamp, seq = int(data["time"]), str(data["sequence"])
    else:
        start, end, data = get(GATE + "/spot/order_book?limit=20&with_id=true&currency_pair=" + coin + "_USDT")
        stamp, seq = int(data["update"]), str(data["id"])
    bids = [(float(p),float(q)) for p,q in data["bids"]]
    asks = [(float(p),float(q)) for p,q in data["asks"]]
    if (not bids or not asks or any(min(p,q)<=0 or not math.isfinite(p*q) for p,q in bids+asks)
            or bids[0][0]>=asks[0][0] or any(a[0]<=b[0] for a,b in zip(bids,bids[1:]))
            or any(a[0]>=b[0] for a,b in zip(asks,asks[1:]))):
        raise ValueError("Invalid or crossed spot book")
    return dict(venue=venue, coin=coin, start_ms=start, end_ms=end, event_ms=stamp,
                sequence=seq, bids=bids, asks=asks)


def timing(a,b,clocks,asof_ms=None):
    decision = max(a["end_ms"],b["end_ms"],asof_ms or 0)
    times, errors, ages = [], [], []
    for q in (a,b):
        c=clocks[q["venue"]]
        local=q["event_ms"]-c["offset"]
        err=c["uncertainty"]
        if local-err > q["end_ms"]+1:
            raise ValueError("clock_inconsistent")
        times.append(local)
        errors.append(err)
        ages.append(decision-local+err)
    skew=abs(times[0]-times[1])+sum(errors)
    if max(ages)>MAX_AGE_MS:
        raise ValueError("stale")
    if skew>MAX_SKEW_MS or abs(a["end_ms"]-b["end_ms"])>MAX_SKEW_MS:
        raise ValueError("skew")
    return max(ages),skew


def notional(levels,qty):
    remaining, total = qty,0.
    for p,q in levels:
        part=min(remaining,q)
        total+=p*part
        remaining-=part
        if remaining<=1e-12:
            return total
    raise ValueError("insufficient_depth")


def route(buy,sell,limits,fee_bps=FEE_BPS, budget=BUDGET):
    """Buy up to BUDGET excluding fees; use identical base quantity on both legs."""
    if not 0<budget<float("inf") or not 0<=fee_bps<10000:
        raise ValueError("Invalid budget or fee")
    qty,usd=0.,budget
    for p,q in buy["asks"]:
        part=min(q,usd/p)
        qty+=part
        usd-=p*part
        if usd<=1e-8:
            break
    if usd>1e-8:
        raise ValueError("insufficient_depth")
    step=Decimal(limits["step"])
    qty=float((Decimal(str(qty))/step).to_integral_value(rounding=ROUND_DOWN)*step)
    buy_cost=notional(buy["asks"],qty)
    proceeds=notional(sell["bids"],qty)
    if min(buy_cost,proceeds)<limits["min_quote"] or qty<limits["min_base"] or qty<=0:
        raise ValueError("below_minimum")
    if qty>limits.get("max_base",math.inf) or max(buy_cost,proceeds)>limits.get("max_quote",math.inf):
        raise ValueError("above_maximum")
    gross=proceeds-buy_cost
    fees=(buy_cost+proceeds)*fee_bps/10000
    return dict(coin=buy["coin"],buy=buy["venue"],sell=sell["venue"],qty=qty,buy_cost=buy_cost,
                proceeds=proceeds,gross_bps=10000*gross/buy_cost,fees=fees,net_usdt=gross-fees,
                net_bps=10000*(gross-fees)/buy_cost,break_even_fee_per_leg_bps=10000*gross/(proceeds+buy_cost))


def scan(rounds=24, interval=3, out=None, fee_bps=FEE_BPS, budget=BUDGET):
    now=datetime.now(timezone.utc)
    out=out or Path("data/spot-arb")/now.strftime("%Y%m%dT%H%M%S%fZ")
    out.mkdir(exist_ok=False,parents=True)
    rows, rejects, seen=[],Counter(),{}
    with ThreadPoolExecutor(max_workers=6) as pool:
        clocks=dict(zip(VENUES,pool.map(clock,VENUES)))
        limits=dict(zip(COINS,pool.map(rules,COINS)))
        save_json(out/"assumptions.json",dict(clock=clocks,limits=limits,fee_bps=fee_bps,budget=budget,
                                             max_age_ms=MAX_AGE_MS,max_skew_ms=MAX_SKEW_MS))
        for i in range(rounds):
            futures={(v,c):pool.submit(book,v,c) for c in COINS for v in VENUES}
            books, errors = {},{}
            for key,future in futures.items():
                try:
                    b=future.result()
                    previous_time, previous_sequence=seen.get(key,(0,0))
                    sequence=int(b["sequence"])
                    if b["event_ms"]<=previous_time or sequence<=previous_sequence:
                        raise ValueError("repeated_or_out_of_sequence")
                    seen[key]=(b["event_ms"],sequence)
                    books[key]=b
                except (OSError,ValueError,KeyError) as e:
                    errors["/".join(key)]=str(e)
            save_json(out/f"round-{i+1:03}.json",dict(books=list(books.values()),errors=errors))
            for c in COINS:
                if any((v,c) not in books for v in VENUES):
                    rejects["missing_or_repeated"]+=2
                    continue
                for source,dest in (VENUES,VENUES[::-1]):
                    try:
                        a,b=books[source,c],books[dest,c]
                        age,skew=timing(a,b,clocks)
                        rows.append(dict(round=i+1,age_upper_ms=age,skew_upper_ms=skew,**route(a,b,limits[c],fee_bps,budget)))
                    except ValueError as e:
                        rejects[str(e)]+=1
            if i+1<rounds:
                time.sleep(interval)
    save_json(out/"routes.json",rows)
    report=dict(start=now.isoformat(),end=datetime.now(timezone.utc).isoformat(),rounds=rounds,
                accepted=len(rows),rejected=dict(rejects))
    if rows:
        report.update(positive_gross=sum(r["gross_bps"]>0 for r in rows),
                      positive_net=sum(r["net_bps"]>0 for r in rows),
                      median_net_bps=median(r["net_bps"] for r in rows),
                      best=max(rows,key=lambda r:r["net_bps"]),worst=min(rows,key=lambda r:r["net_bps"]))
    save_json(out/"summary.json",report)
    print(out, json.dumps(report,indent=2))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rounds",type=int,default=24)
    p.add_argument("--interval",type=float,default=3)
    p.add_argument("--out",type=Path)
    p.add_argument("--fee-bps",type=float,default=FEE_BPS,help="assumed taker fee on each venue")
    p.add_argument("--budget",type=float,default=BUDGET,help="USDT gross buy notional before fees")
    args=p.parse_args()
    if args.rounds<1 or not 1<=args.interval<float("inf") or not 0<=args.fee_bps<10000 or not 0<args.budget<float("inf"):
        p.error("use positive rounds and budget, at least a one-second interval, and a valid nonnegative fee")
    scan(args.rounds,args.interval,args.out,args.fee_bps,args.budget)
