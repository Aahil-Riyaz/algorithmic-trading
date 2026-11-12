"""Read-only paper setup calculator; it never submits an exchange order."""
import argparse
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP
import json
import math
from pathlib import Path
import sys

import joblib

from backtest import SLIP
from flow_data import FUTURES, request_json
from perp_market import Funding, Market, aggregate, bars_from_rest
from shock_research import (
    COINS, DATA_END, EV_HURDLE_R, MAKER_FEE, MAX_ATR_REGIME, RISK_PER_SLEEVE,
    SLEEVE_FRACTION, TAKER_FEE, _quarter_end_epoch, indicators, score_model,
    setup_at,
)


SPOT = "https://api.binance.com/api/v3"
MODEL_PATH = Path("data/shock/model.joblib")
RESULTS_PATH = Path("research/shock/results.json")
FREEZE_PATH = Path("research/shock/freeze.json")
LOOKBACK_DAYS = 10
LIVE_ORDER_POSTING_ENABLED = False
PAPER_WEEKS_REQUIRED = 8
MIN_OOS_FILLS = 220


def floor_to_step(value, step):
    value, step = Decimal(str(value)), Decimal(str(step))
    return float((value / step).to_integral_value(rounding=ROUND_DOWN) * step)


def ceil_to_step(value, step):
    value, step = Decimal(str(value)), Decimal(str(step))
    return float((value / step).to_integral_value(rounding=ROUND_UP) * step)


def precision(step):
    return max(0, -Decimal(str(step)).normalize().as_tuple().exponent)


def fmt(value, step=None):
    places = precision(step) if step is not None else 6
    return f"{value:,.{places}f}"


def live_model_gate(results_path=RESULTS_PATH):
    """Do not issue an actionable setup without positive, sufficiently large OOS and paper evidence."""
    results = json.loads(results_path.read_bytes())
    stats = results["pooled_oos"]["model"]["maker_taker_stop"]
    low = stats["bootstrap"]["net_r_per_fill_95"][0]
    enough = stats["fills"] >= MIN_OOS_FILLS
    historical_positive = stats["mean_net_r"] > 0 and low > 0 and enough
    # Paper records are intentionally a separate, explicit go-live gate.
    prospective_paper_complete = False
    return dict(actionable=bool(LIVE_ORDER_POSTING_ENABLED and historical_positive and prospective_paper_complete),
                historical_fills=stats["fills"], historical_net_r_per_fill=stats["mean_net_r"],
                historical_ci_low=low, enough_oos_fills=enough,
                prospective_paper_weeks=0, paper_weeks_required=PAPER_WEEKS_REQUIRED)


def risk_card(setup, score, equity, filters, evidence):
    """Round a conditional setup to exchange steps and size it within one sleeve."""
    order = setup["order"]
    side = setup["side"]
    symbol_filters = filters
    tick, step = symbol_filters["tick"], symbol_filters["step"]
    min_qty, min_notional = symbol_filters["min_qty"], symbol_filters["min_notional"]
    round_price = floor_to_step if side == 1 else ceil_to_step
    entry = round_price(order.entry, tick)
    stop = round_price(order.stop, tick)
    target = round_price(order.target, tick)
    stop_fill = stop * (1 - side * SLIP)
    risk_unit = -(side * (stop_fill - entry) - MAKER_FEE * entry - TAKER_FEE * stop_fill)
    target_net = side * (target - entry) - MAKER_FEE * (entry + target)
    rr = target_net / risk_unit if risk_unit > 0 else 0.0
    sleeve = equity * SLEEVE_FRACTION
    risk_budget = sleeve * RISK_PER_SLEEVE
    raw_qty = risk_budget / risk_unit if risk_unit > 0 else 0.0
    qty = floor_to_step(min(raw_qty, sleeve / (entry * (1 + MAKER_FEE))), step) if entry > 0 else 0.0
    notional = qty * entry
    actual_risk = qty * risk_unit
    blockers = []
    if score["expected_net_r"] <= EV_HURDLE_R:
        blockers.append(f"expected value does not clear +{EV_HURDLE_R:.2f}R")
    if setup["atr_regime"] > MAX_ATR_REGIME:
        blockers.append("hourly ATR regime is above the 1.5x limit")
    if evidence["actionable"] is False:
        blockers.append("historical net edge and eight-week paper gate are not cleared")
    if rr < 1.45:
        blockers.append("rounded target no longer preserves the planned reward/risk")
    if qty < min_qty:
        blockers.append("risk budget is below the exchange minimum quantity")
    if notional < min_notional:
        blockers.append("notional is below the exchange minimum")
    if actual_risk > risk_budget + 1e-8:
        blockers.append("rounded size exceeds the per-trade risk budget")
    if notional > sleeve + 1e-8:
        blockers.append("notional exceeds the coin sleeve")
    decision = "WATCH ONLY" if not blockers else "WAIT"
    return dict(
        decision=decision,
        blockers=blockers,
        symbol=setup["coin"] + "USDT",
        side="LONG" if side == 1 else "SHORT",
        signal_utc=datetime.fromtimestamp(setup["time"], timezone.utc).isoformat().replace("+00:00", "Z"),
        shock_utc=datetime.fromtimestamp(setup["event_time"], timezone.utc).isoformat().replace("+00:00", "Z"),
        current_price=float(setup["current_close"]),
        entry_limit=entry, stop=stop, target=target,
        target_to_planned_risk=rr,
        p_fill_proxy=score["p_fill"],
        p_target_before_stop_given_fill=score["p_tp_given_fill"],
        expected_net_r=score["expected_net_r"],
        fee_hurdle_r=EV_HURDLE_R,
        account_equity_usdt=float(equity), sleeve_usdt=float(sleeve),
        planned_risk_usdt=float(risk_budget), actual_stop_risk_usdt=float(actual_risk),
        risk_percent_of_account=float(100 * actual_risk / equity if equity else 0),
        quantity=qty, notional_usdt=float(notional),
        estimated_leverage=float(notional / sleeve if sleeve else 0),
        atr_regime=float(setup["atr_regime"]), features=setup["values"],
        execution_assumptions=dict(entry="maker limit, strict trade-through proxy",
                                   stop="taker, 10 bp fee plus 2 bp slippage",
                                   target="maker limit, 2 bp fee", expiry_hours=6,
                                   max_hold_hours=24, partial_fills="not modeled",
                                   queue_position="not modeled", latency="not modeled"),
        evidence_gate=evidence,
        note="The shock, taker flow and funding are market observations, not proof of liquidation cause.",
    )


def _fetch_klines(base, symbol, start_ms, end_ms):
    rows = []
    step = 1000 * 300_000
    for left in range(start_ms, end_ms, step):
        right = min(end_ms, left + step)
        batch = request_json(base + "/klines", dict(symbol=symbol, interval="5m",
                             startTime=left, endTime=right - 1, limit=1000))
        rows.extend(batch)
    expected = list(range(start_ms, end_ms, 300_000))
    if [r[0] for r in rows] != expected or any(r[6] != r[0] + 299_999 for r in rows):
        raise ValueError(f"Incomplete public five-minute data for {symbol}")
    return rows


def _market(coin, start_ms, end_ms):
    rows = _fetch_klines(FUTURES, coin + "USDT", start_ms, end_ms)
    bars = bars_from_rest(rows)
    funding_rows = request_json(FUTURES + "/fundingRate", dict(symbol=coin + "USDT",
                                 startTime=start_ms, endTime=end_ms, limit=1000))
    funding = [Funding(int(r["fundingTime"]), float(r["fundingRate"]), float(r["markPrice"]))
               for r in funding_rows]
    funding.sort(key=lambda f: f.ms)
    if not funding or len({f.ms for f in funding}) != len(funding):
        raise ValueError(f"No clean recent funding history for {coin}")
    return Market(bars, aggregate(bars), funding, [f.ms for f in funding], {}, {}, "live-public")


def _exchange_filters():
    info = request_json(FUTURES + "/exchangeInfo", {})
    parsed = {}
    for row in info["symbols"]:
        if row.get("contractType") != "PERPETUAL" or row.get("quoteAsset") != "USDT":
            continue
        filters = {item["filterType"]: item for item in row["filters"]}
        lot = filters.get("LOT_SIZE") or filters.get("MARKET_LOT_SIZE")
        notional = filters.get("MIN_NOTIONAL", filters.get("NOTIONAL", {}))
        if not lot or not filters.get("PRICE_FILTER"):
            continue
        parsed[row["baseAsset"]] = dict(
            tick=float(filters["PRICE_FILTER"]["tickSize"]),
            step=float(lot["stepSize"]), min_qty=float(lot["minQty"]),
            min_notional=float(notional.get("notional", notional.get("minNotional", 0))))
    return parsed


def _spot_close(coin, open_ms):
    rows = request_json(SPOT + "/klines", dict(symbol=coin + "USDT", interval="5m",
                        startTime=open_ms, endTime=open_ms + 299_999, limit=1))
    if not rows or rows[0][0] != open_ms or rows[0][6] != open_ms + 299_999:
        return None
    return float(rows[0][4])


def _reason(setup, pfill=None, ptp=None, ev=None):
    v = setup["values"]
    move = "down" if setup["shock_side"] < 0 else "up"
    side = "long" if setup["side"] > 0 else "short"
    flow = v["shock_taker_imbalance"]
    flow_text = "net aggressive buying" if flow > 0 else "net aggressive selling"
    return (f"{abs(setup['shock_z']):.2f}σ {move} 15m move; price then confirmed a {side} fade "
            f"by {v['confirm_atr']:.2f} ATR. Shock-bar flow showed {flow_text} "
            f"({flow:+.2f} imbalance); prior 1h/24h trend-with-shock "
            f"{v['pre_shock_1h']:+.2%}/{v['pre_shock_24h']:+.2%}; "
            f"funding benefit-to-fade {v['funding_cost_to_fade']:+.4%}; "
            f"ATR regime {setup['atr_regime']:.2f}x. These are correlations/features, not a cause diagnosis.")


def scan(equity=10000.0):
    if not MODEL_PATH.exists() or not RESULTS_PATH.exists() or not FREEZE_PATH.exists():
        raise FileNotFoundError("Run shock_research.py first to train and freeze the paper model.")
    frozen = json.loads(FREEZE_PATH.read_bytes())
    model_sha = __import__("hashlib").sha256(MODEL_PATH.read_bytes()).hexdigest()
    if model_sha != frozen["model_sha256"]:
        raise ValueError("Paper model does not match the recorded freeze")
    model = joblib.load(MODEL_PATH)
    server_ms = request_json(FUTURES + "/time", {})["serverTime"]
    last_open_ms = server_ms // 300_000 * 300_000 - 300_000
    end_ms = last_open_ms + 300_000
    start_ms = (last_open_ms // 300_000 - LOOKBACK_DAYS * 24 * 12) * 300_000
    markets = {c: _market(c, start_ms, end_ms) for c in COINS}
    filters_by_coin = _exchange_filters()
    btc_arr = indicators(markets["BTC"])
    btc_close = btc_arr["close"]
    gate = live_model_gate()
    cards = []
    for coin in COINS:
        market = markets[coin]
        a = btc_arr if coin == "BTC" else indicators(market)
        latest_i = len(market.bars) - 1
        latest_close = (market.bars[-1].time + 300) * 1000
        age_ms = server_ms - latest_close
        if age_ms > 10 * 60_000:
            cards.append(dict(symbol=coin + "USDT", decision="WAIT", reason="latest closed candle is stale"))
            continue
        selected_events = []
        last_event = -10**12
        for j in a["event_indices"]:
            z = a["z_by_index"].get(j)
            if z is not None and abs(z) >= 3.0 and j - last_event >= 36 * 12:
                selected_events.append(j)
                last_event = j
        event_index = latest_i - 3
        if not selected_events or selected_events[-1] != event_index:
            cards.append(dict(symbol=coin + "USDT", decision="WAIT",
                              reason="no fresh 3-sigma 15-minute shock at the latest confirmed bar",
                              latest_candle_utc=datetime.fromtimestamp(latest_close / 1000,
                                  timezone.utc).isoformat().replace("+00:00", "Z")))
            continue
        setup = setup_at(coin, market, a, btc_close, event_index, require_execution_horizon=False)
        if setup["status"] != "eligible":
            cards.append(dict(symbol=coin + "USDT", decision="WAIT", reason=setup["status"],
                              shock_z=a["z_by_index"].get(event_index)))
            continue
        pfill, ptp, ev = score_model(model, [dict(values=setup["values"])])
        scored = dict(p_fill=float(pfill[0]), p_tp_given_fill=float(ptp[0]), expected_net_r=float(ev[0]))
        card = risk_card(setup, scored, equity, filters_by_coin[coin], gate)
        spot = _spot_close(coin, market.bars[-1].time * 1000)
        card["spot_close"] = spot
        card["perp_spot_basis_bps"] = ((market.bars[-1].close / spot - 1) * 10000 if spot else None)
        card["reason"] = _reason(setup)
        cards.append(card)
    return dict(asof_utc=datetime.fromtimestamp(server_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z"),
                mode="READ-ONLY PAPER RESEARCH", model_sha256=model_sha,
                data_source="Binance public USDT-perpetual and spot candles/funding",
                no_api_key=True, orders_submitted=0, cards=cards)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--equity", type=float, default=10000.0,
                        help="hypothetical account size in USDT; does not connect to an account")
    args = parser.parse_args(argv)
    if not math.isfinite(args.equity) or args.equity <= 0:
        parser.error("--equity must be a positive finite number")
    try:
        print(json.dumps(scan(args.equity), indent=2))
    except Exception as error:
        print(json.dumps(dict(mode="READ-ONLY PAPER RESEARCH", decision="WAIT",
                              reason=f"public data or model unavailable: {error}", orders_submitted=0), indent=2))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
