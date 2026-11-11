"""Aahil Wave prospective, paper-only signal ledger. Times are UTC epoch seconds."""
import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import time

import numpy as np

COINS = {"BTC","ETH","SOL","AVAX"}
CAPITAL = 10_000.
MAKER, TAKER, SLIP = .0002, .0005, .0002  # research assumptions
TTL = 6*3600
ACTIVE = {"pending", "filled", "be_armed"}
DB = Path("data/aahil-wave/paper.sqlite3")


def connect(path=DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=20, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE IF NOT EXISTS events(
            seq INTEGER PRIMARY KEY, id TEXT NOT NULL, kind TEXT NOT NULL,
            ts INTEGER NOT NULL, recorded INTEGER NOT NULL, payload TEXT NOT NULL,
            UNIQUE(id,kind,ts));
        CREATE TRIGGER IF NOT EXISTS immutable_update BEFORE UPDATE ON events
            BEGIN SELECT RAISE(ABORT,'immutable event'); END;
        CREATE TRIGGER IF NOT EXISTS immutable_delete BEFORE DELETE ON events
            BEGIN SELECT RAISE(ABORT,'immutable event'); END;
        CREATE TABLE IF NOT EXISTS delivery(seq INTEGER PRIMARY KEY, message TEXT NOT NULL);
    """)
    return db


@contextmanager
def transaction(db):
    if db.in_transaction:
        yield
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def append(db, key, kind, ts, **fields):
    db.execute("INSERT INTO events(id,kind,ts,recorded,payload) VALUES(?,?,?,?,?)",
               (key,kind,ts,int(time.time()),json.dumps(fields,allow_nan=False)))


def states(db):
    orders = {}
    for r in db.execute("SELECT * FROM events WHERE kind NOT IN ('account','skip') ORDER BY seq"):
        p = json.loads(r["payload"])
        if r["kind"] == "signal":
            orders[r["id"]] = dict(p, status="pending", funding=0., entry_time=None, last=p["active"]-60)
        else:
            s = orders[r["id"]]
            if r["kind"] == "bar":
                s.update(last=r["ts"], mark=p["mark"], funding=s["funding"]+p["funding"])
            elif r["kind"] == "replace_requested":
                s.update(p)
            else:
                s.update(p,status=r["kind"])
    return orders


def account(db, orders, now):
    equity = CAPITAL
    for s in orders.values():
        equity += s.get("pnl",0.)
        if s["status"] in {"filled","be_armed"}:
            equity += s["qty"]*(s["side"]*(s["mark"]-s["entry"])-MAKER*s["entry"]-TAKER*s["mark"]) + s["funding"]
    rows = list(db.execute("SELECT ts,payload FROM events WHERE kind='account' ORDER BY seq"))
    day = now//86400
    prior = [json.loads(r["payload"])["equity"] for r in rows if r["ts"]//86400 < day]
    high = max([CAPITAL,equity]+[json.loads(r["payload"])["equity"] for r in rows])
    day_start = prior[-1] if prior else CAPITAL
    halted = any(json.loads(r["payload"])["kill"] for r in rows) or equity <= .95*high
    daily = equity <= .985*day_start or any(r["ts"]//86400==day and json.loads(r["payload"])["daily"] for r in rows)
    return dict(equity=equity,kill=halted,daily=daily)


def propose(db, candidate, now=None):
    """Record a model proposal before the first executable minute. Reject late or stale inputs."""
    now = int(time.time()) if now is None else now
    c = dict(candidate)
    key = f"{c['coin']}-{c['decision']}"
    with transaction(db):
        if db.execute("SELECT 1 FROM events WHERE id=?",(key,)).fetchone():
            return key
        orders = states(db)
        a = account(db,orders,now)
        side, entry, stop, target = (c[k] for k in ("side","entry","stop","target"))
        distance = side*(entry-stop)
        numeric = ("entry","stop","target","bid","ask","atr","wave1","p_fill","p_tp_given_fill","expected_net_r")
        if any(not math.isfinite(c[k]) for k in numeric):
            raise ValueError("Nonfinite model input")
        valid = (c["coin"] in COINS and side in {-1,1} and min(entry, stop, target, c["atr"],c["wave1"])>0
                 and 0<c["bid"]<=c["ask"] and 0<=c["p_fill"]<=1 and 0<=c["p_tp_given_fill"]<=1
                 and c["decision"]%60==0 and 0<=now-c["decision"]<60 and 0<=now-c["quote_time"]<=10 and c["model_id"]
                 and side*(target-entry)>0)
        mark = c["bid"] if side==1 else c["ask"]
        maker = entry < c["ask"] if side==1 else entry > c["bid"]
        reason = None
        if not valid or not maker:
            reason = "invalid_or_stale"
        elif (distance < max(c["atr"],4*(MAKER+TAKER+SLIP)*entry)
              or side*(mark-c["wave1"]) < .5*c["atr"] or side*(entry-c["wave1"])<=0):
            reason = "geometry_or_invalidation"
        elif abs(entry-mark)>2*c["atr"] or side*(mark-target)>=0 or c["expected_net_r"]<=.05:
            reason = "distance_or_expectancy"
        active = {k:s for k,s in orders.items() if s["status"] in ACTIVE}
        previous = [(k,s) for k,s in active.items() if s["coin"]==c["coin"]]
        if any(s["status"]!="pending" for _,s in previous):
            reason = "coin_in_position"
        if any(now-s["last"]>180 and now>=s["active"]+120 for s in active.values()):
            reason = "paper_feed_behind"
        if a["daily"] or a["kill"]:
            reason = "risk_halt"
        # Reserve pending and filled notional together. Treat all four coins as one correlated bucket.
        reserved = sum(s["qty"]*max(s["entry"],s.get("mark",s["entry"])) for s in active.values()
                       if s["coin"]!=c["coin"])
        slipped_stop = stop*(1-side*SLIP)
        unit_risk = side*(entry-slipped_stop) + MAKER*entry + TAKER*slipped_stop
        budget = .0025*a["equity"]
        if "kelly_lower_fraction" in c:
            lower = float(c["kelly_lower_fraction"])
            if not math.isfinite(lower):
                raise ValueError("Invalid Kelly lower bound")
            measured=scoreboard(db)
            interval=measured["signal_day_bootstrap_95"]
            if measured["closed"]<220 or not interval or interval[0]<=0:
                budget=0.
            else:
                budget = min(budget,.25*max(0.,lower)*a["equity"])
        qty = min(budget/max(unit_risk,1e-12), .25*a["equity"]/max(entry,1e-12),
                  (.75*a["equity"]-reserved)/max(entry,1e-12))
        if qty<=0:
            reason = "exposure_cap"
        if reason:
            append(db,key,"skip",now,coin=c["coin"],reason=reason,candidate=c)
            return key
        active_time = c["decision"]+300
        for prior,old in previous:
            if active_time < old.get("replace_at",math.inf):
                append(db,prior,"replace_requested",now,replace_at=active_time,by=key)
        append(db,key,"signal",now,**{k:c[k] for k in ("coin","side","entry","stop","target","atr","wave1",
               "p_fill","p_tp_given_fill","expected_net_r","model_id","decision","bid","ask","quote_time")},
               features=c.get("features",{}),policy_id=c.get("policy_id"),active=active_time,expires=active_time+TTL,
               qty=qty,unit_risk=unit_risk,mark=mark)
    return key


def advance(db, key, bar, settlements=()):
    """Consume one closed one-minute candle. Funding records are (event_second, rate, mark)."""
    t,op,hi,lo,cl = bar
    if (not all(map(math.isfinite,bar)) or t%60 or not 0<lo<=min(op,cl)<=max(op,cl)<=hi
            or t+60>time.time()):
        raise ValueError("Expected closed UTC minute")
    with transaction(db):
        s = states(db)[key]
        if s["status"] not in ACTIVE or t<=s["last"]:
            return
        if t != s["last"]+60:
            raise ValueError("Missing candle; resume from the ledger cursor")
        side,entry = s["side"],s["entry"]
        adverse,best = (lo,hi) if side==1 else (hi,lo)
        funded = 0.
        fresh = s["status"]=="pending"
        if fresh:
            if t>=s["expires"]:
                append(db,key,"expired",t)
                return
            if t>=s.get("replace_at",math.inf):
                append(db,key,"replaced",t)
                return
            if t==s["active"] and any(k!=key and old["coin"]==s["coin"] and old["entry_time"] is not None
                    and old["entry_time"]<t<old.get("ended",math.inf) for k,old in states(db).items()):
                append(db,key,"position_busy",t)
                return
            if t==s["active"] and side*(op-s["wave1"])<=0:
                append(db,key,"invalidated",t)
                return
            if t==s["active"] and side*(op-entry)<=0:
                append(db,key,"post_only_reject",t)
                return
            if side*(adverse-entry)<0:
                append(db,key,"filled",t,entry_time=t)
                s.update(status="filled",entry_time=t)
            elif side*(adverse-s["wave1"])<=0:
                append(db,key,"invalidated",t)
                return
            elif t+60==s["expires"]:
                append(db,key,"expired",s["expires"])
                return
        if s["status"] in {"filled","be_armed"}:
            stop = entry if s["status"]=="be_armed" else s["stop"]
            outcome = None
            if side*(adverse-stop)<=0:
                outcome = "be" if s["status"]=="be_armed" else "sl"
                px = (min(op,stop) if side==1 else max(op,stop))*(1-side*SLIP)
            elif not fresh and side*(best-s["target"])>0:
                outcome,px = "tp",s["target"]
            elif t+60>=s["entry_time"]+86400:
                outcome,px = "timeout",cl*(1-side*SLIP)
            for ts,rate,mark in settlements:
                if t<=ts<t+60:
                    payment = -side*rate*mark*s["qty"]
                    funded += min(0.,payment) if fresh or outcome else payment
            if outcome:
                fee = MAKER if outcome=="tp" else TAKER
                pnl = s["qty"]*(side*(px-entry)-MAKER*entry-fee*px)+s["funding"]+funded
                append(db,key,outcome,t+60,ended=t+60,exit_price=px,pnl=pnl,net_r=pnl/(s["qty"]*s["unit_risk"]),
                       funding_paid=s["funding"]+funded)
                return
            if not fresh and s["status"]=="filled" and side*(cl-entry)>=abs(entry-s["stop"]):
                append(db,key,"be_armed",t+60)
        append(db,key,"bar",t,mark=cl,funding=funded)


def checkpoint(db, now):
    with transaction(db):
        orders = states(db)
        a = account(db,orders,now)
        if not db.execute("SELECT 1 FROM events WHERE id='account' AND ts=?",(now,)).fetchone():
            append(db,"account","account",now,**a)
        if a["daily"] or a["kill"]:
            for k,s in orders.items():
                if s["status"]=="pending":
                    append(db,k,"risk_cancelled",now)
        return a


def scoreboard(db):
    orders = states(db)
    counts = Counter(s["status"] for s in orders.values())
    fills = sum(s["entry_time"] is not None for s in orders.values())
    returns = [s["net_r"] for s in orders.values() if "net_r" in s]
    total = len(orders)
    # Resample whole UTC signal days, including dates with zero closed trades.
    by_day = defaultdict(list)
    for s in orders.values():
        if "net_r" in s:
            by_day[s["decision"]//86400].append(s["net_r"])
    ci = None
    if len(by_day)>=7:
        days = range(min(by_day),max(by_day)+1)
        sums = np.array([sum(by_day[d]) for d in days])
        sizes = np.array([len(by_day[d]) for d in days])
        rng = np.random.default_rng(17)
        boot = []
        for _ in range(2000):
            ix = rng.integers(len(days),size=len(days))
            if sizes[ix].sum():
                boot.append(sums[ix].sum()/sizes[ix].sum())
        ci = list(np.quantile(boot,[.025,.975]))
    return dict(signals=total, skipped=db.execute("SELECT count(*) FROM events WHERE kind='skip'").fetchone()[0],
                statuses=dict(counts),filled=fills,fill_rate=fills/total if total else None,
                invalidation_rate=counts["invalidated"]/total if total else None,
                closed=len(returns),net_r=sum(returns),net_r_per_closed=np.mean(returns) if returns else None,
                signal_day_bootstrap_95=ci)


def price(n):
    return np.format_float_positional(float(n),precision=10,trim="-")


def render(event):
    p = json.loads(event["payload"])
    clock = datetime.fromtimestamp(event["ts"],timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    label = f"Aahil Wave paper | {event['id']} | {clock}"
    if event["kind"]=="signal":
        return (f"{label}\n{'LONG' if p['side']==1 else 'SHORT'} {p['coin']}  Entry {price(p['entry'])}  "
                f"Stop {price(p['stop'])}  TP {price(p['target'])}\nHistorical model estimates before paper overlays: "
                f"P(fill) {p['p_fill']:.1%}  P(TP before SL | fill) {p['p_tp_given_fill']:.1%}  "
                f"Expected net R/signal {p['expected_net_r']:+.3f}")
    return f"{label}\n{event['kind'].upper()}" + (f"  {p['net_r']:+.3f}R after costs" if "net_r" in p else "")


if __name__=="__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate",type=Path,help="fresh prospective model output JSON")
    args=parser.parse_args()
    db=connect()
    if args.candidate:
        print(propose(db,json.loads(args.candidate.read_bytes())))
    print(json.dumps(scoreboard(db),indent=2))
