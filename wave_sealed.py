"""Evaluate the predeclared December paper cohort once all six-hour entries and 24h exits can settle."""
from collections import Counter
from datetime import datetime, timezone
import json
import time
from hashlib import sha256
from pathlib import Path

from aahil_wave import DB, connect, states
from wave_inputs import OUT

START = int(datetime(2026,12,1,tzinfo=timezone.utc).timestamp())
END = int(datetime(2027,1,1,tzinfo=timezone.utc).timestamp())
FREEZE = Path(__file__).resolve().parent/"research/aahil-wave/seal.json"


def policy_digest():
    h=sha256()
    root=Path(__file__).resolve().parent
    for name in ("aahil_wave.py","wave_signal_feed.py","wave_paper_service.py","wave_research.py",
                 "wave_inputs.py","perp_market.py","perp_orders.py","quote_replay.py","backtest.py"):
        h.update(name.encode()+b"\0"+(root/name).read_text(encoding="utf-8").encode()+b"\0")
    return h.hexdigest()


def review(now=None):
    now = int(time.time()) if now is None else now
    if now < END+30*3600+300:
        return dict(status="sealed", first_decision_utc="2026-12-01",end_exclusive_utc="2027-01-01",
                    earliest_review_utc="2027-01-02T06:05:00Z")
    coverage=set()
    freeze=json.loads(FREEZE.read_bytes())
    if policy_digest()!=freeze["policy_sha256"]:
        return dict(status="policy differs from frozen code")
    for path in (OUT/"availability").glob("*.json"):
        r=json.loads(path.read_bytes())
        if not START<=r["decision"]<END or r["model_id"]!=freeze["model_sha256"] or r.get("policy_id")!=freeze["policy_sha256"]:
            continue
        if r.get("error") or not r.get("members") or set(r["members"])!=set(r["coins"]):
            continue
        if any(v.startswith("unavailable") or v=="no_setup_or_missing_input" for v in r["coins"].values()):
            continue
        coverage.add(r["decision"])
    if not DB.exists():
        return dict(status="no prospective ledger",complete_hours=len(coverage))
    db=connect()
    try:
        cohort=[s for s in states(db).values() if START<=s["decision"]<END]
    finally:
        db.close()
    if any(s["model_id"]!=freeze["model_sha256"] or s.get("policy_id")!=freeze["policy_sha256"] for s in cohort):
        return dict(status="model changed during evaluation",complete_hours=len(coverage))
    unresolved=sum(s["status"] in ("pending","be_armed","filled") for s in cohort)
    net=sum(s.get("net_r",0.) for s in cohort)
    return dict(status="complete" if len(coverage)==(END-START)//3600 and not unresolved else "incomplete coverage",
                complete_hours=len(coverage),expected_hours=(END-START)//3600,logged=len(cohort),
                statuses=dict(Counter(s["status"] for s in cohort)),unresolved=unresolved,
                realized_net_r=net,net_r_per_signal=(net/len(cohort) if cohort and not unresolved else None))


if __name__=="__main__":
    print(json.dumps(review(),indent=2))
