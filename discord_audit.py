"""Audit hand-copied Discord embeds, preserving source lines and unresolved events."""
import argparse
import csv
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import statistics

import numpy as np

DUBAI = timezone(timedelta(hours=4))
NUM = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?"
STAMP = r"(?:\d{2}/\d{2}/\d{4}, |(?:Yesterday|Today) at )\d{2}:\d{2}"
SIGNAL = re.compile(r"^([A-Z0-9]+)USDT (LONG|SHORT) \[CRYPTO\]$")
EVENT = re.compile(r"(TP Hit|Stop Hit|Break-even|Setup Invalidated|Cancel Order) — ([A-Z0-9]+)USDT (LONG|SHORT)$")
KINDS = {"TP Hit":"TP", "Stop Hit":"SL", "Break-even":"BE", "Setup Invalidated":"invalidated", "Cancel Order":"expired"}
CLOSED = ("TP","SL","BE")
SCENARIOS = ("maker_maker","maker_taker_stop","taker_taker")


def utc(value, as_of):
    if " at " in value:
        day, hm = value.split(" at ")
        local = datetime.combine(as_of-timedelta(days=day == "Yesterday"), datetime.strptime(hm,"%H:%M").time())
    else:
        local = datetime.strptime(value,"%d/%m/%Y, %H:%M")
    return local.replace(tzinfo=DUBAI).astimezone(timezone.utc).isoformat()


def printed_match(original, printed):
    # Exit cards drop trailing zeros (8.79, 97.9). Use their displayed resolution.
    center = Decimal(printed)
    unit = Decimal(1).scaleb(center.as_tuple().exponent)
    return abs(Decimal(original)-center) <= unit/2


def capture(text, regex, default=""):
    hit = re.search(regex, text, re.MULTILINE)
    return hit.group(1) if hit else default


def parse(text, as_of):
    lines = [v.strip() for v in text.splitlines()]
    signals, events, stats, issues = [], [], [], []
    i = 0
    while i < len(lines):
        line = lines[i]
        header = SIGNAL.fullmatch(line)
        event = EVENT.search(line)
        if header:
            # An embed repeats the symbol above its price footer.
            if i+1 >= len(lines) or lines[i+1] != "Confidence":
                issues.append(dict(line=i+1, reason="incomplete signal"))
                i += 1
                continue
            block = lines[i:i+16]
            footer = next((k for k,v in enumerate(block) if v.startswith("Price ")),None)
            if footer is None:
                raise ValueError(f"Signal without price and timestamp on line {i+1}")
            fields = dict(zip(block[1:9:2],block[2:9:2]))
            match = re.fullmatch(rf"Price ({NUM})•({STAMP})",block[footer])
            if not match or not re.fullmatch("●*○*", fields["Confidence"]) or len(fields["Confidence"])!=5:
                raise ValueError(f"Unrecognized signal on line {i+1}")
            coin,side = header.groups()
            row = dict(signal_id=f"S{i+1:05}",line=i+1,signal_time=utc(match[2],as_of),
                       coin=coin,side=side,entry=fields["Entry"],stop=fields["Stop"],target=fields["Target"],
                       posted_price=match[1],confidence=fields["Confidence"].count("●"),
                       outcome="unresolved",outcome_time="",outcome_line="",wave1="",reported_r="",
                       reported_entry="",reported_exit="")
            if not (float(row["stop"]) < float(row["entry"]) < float(row["target"]) if side=="LONG"
                    else float(row["target"]) < float(row["entry"]) < float(row["stop"])):
                raise ValueError(f"Invalid geometry on line {i+1}")
            if any(all(s[k]==row[k] for k in ("signal_time","coin","side","entry","stop","target","confidence","posted_price")) for s in signals):
                issues.append(dict(line=i+1,reason="duplicate signal"))
            else:
                signals.append(row)
            i += footer+1
            continue
        if event or line.startswith("Trade Stats"):
            j = i+1
            while j<len(lines) and not re.fullmatch(STAMP,lines[j]):
                if lines[j] in ("APP","@Algo Crypto") or EVENT.search(lines[j]) or SIGNAL.fullmatch(lines[j]):
                    break
                j+=1
            if j==len(lines) or not re.fullmatch(STAMP,lines[j]):
                raise ValueError(f"Event on line {i+1} has no timestamp")
            stamp = utc(lines[j],as_of)
            if event:
                kind,coin,side = event.groups()
                body = "\n".join(lines[i+1:j])
                printed_entry = capture(body,rf"(?:Entry |Stop moved to entry )({NUM})")
                printed_exit = capture(body,rf"(?:Target |Stop |Stop moved to entry )({NUM})")
                events.append(dict(coin=coin,side=side,outcome=KINDS[kind],outcome_time=stamp,outcome_line=i+1,
                                   wave1=capture(body,rf"Wave 1 \(({NUM})\)"),
                                   reported_r=capture(body,rf"({NUM})R\b"),reported_entry=printed_entry,reported_exit=printed_exit))
            else:
                labels_values = lines[i+1:j]
                if len(labels_values)%2:
                    raise ValueError(f"Unpaired stats fields on line {i+1}")
                stats.append(dict(time=stamp,line=i+1,**dict(zip(labels_values[::2],labels_values[1::2]))))
            i=j+1
            continue
        i+=1
    seen = set()
    for event in sorted(events,key=lambda e:(e["outcome_time"],e["outcome_line"])):
        key = tuple(v for k,v in event.items() if k!="outcome_line")
        if key in seen:
            issues.append(dict(line=event["outcome_line"],reason="duplicate event"))
            continue
        seen.add(key)
        candidates = []
        for s in signals:
            if s["coin"]!=event["coin"] or s["side"]!=event["side"] or s["outcome"]!="unresolved":
                continue
            age = datetime.fromisoformat(event["outcome_time"])-datetime.fromisoformat(s["signal_time"])
            if age<timedelta(0) or (age==timedelta(0) and s["line"]>event["outcome_line"]):
                continue
            if event["outcome"] not in CLOSED and age > timedelta(hours=8,minutes=2):
                continue
            if event["outcome"]=="expired" and age < timedelta(hours=8,minutes=-1):
                continue
            if event["reported_entry"] and not printed_match(s["entry"],event["reported_entry"]):
                continue
            if event["outcome"] in ("TP","SL") and event["reported_exit"]:
                k = "target" if event["outcome"]=="TP" else "stop"
                if not printed_match(s[k],event["reported_exit"]):
                    continue
            candidates.append(s)
        if len(candidates)==1:
            candidates[0].update(event)
        else:
            issues.append(dict(line=event["outcome_line"],reason="ambiguous" if candidates else "unmatched",
                               candidates=[s["signal_id"] for s in candidates],event=event))
    return signals, stats, issues


def costed_r(entry,stop,exit_price,side,outcome,scenario,maker_bps=2,taker_bps=5,slip_bps=1):
    if scenario not in SCENARIOS or side not in ("LONG","SHORT"):
        raise ValueError("Unknown scenario or side")
    sign = 1 if side=="LONG" else -1
    take_entry = scenario=="taker_taker"
    take_exit = take_entry or (scenario=="maker_taker_stop" and outcome!="TP")
    entry_fill = entry*(1+sign*slip_bps/10000*take_entry)
    exit_fill = exit_price*(1-sign*slip_bps/10000*take_exit)
    fees = (entry_fill*(taker_bps if take_entry else maker_bps)
            +exit_fill*(taker_bps if take_exit else maker_bps))/10000
    return (sign*(exit_fill-entry_fill)-fees)/abs(entry-stop)


def add_payoffs(signals, maker, taker, slip):
    for r in signals:
        for scenario in SCENARIOS:
            if r["outcome"] in CLOSED:
                exit_field = {"TP":"target","SL":"stop","BE":"entry"}[r["outcome"]]
                r[scenario] = costed_r(float(r["entry"]),float(r["stop"]),float(r[exit_field]),r["side"],
                                       r["outcome"],scenario,maker,taker,slip)
            else:
                r[scenario] = "" if r["outcome"]=="unresolved" else 0.


def summary(rows):
    counts = Counter(r["outcome"] for r in rows)
    fills = sum(counts[k] for k in CLOSED)
    resolved = len(rows)-counts["unresolved"]
    row = dict(signals=len(rows),fills=fills,**{k:counts[k] for k in (*CLOSED,"expired","invalidated","unresolved")},
               fill_rate_lower=fills/len(rows),fill_rate_upper=(fills+counts["unresolved"])/len(rows),
               fill_rate_resolved=fills/resolved if resolved else None)
    for key in SCENARIOS:
        total = sum(r[key] for r in rows if r[key]!="")
        row.update({key+"_total":total,key+"_per_fill":total/fills if fills else None,
                    key+"_per_resolved_signal":total/resolved if resolved else None})
    return row


def cluster_ci(rows, key, seed=20261111):
    days = defaultdict(list)
    for r in rows:
        days[r["signal_time"][:10]].append(r)
    blocks = [(sum(r[key] for r in rs if r["outcome"] in CLOSED),sum(r["outcome"] in CLOSED for r in rs))
              for rs in days.values()]
    if len(blocks)<2 or not sum(n for _,n in blocks):
        return None
    rng = np.random.default_rng(seed)
    sums = np.asarray(blocks)[rng.integers(len(blocks),size=(10000,len(blocks)))].sum(axis=1)
    valid = sums[:,1]>0
    return np.quantile(sums[valid,0]/sums[valid,1],[.025,.975]).tolist()


def dot_association(rows, values, seed=20261111):
    """Descriptive correlation and a two-sided permutation check conditional on signal day."""
    dots = np.asarray([r["confidence"] for r in rows],dtype=float)
    y = np.asarray(values,dtype=float)
    if len(dots)<2 or dots.std()==0 or y.std()==0:
        return dict(n=len(rows),correlation=None,within_day_permutation_p=None)
    x = dots-dots.mean()
    centered = y-y.mean()
    observed = x @ centered
    groups = defaultdict(list)
    for i,row in enumerate(rows):
        groups[row["signal_time"][:10]].append(i)
    rng = np.random.default_rng(seed)
    # Between-day variation stays fixed under this null.
    expected = sum(x[idx].sum()*centered[idx].mean() for idx in groups.values())
    null = np.zeros(10000)
    for idx in groups.values():
        perms = rng.permuted(np.tile(centered[idx],(len(null),1)),axis=1)
        null += perms @ x[idx]
    p = (1+sum(abs(null-expected)>=abs(observed-expected)-1e-12))/(1+len(null))
    return dict(n=len(rows),correlation=float(observed/(np.linalg.norm(x)*np.linalg.norm(centered))),
                within_day_permutation_p=float(p))


def save_csv(path,rows,empty_header):
    with path.open("w",encoding="utf-8",newline="") as f:
        keys = list(dict.fromkeys(k for r in rows for k in r)) or empty_header
        writer=csv.DictWriter(f,fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def run(path, as_of, out, maker=2.,taker=5.,slip=1.):
    if not all(np.isfinite(n) and n>=0 for n in (maker,taker,slip)):
        raise ValueError("Costs must be nonnegative finite basis points")
    raw = path.read_bytes()
    signals,stats,issues = parse(raw.decode("utf-8-sig"),as_of)
    if not signals:
        raise ValueError("No complete signal cards")
    add_payoffs(signals,maker,taker,slip)
    out.mkdir(exist_ok=True,parents=True)
    save_csv(out/"signals.csv",signals,["signal_id"])
    save_csv(out/"cumulative.csv",stats,["time","line"])
    groups = []
    for dimension in ("confidence","coin","side","utc_hour"):
        by = defaultdict(list)
        for row in signals:
            bucket = row["signal_time"][11:13] if dimension=="utc_hour" else str(row[dimension])
            by[bucket].append(row)
        groups.extend(dict(dimension=dimension,bucket=bucket,**summary(rows)) for bucket,rows in sorted(by.items()))
    save_csv(out/"groups.csv",groups,["dimension","bucket"])
    filled = [r for r in signals if r["outcome"] in CLOSED]
    resolved = [r for r in signals if r["outcome"]!="unresolved"]
    gross = sum(float(r["reported_r"]) for r in filled)
    risk_pct = [abs(float(r["entry"])-float(r["stop"]))/float(r["entry"])*100 for r in signals]
    result = dict(source_sha256=sha256(raw).hexdigest(),as_of_dubai=as_of.isoformat(),
                  cost_bps=dict(maker=maker,taker=taker,taker_leg_slip=slip),
                  first_signal=min(r["signal_time"] for r in signals),last_event=max(max(r["outcome_time"],r["signal_time"]) for r in signals),
                  cumulative_posts=len(stats),gross_reported_r=gross,issues=issues,
                  median_stop_pct=statistics.median(risk_pct),summary=summary(signals),
                  confidence_vs_fill=dot_association(resolved,[r["outcome"] in CLOSED for r in resolved]),
                  confidence_vs_tp_given_fill=dot_association(filled,[r["outcome"]=="TP" for r in filled]),
                  confidence_vs_net_r_given_fill=dot_association(filled,[r["maker_taker_stop"] for r in filled]),
                  net_r_per_fill_utc_day_bootstrap_95={k:cluster_ci(signals,k) for k in SCENARIOS})
    (out/"reported.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export",type=Path)
    parser.add_argument("--as-of",required=True,type=date.fromisoformat,help="Dubai calendar date when Today/Yesterday were copied")
    parser.add_argument("--out",type=Path,default=Path("data/discord-audit"))
    parser.add_argument("--maker-bps",type=float,default=2.)
    parser.add_argument("--taker-bps",type=float,default=5.)
    parser.add_argument("--slip-bps",type=float,default=1.)
    a=parser.parse_args()
    print(json.dumps(run(a.export,a.as_of,a.out,a.maker_bps,a.taker_bps,a.slip_bps),indent=2))
