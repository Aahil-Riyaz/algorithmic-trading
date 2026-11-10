"""Independent retrospective replay of manually transcribed perpetual signals."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from itertools import product
import json
import math
from pathlib import Path
import random
from statistics import mean, median

from discord_market import Bar, interval_data
from flow_data import FUTURES, request_json, save_json

MINUTE = 60
VALID = 8*3600
FOLLOW = 24*3600
CLOSED = {"TP","SL","BE"}
RESOLVED = CLOSED | {"expired","invalidated"}
SCENARIOS = ("maker_maker","maker_taker_stop","taker_taker")


def iso(t):
    return datetime.fromtimestamp(t,timezone.utc).isoformat() if t is not None else ""


@dataclass(frozen=True)
class Order:
    t: int
    side: int
    entry: float
    stop: float
    target: float
    wave1: float | None = None

    @property
    def risk(self):
        return self.side*(self.entry-self.stop)


@dataclass
class Result:
    status: str
    fill: int | None = None
    end: int | None = None
    exit: float | None = None
    ambiguous: int = 0


def groups(bars, width, breaks):
    """Aggregate available minutes on the UTC grid, splitting at the expiry boundary."""
    if width == 60:
        return bars
    result = []
    for b in bars:
        if not result or b.time%width == 0 or b.time in breaks:
            result.append(b)
        else:
            p = result[-1]
            result[-1] = Bar(p.time,p.open,max(p.high,b.high),min(p.low,b.low),b.close)
    return result


def simulate(bars, order, width=60, touch=False, be="none", wave=False, delay=60, through=None):
    """bars is a nonempty contiguous 1m tape. Results use bar-open timestamps."""
    if order.risk <= 0 or order.side*(order.target-order.entry)<=0:
        raise ValueError("Invalid trade geometry")
    expiry = order.t+VALID
    begin = order.t+delay
    if begin < bars[0].time:
        return Result("missing_data")
    i = (begin-bars[0].time)//60
    end_data = min(bars[-1].time+60,through) if through is not None else bars[-1].time+60
    j = (min(expiry+FOLLOW,end_data)-bars[0].time)//60
    path = groups(bars[i:j],width,{expiry})
    fill, stop, armed, ambiguity = None, order.stop, False, 0
    for b in path:
        if fill is None:
            if b.time >= expiry:
                return Result("expired",end=expiry,ambiguous=ambiguity)
            penetration = ((order.entry-b.low) if order.side==1 else (b.high-order.entry))
            hit = penetration>=0 if touch else penetration>0
            invalid = wave and order.wave1 is not None and (
                b.high >= order.wave1 if order.side == 1 else b.low <= order.wave1)
            if invalid:
                # Both hit in the same candle has unknown order; return a distinct category.
                return Result("ambiguous_invalidation" if hit else "invalidated",end=b.time,
                              ambiguous=int(hit))
            if not hit:
                continue
            fill = b.time
        if b.time >= fill+FOLLOW:
            return Result("open_at_horizon",fill,end=fill+FOLLOW,ambiguous=ambiguity)
        sl = b.low<=stop if order.side==1 else b.high>=stop
        tp = b.high>=order.target if order.side==1 else b.low<=order.target
        if sl and tp:
            ambiguity += 1
        if sl:
            price = min(stop,b.open) if order.side==1 else max(stop,b.open)
            return Result("BE" if armed else "SL",fill,b.time,price,ambiguity)
        # A favorable extreme could precede a resting fill. Defer the target and
        # BE observation until the next candle unless the open already crossed entry.
        from_open = (order.side*(b.open-order.entry) < 0 or (touch and b.open==order.entry))
        if b.time==fill and not from_open:
            ambiguity += int(tp)
            continue
        if tp:
            return Result("TP",fill,b.time,order.target,ambiguity)
        favorable = (b.high-order.entry) if order.side==1 else (order.entry-b.low)
        if ((be in ("0.5R","1R") and favorable >= float(be[:-1])*order.risk) or
                (be=="30min" and b.time-fill>=1800 and order.side*(b.close-order.entry)>0)):
            armed, stop = True, order.entry
    if fill is not None:
        horizon = fill+FOLLOW
        return Result("open_at_horizon" if end_data>=horizon else "open_at_cutoff",fill,
                      min(horizon,end_data),ambiguous=ambiguity)
    return Result("expired" if end_data>=expiry else "pending_at_cutoff",end=min(end_data,expiry))


def accounting(order,result,funding,maker,taker,slip):
    if result.status in ("invalidated","expired"):
        return {"gross_r":0., "funding_r":0., **dict.fromkeys(SCENARIOS,0.)}
    if result.status not in CLOSED:
        return dict.fromkeys(("gross_r","funding_r",*SCENARIOS),None)
    gross = order.side*(result.exit-order.entry)/order.risk
    carry = 0.
    for stamp,rate,mark in funding:
        minute = stamp//60000*60
        if result.fill<=minute<=result.end:
            cash = -order.side*rate*mark/order.risk
            carry += min(0.,cash) if minute in (result.fill,result.end) else cash
    # Entry/exit are executable proxies. Slip is charged on taker legs only.
    net = {}
    for name in SCENARIOS:
        aggressive_entry = name=="taker_taker"
        aggressive_exit = aggressive_entry or (name=="maker_taker_stop" and result.status!="TP")
        entry = order.entry*(1+order.side*(slip/10000 if aggressive_entry else 0.))
        exit_price = result.exit*(1-order.side*(slip/10000 if aggressive_exit else 0.))
        fees = (entry*(taker if aggressive_entry else maker)+exit_price*(taker if aggressive_exit else maker))/10000
        net[name] = (order.side*(exit_price-entry)-fees)/order.risk+carry
    return {"gross_r":gross,"funding_r":carry,**net}


def read_order(row):
    return Order(int(datetime.fromisoformat(row["signal_time"]).timestamp()),1 if row["side"]=="LONG" else -1,
                 float(row["entry"]),float(row["stop"]),float(row["target"]),
                 float(row["wave1"]) if row["wave1"] else None)


def half_unit(price):
    return float(Decimal(1).scaleb(Decimal(price).as_tuple().exponent)/2)


def rounded_variants(bars,o,r):
    possibilities = set()
    for deltas in product((-1,1),repeat=3):
        levels = [float(r[k])+s*half_unit(r[k]) for k,s in zip(("entry","stop","target"),deltas)]
        candidate = replace(o,entry=levels[0],stop=levels[1],target=levels[2])
        if candidate.risk > 0 and candidate.side*(candidate.target-candidate.entry)>0:
            possibilities.add(simulate(bars,candidate).status)
    return "|".join(sorted(possibilities))


def compare(a,b):
    return (a!=b) if a in RESOLVED and b in RESOLVED else None


def compare_counts(rows,key,fold=None):
    cases = [r for r in rows if r["outcome"] in RESOLVED and r[key] in RESOLVED
             and (fold is None or r["outcome"] in fold)]
    return dict(comparable=len(cases),mismatches=sum(r["outcome"]!=r[key] for r in cases),
                confusion=dict(Counter(r["outcome"]+" -> "+r[key] for r in cases)))


def replay_row(row,tape,funds,fees):
    o = read_order(row)
    r = simulate(tape,o)
    wave = simulate(tape,o,wave=True)
    posted = float(row["posted_price"])
    minute = tape[(o.t-tape[0].time)//60]
    # The parser's hypothetical costs apply to reported outcomes; preserve both.
    source = {("reported_"+k if k in SCENARIOS else k):v for k,v in row.items()}
    line = dict(source,rebuilt=r.status,fill_utc=iso(r.fill),end_bar_utc=iso(r.end),
                exit_price=r.exit,**accounting(o,r,funds,*fees),ambiguous_bars=r.ambiguous,
                mismatch=compare(row["outcome"],r.status),wave1_diagnostic=wave.status,
                wave1_end_bar=iso(wave.end),mismatch_with_wave1=compare(row["outcome"],wave.status),
                post_minute_open=minute.open,post_minute_close=minute.close,
                posted_price_in_minute=minute.low<=posted<=minute.high,
                close_error_bps=10000*(minute.close/posted-1),
                posted_entry_offset_r=o.side*(posted-o.entry)/o.risk,
                posted_entry_offset_bps=o.side*(posted-o.entry)/posted*10000,
                past_target_at_post=o.side*(posted-o.target)>=0,
                past_reported_wave1_at_post=None if o.wave1 is None else o.side*(posted-o.wave1)>=0,
                rounding_envelope=rounded_variants(tape,o,row))
    if row["outcome_time"] and r.end is not None:
        reported_t = int(datetime.fromisoformat(row["outcome_time"]).timestamp())
        line["end_minus_reported_minutes"] = (r.end-reported_t)//60
        if wave.end is not None:
            line["wave1_end_minus_reported_minutes"] = (wave.end-reported_t)//60
    for name,params in (("touch",dict(touch=True)),("five_min",dict(width=300)),
                        ("include_post_min",dict(delay=0)),("be_half_r",dict(be="0.5R")),
                        ("be_one_r",dict(be="1R")),("be_30min",dict(be="30min"))):
        alt = simulate(tape,o,**params)
        line[name] = alt.status
        line[name+"_net_r"] = accounting(o,alt,funds,*fees)["maker_taker_stop"]
    inferred = simulate(tape,o,wave=True,be="0.5R")
    line["inferred_wave_half_r"] = inferred.status
    line["inferred_end_bar"] = iso(inferred.end)
    line.update({"inferred_"+k:v for k,v in accounting(o,inferred,funds,*fees).items()})
    shown = replace(o,entry=float(row["reported_entry"] or o.entry))
    if row["reported_exit"] and row["outcome"] in ("SL","TP"):
        shown = replace(shown,**{"stop" if row["outcome"]=="SL" else "target":float(row["reported_exit"])})
    line["exit_message_levels"] = simulate(tape,shown).status if shown.risk>0 and shown.side*(shown.target-shown.entry)>0 else "invalid_geometry"
    return line


def random_baseline(rows,markets,fees,reps,seed):
    rng = random.Random(seed)
    means,counts,fill_rates = [],[],[]
    for _ in range(reps):
        values,filled = [],0
        for row in rows:
            o = read_order(row)
            tape,funding,_ = markets[row["coin"]]
            # Pick a random minute on the same UTC day, with at least the original
            # amount of observed follow-up. Scale every posted distance together.
            day = o.t//86400*86400
            last_start = tape[-1].time-min((VALID+FOLLOW),tape[-1].time-o.t)
            lo = max(day,tape[0].time)
            hi = min(day+86340,last_start)
            t = rng.randrange(lo//60,hi//60+1)*60
            idx = (t-tape[0].time)//60
            source_price = tape[max(0,idx-1)].close
            scale = source_price/float(row["posted_price"])
            random_order = Order(t,o.side,o.entry*scale,o.stop*scale,o.target*scale)
            duration = min(VALID+FOLLOW,tape[-1].time+60-o.t)
            result = simulate(tape,random_order,through=t+duration)
            val = accounting(random_order,result,funding,*fees)["maker_taker_stop"]
            filled += result.fill is not None
            if val is not None:
                values.append(val)
        if values:
            means.append(mean(values))
            counts.append(len(values))
            fill_rates.append(filled/len(rows))
    means.sort()
    return dict(draws=reps,seed=seed,known_signals_range=[min(counts),max(counts)],
                median_net_r_per_resolved_signal=median(means),
                central_95pct=[means[int(.025*(len(means)-1))],means[int(.975*(len(means)-1))]],
                median_fill_rate=median(fill_rates))


def run(source,out,through=None,maker=2.,taker=5.,slip=1.,reps=100,seed=817):
    with source.open(encoding="utf-8-sig",newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError("No parsed signals")
    fees = (maker,taker,slip)
    if min(fees)<0 or not all(map(math.isfinite,fees)) or reps<1:
        raise ValueError("Invalid costs or random draws")
    stamps = [read_order(r).t for r in rows]
    start = min(stamps)//86400*86400-86400
    exchange_end = request_json(FUTURES+"/time",{})["serverTime"]//60000*60
    through = int(datetime.fromisoformat(through).timestamp()) if through else exchange_end
    end = min(through,exchange_end,max(stamps)+VALID+FOLLOW)
    end = end//60*60
    if end<=max(stamps):
        raise ValueError("Exchange cutoff precedes a posted signal")
    coins = sorted({r["coin"] for r in rows})
    with ThreadPoolExecutor(max_workers=2) as pool:
        markets = dict(zip(coins,pool.map(lambda c:interval_data(c,start,end,out/"market"),coins)))
    audit = [replay_row(r,*markets[r["coin"]][:2],fees) for r in rows]
    fields = list(dict.fromkeys(k for r in audit for k in r))
    with (out/"rebuilt.csv").open("w",newline="",encoding="utf-8") as f:
        writer = csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        writer.writerows(audit)
    offsets = {}
    for hours in (-4,0,4):
        errors,inside = [],0
        for r in rows:
            o = read_order(r)
            tape = markets[r["coin"]][0]
            i = (o.t+hours*3600-start)//60
            if 0<=i<len(tape):
                posted = float(r["posted_price"])
                b = tape[i]
                errors.append(abs(10000*(b.close/posted-1)))
                inside += b.low<=posted<=b.high
        offsets[str(hours)] = dict(n=len(errors),median_abs_close_error_bps=median(errors),in_range=inside)
    summary = dict(input_signals=len(rows),start=iso(start),through_exclusive=iso(end),alignment=offsets,
                   source_sha256={c:v[2] for c,v in markets.items()},cost_bps=fees,
                   counts=dict(Counter(r["rebuilt"] for r in audit)),reported=dict(Counter(r["outcome"] for r in audit)),
                   primary=compare_counts(audit,"rebuilt"),known_wave=compare_counts(audit,"wave1_diagnostic"),
                   inferred=compare_counts(audit,"inferred_wave_half_r"),
                   sensitivity={k:compare_counts(audit,k,CLOSED|{"expired"}) for k in (
                       "rebuilt","five_min","touch","include_post_min","be_half_r","be_one_r","be_30min","exit_message_levels")},
                   baseline=random_baseline(rows,markets,fees,reps,seed))
    closed = [r for r in audit if r["rebuilt"] in CLOSED]
    known = [r for r in audit if r["rebuilt"] in RESOLVED]
    inferred = [r for r in audit if r["inferred_wave_half_r"] in CLOSED]
    summary.update(net_r_per_fill={s:mean(r[s] for r in closed) if closed else None for s in SCENARIOS},
                   inferred_net_r_per_fill={s:mean(r["inferred_"+s] for r in inferred) if inferred else None for s in SCENARIOS},
                   inferred_fills=len(inferred),
                   net_r_per_resolved_signal={s:mean(r[s] for r in known) if known else None for s in SCENARIOS},
                   gross_closed_total=sum(r["gross_r"] for r in closed),
                   total_funding_r=sum(r["funding_r"] for r in closed),
                   median_entry_offset_bps=median(r["posted_entry_offset_bps"] for r in audit),
                   posted_past_target=sum(r["past_target_at_post"] for r in audit),
                   posted_past_wave1=sum(r["past_reported_wave1_at_post"] is True for r in audit),
                   wave1_available=sum(bool(r["wave1"]) for r in audit),
                   rounding_changes=sum(any(x!=r["rebuilt"] for x in r["rounding_envelope"].split("|")) for r in audit),
                   reported_precision_changes=sum(r["exit_message_levels"]!=r["rebuilt"] for r in audit),
                   coarse_changes=sum(r["five_min"]!=r["rebuilt"] for r in audit))
    save_json(out/"replay-summary.json",summary)
    print(json.dumps(summary,indent=2))
    return summary


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--signals",type=Path,default=Path("data/discord-audit/signals.csv"))
    parser.add_argument("--out",type=Path,default=Path("data/discord-audit"))
    parser.add_argument("--through",help="UTC exclusive end from an earlier run's manifest")
    parser.add_argument("--maker-bps",type=float,default=2)
    parser.add_argument("--taker-bps",type=float,default=5)
    parser.add_argument("--slip-bps",type=float,default=1)
    parser.add_argument("--random-draws",type=int,default=100)
    args = parser.parse_args()
    run(args.signals,args.out,args.through,args.maker_bps,args.taker_bps,args.slip_bps,args.random_draws)
