"""Rebuild paper order state from timely live decisions and subsequent closed exchange bars."""
import json
import time

from compare import COINS
from flow_data import FUTURES, request_json, save_json
from flow_live import FORWARD
from perp_market import Funding, Market, bars_from_rest
from perp_orders import HOLD_BARS, Order
from quote_replay import QUOTE_TTL_BARS, Proposal, replay_quotes
from regime_data import rest_candles


def decisions(paths):
    # Keep the first completed decision per coin/boundary, including blocked decisions.
    earliest = {}
    for path in paths:
        snapshot = json.loads(path.read_bytes())
        t = snapshot["cutoff"]
        for coin,r in snapshot["coins"].items():
            if not t*1000 <= r["scored_ms"] < (t+300)*1000:
                continue
            key = coin,t
            if key not in earliest or r["scored_ms"] < earliest[key]["scored_ms"]:
                # Snapshots written before the six-hour model used a 15-minute expiry.
                expiry = snapshot.get("expiry", t+300+15*60)
                lifetime, remainder = divmod(expiry-t-300, 300)
                if remainder or lifetime < 1:
                    raise ValueError(f"Invalid quote expiry in {path}")
                earliest[key] = dict(r, ttl_bars=lifetime)
    return earliest


def paper_coin(coin, history, end):
    observed = [(t,r) for (c,t),r in sorted(history.items()) if c == coin and r["status"] == "qualifies"]
    closed = [(t,r) for t,r in observed if t+300 < end]
    queued = [dict(decision=t, active=t+300, expires=t+(1+r.get("ttl_bars", QUOTE_TTL_BARS))*300, status="awaiting_activation_bar",
                   entry=r["entry"], stop=r["stop"], target=r["target"]) for t,r in observed if t+300 >= end]
    if not closed:
        return queued
    first = closed[0][0]
    end = min(end, max(t + (r.get("ttl_bars", QUOTE_TTL_BARS)+HOLD_BARS)*300 for t,r in closed))
    raw = rest_candles(coin, first, end)
    bars = bars_from_rest(raw)
    funding = []
    for start in range(first, end, 7*86400):
        rows = request_json(FUTURES+"/fundingRate", dict(symbol=coin+"USDT", startTime=start*1000,
                            endTime=min(end,start+7*86400)*1000-1, limit=1000))
        funding.extend(Funding(r["fundingTime"],float(r["fundingRate"]),float(r["markPrice"])) for r in rows)
    times = [f.ms for f in funding]
    if times != sorted(set(times)):
        raise ValueError(f"{coin} funding is out of sequence")
    market = Market(bars, [], funding, times, {}, {}, "")
    signals = [Proposal((t-first)//300, Order(1,r["entry"],r["stop"],r["target"],r["risk"]),
                        r["expected_r"], r.get("ttl_bars", QUOTE_TTL_BARS)) for t,r in closed]
    return replay_quotes(market, signals, allow_open=True) + queued


def run():
    end = (int(time.time())-2)//300*300
    history = decisions((FORWARD/"quote-scores").glob("*.json"))
    orders = {coin: paper_coin(coin, history, end) for coin in COINS}
    report = dict(closed_through=end, timely_coin_decisions=len(history), orders=orders)
    path = FORWARD/"paper-orders.json"
    save_json(path, report)
    print(f"{len(history)} timely coin decisions, {sum(map(len,orders.values()))} paper signals | {path}")
    return report


if __name__ == "__main__":
    run()
