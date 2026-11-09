"""Check the published test ledger and reprice identical fills under alternative fees."""
import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from math import isclose
from pathlib import Path


HERE = Path(__file__).resolve().parent


def check(condition, message):
    if not condition:
        raise ValueError(message)


def audit():
    freeze = json.loads((HERE / "freeze.json").read_bytes())
    report = json.loads((HERE / "holdout.json").read_bytes())
    digest = hashlib.sha256(json.dumps(freeze, separators=(",", ":"), sort_keys=True).encode()).hexdigest()
    check(report["freeze_id"] == digest, "Wrong model freeze")
    result = report["models"]["options_flow"]
    start, end = [datetime.fromisoformat(report[k]).replace(tzinfo=timezone.utc).timestamp()
                  for k in ("test_start", "test_end_exclusive")]
    orders = fills = wins = 0
    gross = fees = carry = entry_turnover = exit_mixed_fees = 0.0
    prior_end = defaultdict(int)
    net = Counter()
    with (HERE / "orders.csv").open(newline="", encoding="utf-8") as file:
        for r in csv.DictReader(file):
            orders += 1
            coin = r["coin"]
            sign = {"long": 1, "short": -1}[r["side"]]
            active, finish = int(r["active"]), int(r["end"])
            check(start <= int(r["feature_cutoff"]) == active - 300 <= finish < end, "Order clock mismatch")
            check(prior_end[coin] < active, "Two orders active on the same coin")
            prior_end[coin] = finish
            price, stop, target, qty = map(float, (r["entry"], r["stop"], r["target"], r["qty"]))
            check(sign * (price - stop) > 0 and sign * (target - price) > 0, "Invalid bracket")
            check(qty * price <= 10_000 + net[coin] + 1e-6, "Order exceeds available notional")
            slipped_stop = stop * (1 - sign * 0.0002)
            planned_risk = qty * (sign * (price - slipped_stop) + 0.001 * (price + slipped_stop))
            check(planned_risk <= 0.005 * (10_000 + net[coin]) + 1e-6, "Risk budget exceeded")
            if not r["fill"]:
                check(r["reason"] == "expired" and float(r["net_usdt"]) == 0
                      and finish == active + 23 * 300, "Invalid expiry")
                continue
            fill = int(r["fill"])
            check(active <= fill < active + 7200 and fill <= finish < fill + 86400, "Invalid fill clock")
            exit_px, funding, pnl = map(float, (r["exit_px"], r["funding_usdt"], r["net_usdt"]))
            price_pnl = qty * sign * (exit_px - price)
            fee = qty * 0.001 * (price + exit_px)
            check(isclose(price_pnl - fee + funding, pnl, abs_tol=1e-7), "Trade P&L mismatch")
            fills += 1
            wins += pnl > 0
            gross += price_pnl
            fees += fee
            carry += funding
            net[coin] += pnl
            entry_turnover += qty * price
            exit_mixed_fees += qty * exit_px * (0.0002 if r["reason"] == "target" else 0.0005)
    check((orders, fills, wins) == (result["orders"], result["fills"], result["wins"]), "Count mismatch")
    check(isclose(gross, result["gross_price_pnl_usdt"], abs_tol=1e-6), "Gross P&L mismatch")
    check(isclose(fees, result["trading_fees_usdt"], abs_tol=1e-6), "Fee mismatch")
    for coin, pnl in net.items():
        check(isclose(pnl, result["by_coin"][coin]["net_usdt"], abs_tol=1e-6), f"{coin} net P&L mismatch")
    check(isclose(sum(net.values()), result["net_usdt"], abs_tol=1e-6), "Portfolio P&L mismatch")
    return dict(orders=orders, fills=fills, wins=wins, win_pct=100 * wins / fills,
                gross=gross, fees=fees, funding=carry, net=sum(net.values()),
                net_if_entries_maker=gross + carry - exit_mixed_fees - 0.0002 * entry_turnover,
                net_if_entries_taker=gross + carry - exit_mixed_fees - 0.0005 * entry_turnover)


if __name__ == "__main__":
    print(json.dumps({k: round(v, 4) for k, v in audit().items()}, indent=2))
