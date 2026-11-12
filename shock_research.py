"""Causal study of confirmed, unusually large moves on Binance USDT perps."""
import argparse
import csv
from bisect import bisect_left
from dataclasses import asdict
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss
from threadpoolctl import threadpool_limits
from xgboost import XGBClassifier

from backtest import FEE as BASE_TAKER_FEE, SLIP
from flow_data import ROOT
from perp_market import load_market
from perp_orders import HOLD_BARS, Order, resolve


COINS = ("BTC", "ETH", "SOL", "AVAX")
FIRST = date(2023, 12, 1)
DATA_END = date(2026, 10, 1)
MAKER_FEE = 0.0002
TAKER_FEE = BASE_TAKER_FEE
ENTRY_BARS = 72
MAX_LIFETIME_BARS = ENTRY_BARS + HOLD_BARS
MAX_LIFETIME_SECONDS = MAX_LIFETIME_BARS * 300
EMBARGO_SECONDS = 24 * 3600
EVENT_GAP_BARS = 36 * 12
SHOCK_Z = 3.0
SHOCK_WINDOW = 3
SHOCK_SIGMA_PERIODS = 7 * 24 * 4
CONFIRM_BARS = 3
MIN_CONFIRM_ATR = 0.25
MAX_ATR_REGIME = 1.5
EV_HURDLE_R = 0.05
RISK_PER_SLEEVE = 0.0025
SLEEVE_FRACTION = 0.25
NOTIONAL_CAP = 1.0
DAILY_LOSS_LIMIT = 0.01
MAX_DRAWDOWN = 0.05
BOOTSTRAP_SEED = 421
BOOTSTRAP_REPS = 2000
BLOCK_DAYS = 7

FEATURES = (
    "side", "shock_z", "pre_shock_1h", "pre_shock_24h", "confirm_atr",
    "atr_regime", "shock_volume_expansion", "shock_taker_imbalance",
    "confirm_taker_imbalance", "btc_ret_1h", "funding_cost_to_fade",
) + tuple("is_" + c for c in COINS)

FOLDS = (
    ("2025-Q1", date(2025, 1, 1), date(2025, 4, 1)),
    ("2025-Q2", date(2025, 4, 1), date(2025, 7, 1)),
    ("2025-Q3", date(2025, 7, 1), date(2025, 10, 1)),
    ("2025-Q4", date(2025, 10, 1), date(2026, 1, 1)),
    ("2026-Q1", date(2026, 1, 1), date(2026, 4, 1)),
    ("2026-Q2", date(2026, 4, 1), date(2026, 7, 1)),
    ("2026-Q3", date(2026, 7, 1), date(2026, 10, 1)),
)


def utc_iso(seconds):
    return datetime.fromtimestamp(int(seconds), timezone.utc).isoformat().replace("+00:00", "Z")


def _rolling_mean(values, window):
    values = np.asarray(values, dtype=float)
    out = np.full(len(values), np.nan)
    if window <= 0 or len(values) < window:
        return out
    sums = np.r_[0.0, np.cumsum(values)]
    out[window - 1:] = (sums[window:] - sums[:-window]) / window
    return out


def indicators(market):
    """Causal return, five-minute ATR, and the non-overlapping 15m shock z-score."""
    bars = market.bars
    n = len(bars)
    close = np.asarray([b.close for b in bars], dtype=float)
    prev = np.r_[close[0], close[:-1]]
    high = np.asarray([b.high for b in bars], dtype=float)
    low = np.asarray([b.low for b in bars], dtype=float)
    tr = np.maximum(high, prev) - np.minimum(low, prev)
    atr5 = _rolling_mean(tr, 14)

    # Bar timestamps are candle-open UTC seconds. Modulo 900 == 600 is the
    # last five-minute candle in each non-overlapping 15-minute interval.
    events = [i for i, b in enumerate(bars) if b.time % 900 == 600 and i >= 3]
    ret15 = np.asarray([math.log(close[i] / close[i - 3]) for i in events])
    z_by_index = {}
    if len(events) > SHOCK_SIGMA_PERIODS:
        sums = np.r_[0.0, np.cumsum(ret15)]
        sums2 = np.r_[0.0, np.cumsum(ret15 * ret15)]
        for k in range(SHOCK_SIGMA_PERIODS, len(events)):
            left, right = k - SHOCK_SIGMA_PERIODS, k
            mean = (sums[right] - sums[left]) / SHOCK_SIGMA_PERIODS
            variance = (sums2[right] - sums2[left]) / SHOCK_SIGMA_PERIODS - mean * mean
            sigma = math.sqrt(max(0.0, variance))
            if sigma > 0:
                z_by_index[events[k]] = ret15[k] / sigma

    # Completed-hour true ranges. For a candidate inside an hour, the current
    # numerator is rebuilt from that hour's bars seen so far; future candles
    # never enter the regime gate.
    n_hours = n // 12
    hour_tr = np.empty(n_hours, dtype=float)
    for h in range(n_hours):
        start, stop = h * 12, (h + 1) * 12
        prior_close = close[start - 1] if start else close[start]
        hour_tr[h] = max(high[start:stop].max() - low[start:stop].min(),
                         abs(high[start:stop].max() - prior_close),
                         abs(low[start:stop].min() - prior_close))
    hour_atr14 = _rolling_mean(hour_tr, 14)
    return dict(close=close, high=high, low=low, tr=tr, atr5=atr5,
                z_by_index=z_by_index, event_indices=events,
                hour_tr=hour_tr, hour_atr14=hour_atr14)


def atr_regime(market, arrays, i):
    """Current partial-hour ATR(14) divided by the prior 168 completed ATRs."""
    h = i // 12
    if h < 14 + 168:
        return None
    previous_atrs = arrays["hour_atr14"][h - 168:h]
    if len(previous_atrs) != 168 or not np.isfinite(previous_atrs).all():
        return None
    start = h * 12
    seen = market.bars[start:i + 1]
    prior_close = market.bars[start - 1].close if start else seen[0].open
    hh = max(b.high for b in seen)
    ll = min(b.low for b in seen)
    partial_tr = max(hh - ll, abs(hh - prior_close), abs(ll - prior_close))
    recent_completed = arrays["hour_tr"][h - 13:h]
    if len(recent_completed) != 13:
        return None
    current_atr = float((recent_completed.sum() + partial_tr) / 14)
    baseline = float(previous_atrs.mean())
    return current_atr / baseline if baseline > 0 else None


def _buy_share(bars):
    quote = sum(b.quote for b in bars)
    buy = sum(b.buy_quote for b in bars)
    return (2 * buy / quote - 1) if quote > 0 else 0.0


def _volume_expansion(bars, j):
    # Compare the event's 15m turnover with the median of the prior 24h's
    # non-overlapping 15m turnover observations.
    current = sum(b.quote for b in bars[j - 2:j + 1])
    past = []
    for k in range(j - 3, j - 3 * 96, -3):
        group = bars[k - 2:k + 1]
        if len(group) == 3:
            past.append(sum(b.quote for b in group))
    if not past or float(np.median(past)) <= 0:
        return 0.0
    return current / float(np.median(past))


def _known_funding(market, signal_close_ms):
    k = bisect_left(market.funding_times, signal_close_ms) - 1
    if k < 0:
        return None
    payment = market.funding[k]
    if signal_close_ms - payment.ms > 9 * 3600_000:
        return None
    return float(payment.rate)


def order_geometry(side, close, atr, swing_low, swing_high):
    """Cost-aware 1.5R target, wider swing/ATR stop, and a half-ATR limit."""
    if side not in (-1, 1) or min(close, atr) <= 0:
        return None
    entry = close - side * 0.5 * atr
    swing = swing_low if side == 1 else swing_high
    distance = max(2 * atr, 0.015 * entry, side * (entry - swing) + 0.25 * atr)
    stop = entry - side * distance
    stop_fill = stop * (1 - side * SLIP)
    risk = -(side * (stop_fill - entry) - MAKER_FEE * entry - TAKER_FEE * stop_fill)
    if risk <= 0 or min(entry, stop, stop_fill) <= 0:
        return None
    target = (1.5 * risk + (side + MAKER_FEE) * entry) / (side - MAKER_FEE)
    if target <= 0 or side * (target - entry) <= 0:
        return None
    return Order(side, float(entry), float(stop), float(target), float(risk))


def net_pnl(order, outcome, scenario):
    if outcome.fill is None:
        return 0.0
    if scenario == "maker_maker_best_case":
        fee_in, fee_out = MAKER_FEE, MAKER_FEE
    elif scenario == "maker_taker_stop":
        fee_in = MAKER_FEE
        fee_out = MAKER_FEE if outcome.reason == "target" else TAKER_FEE
    elif scenario == "taker_taker":
        fee_in = fee_out = TAKER_FEE
    else:
        raise ValueError(f"Unknown fee scenario: {scenario}")
    return (order.side * (outcome.price - order.entry)
            - fee_in * order.entry - fee_out * outcome.price + outcome.funding)


SCENARIOS = ("maker_maker_best_case", "maker_taker_stop", "taker_taker")


def setup_at(coin, market, arrays, btc_close, event_index, require_execution_horizon=True):
    """Build point-in-time features and order geometry for one 15m shock."""
    bars, close = market.bars, arrays["close"]
    j = int(event_index)
    z = arrays["z_by_index"].get(j)
    if z is None or abs(z) < SHOCK_Z:
        return dict(status="below_shock_threshold")
    shock_side = 1 if z > 0 else -1
    side = -shock_side
    signal_i = j + CONFIRM_BARS
    if signal_i >= len(bars):
        return dict(status="incomplete_confirmation")
    if require_execution_horizon and signal_i + MAX_LIFETIME_BARS > len(bars):
        return dict(status="incomplete_horizon")
    atr_event = float(arrays["atr5"][j])
    atr_signal = float(arrays["atr5"][signal_i])
    if not np.isfinite(atr_event) or not np.isfinite(atr_signal) or min(atr_event, atr_signal) <= 0:
        return dict(status="missing_atr")
    confirm_atr = side * (close[signal_i] - close[j]) / atr_event
    if confirm_atr < MIN_CONFIRM_ATR:
        return dict(status="no_confirmation", confirm_atr=float(confirm_atr))
    regime = atr_regime(market, arrays, signal_i)
    if regime is None:
        return dict(status="missing_regime", confirm_atr=float(confirm_atr))
    if regime > MAX_ATR_REGIME:
        return dict(status="high_volatility", confirm_atr=float(confirm_atr),
                    atr_regime=float(regime))
    if signal_i < 24 * 12 + 15:
        return dict(status="missing_history", confirm_atr=float(confirm_atr),
                    atr_regime=float(regime))
    funding = _known_funding(market, (bars[signal_i].time + 300) * 1000)
    if funding is None:
        return dict(status="missing_funding", confirm_atr=float(confirm_atr),
                    atr_regime=float(regime))
    shock_bars = bars[j - 2:j + 1]
    confirm_bars = bars[signal_i - 2:signal_i + 1]
    previous_1h = close[j - 3] / close[j - 15] - 1
    previous_24h = close[j - 3] / close[j - 3 - 288] - 1
    values = dict(
        side=side, shock_z=abs(float(z)),
        pre_shock_1h=float(shock_side * previous_1h),
        pre_shock_24h=float(shock_side * previous_24h),
        confirm_atr=float(confirm_atr), atr_regime=float(regime),
        shock_volume_expansion=float(_volume_expansion(bars, j)),
        shock_taker_imbalance=float(_buy_share(shock_bars)),
        confirm_taker_imbalance=float(_buy_share(confirm_bars)),
        btc_ret_1h=float(btc_close[signal_i] / btc_close[signal_i - 12] - 1),
        funding_cost_to_fade=float(-side * funding),
    )
    values.update({"is_" + c: int(c == coin) for c in COINS})
    current_close = float(close[signal_i])
    swing_low = float(min(b.low for b in bars[signal_i - 11:signal_i + 1]))
    swing_high = float(max(b.high for b in bars[signal_i - 11:signal_i + 1]))
    order = order_geometry(side, current_close, atr_signal, swing_low, swing_high)
    continuation_order = order_geometry(shock_side, current_close, atr_signal, swing_low, swing_high)
    if order is None or continuation_order is None:
        return dict(status="invalid_geometry", confirm_atr=float(confirm_atr),
                    atr_regime=float(regime))
    return dict(status="eligible", coin=coin, event_index=j, signal_index=signal_i,
                event_time=bars[j].time + 300, time=bars[signal_i].time + 300,
                shock_side=shock_side, side=side, shock_z=abs(float(z)),
                confirm_atr=float(confirm_atr), atr_regime=float(regime),
                values=values, order=order, continuation_order=continuation_order,
                current_close=current_close, atr_signal=atr_signal)


def event_rows(markets):
    """Return raw event audit rows and executable, fully labelled candidates."""
    arrays = {c: indicators(markets[c]) for c in COINS}
    btc_close = arrays["BTC"]["close"]
    raw, candidates = [], []
    for coin in COINS:
        market, a = markets[coin], arrays[coin]
        bars, close = market.bars, a["close"]
        last_selected = -10**12
        for j in a["event_indices"]:
            z = a["z_by_index"].get(j)
            if z is None or abs(z) < SHOCK_Z:
                continue
            shock_side = 1 if z > 0 else -1
            fade_side = -shock_side
            signal_i = j + CONFIRM_BARS
            signal_time = (bars[signal_i].time + 300 if signal_i < len(bars)
                           else bars[j].time + 300 + CONFIRM_BARS * 300)
            row = dict(coin=coin, event_index=j, signal_index=signal_i,
                       event_time=bars[j].time + 300, time=signal_time,
                       shock_side=shock_side, side=fade_side, shock_z=float(abs(z)),
                       status="unprocessed")
            if j - last_selected < EVENT_GAP_BARS:
                row["status"] = "cooldown"
                raw.append(row)
                continue
            last_selected = j
            if signal_i >= len(bars):
                row["status"] = "incomplete_confirmation"
                raw.append(row)
                continue
            if signal_i + MAX_LIFETIME_BARS > len(bars):
                row["status"] = "incomplete_horizon"
                raw.append(row)
                continue
            setup = setup_at(coin, market, a, btc_close, j)
            row["confirm_atr"] = setup.get("confirm_atr")
            row["atr_regime"] = setup.get("atr_regime")
            if setup["status"] != "eligible":
                row["status"] = setup["status"]
                raw.append(row)
                continue
            values = setup["values"]
            fade_order = setup["order"]
            continuation_order = setup["continuation_order"]
            start = signal_i + 1
            fade_outcome = resolve(market, fade_order, start, entry_bars=ENTRY_BARS)
            continuation_outcome = resolve(market, continuation_order, start, entry_bars=ENTRY_BARS)
            end_time = bars[fade_outcome.end].time + 300
            candidate = dict(
                coin=coin, time=row["time"], event_time=row["event_time"],
                event_index=j, signal_index=signal_i, side=fade_side,
                shock_side=shock_side, shock_z=float(abs(z)),
                status="eligible", values=values, order=fade_order,
                outcome=fade_outcome, end=end_time,
                fill=fade_outcome.fill is not None,
                tp=fade_outcome.reason == "target",
                reason=fade_outcome.reason,
                r=net_pnl(fade_order, fade_outcome, "maker_taker_stop") / fade_order.risk,
                pnl_scenarios={s: net_pnl(fade_order, fade_outcome, s) for s in SCENARIOS},
                continuation_order=continuation_order,
                continuation_outcome=continuation_outcome,
                continuation_fill=continuation_outcome.fill is not None,
                continuation_reason=continuation_outcome.reason,
                continuation_end=bars[continuation_outcome.end].time + 300,
                continuation_r=(net_pnl(continuation_order, continuation_outcome,
                                        "maker_taker_stop") / continuation_order.risk
                                if continuation_outcome.fill is not None else 0.0),
                continuation_pnl_scenarios={s: net_pnl(continuation_order, continuation_outcome, s)
                                            for s in SCENARIOS},
            )
            raw.append({**row, "status": "eligible", "atr_regime": float(setup["atr_regime"]),
                        "confirm_atr": float(setup["confirm_atr"]), "reason": fade_outcome.reason,
                        "fill": fade_outcome.fill is not None, "net_r": candidate["r"]})
            candidates.append(candidate)
    return sorted(raw, key=lambda r: (r["time"], r["coin"])), sorted(candidates, key=lambda r: (r["time"], r["coin"]))


def _matrix(rows):
    return np.asarray([[r["values"][f] for f in FEATURES] for r in rows], dtype=float)


def _classifier(x, y, xcal, ycal):
    if len(x) < 30 or len(xcal) < 20 or len(set(y)) != 2 or len(set(ycal)) != 2:
        raise ValueError("Insufficient chronological examples or classes for calibrated model")
    model = XGBClassifier(
        n_estimators=60, max_depth=2, learning_rate=0.05, min_child_weight=10,
        subsample=0.8, colsample_bytree=0.8, reg_lambda=5, n_jobs=2,
        random_state=421, eval_metric="logloss", verbosity=0,
    )
    model.fit(x, y)
    margins = model.predict(xcal, output_margin=True).reshape(-1, 1)
    calibration = LogisticRegression(C=1.0).fit(margins, ycal)
    return model, calibration


def fit_model(train, calibration):
    """Fit only on prior rows, calibrate on the later purged slice."""
    fill_model = _classifier(_matrix(train), [int(r["fill"]) for r in train],
                             _matrix(calibration), [int(r["fill"]) for r in calibration])
    tr_filled = [r for r in train if r["fill"]]
    ca_filled = [r for r in calibration if r["fill"]]
    direction_model = _classifier(_matrix(tr_filled), [int(r["tp"]) for r in tr_filled],
                                  _matrix(ca_filled), [int(r["tp"]) for r in ca_filled])
    winners = [r["r"] for r in ca_filled if r["tp"]]
    others = [r["r"] for r in ca_filled if not r["tp"]]
    if not winners or not others:
        raise ValueError("Calibration needs both target and non-target filled examples")
    return dict(features=FEATURES, fill=fill_model, direction=direction_model,
                mean_target_r=float(np.mean(winners)), mean_other_r=float(np.mean(others)),
                train_rows=len(train), calibration_rows=len(calibration),
                calibration_fills=len(ca_filled))


def score_model(model, rows):
    x = _matrix(rows)
    def calibrated(pair):
        tree, cal = pair
        margin = tree.predict(x, output_margin=True).reshape(-1, 1)
        return cal.predict_proba(margin)[:, 1]
    pfill = calibrated(model["fill"])
    ptp = calibrated(model["direction"])
    ev = pfill * (ptp * model["mean_target_r"] + (1 - ptp) * model["mean_other_r"])
    return pfill, ptp, ev


def chronological_split(rows, first):
    """Purge full 30h label horizons and 24h embargo at test and calibration edges."""
    first_s = (_quarter_end_epoch(first) if isinstance(first, date) and not isinstance(first, datetime)
               else int(first.replace(tzinfo=timezone.utc).timestamp()))
    available = [r for r in rows if r["time"] + MAX_LIFETIME_SECONDS + EMBARGO_SECONDS < first_s]
    if len(available) < 100:
        raise ValueError(f"Only {len(available)} eligible purged training rows before {first}")
    cut = max(1, int(0.8 * len(available)))
    cal_start = available[cut]["time"]
    train = [r for r in available if r["time"] + MAX_LIFETIME_SECONDS + EMBARGO_SECONDS < cal_start]
    calibration = [r for r in available if r["time"] >= cal_start]
    if len(train) < 50 or len(calibration) < 30:
        raise ValueError("Purged train/calibration slice is too small")
    return train, calibration


def _quarter_end_epoch(day):
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def _eligible_in_window(rows, start, end):
    left, right = _quarter_end_epoch(start), _quarter_end_epoch(end)
    return [r for r in rows if left <= r["time"] and r["time"] + MAX_LIFETIME_SECONDS <= right]


def _risk_sized_trades(rows, selection, initial=10000.0):
    """Apply equal sleeves, one-times notional, daily halt and drawdown kill."""
    sleeve_cash = {c: initial * SLEEVE_FRACTION for c in COINS}
    cash = initial
    peak = initial
    day_start = initial
    current_day = None
    daily_realized = 0.0
    halted_drawdown = False
    max_drawdown = 0.0
    pending = []
    realized = []
    selected = [r for r in rows if selection(r)]
    tickets = []
    skips = {"daily_halt": 0, "drawdown_kill": 0, "risk_cap": 0}

    def close_through(now):
        nonlocal cash, peak, daily_realized, day_start, current_day, halted_drawdown, max_drawdown
        while pending and pending[0][0] <= now:
            _, _, row, qty, base_pnl = __import__("heapq").heappop(pending)
            pnl = qty * base_pnl
            cash += pnl
            sleeve_cash[row["coin"]] += pnl
            day = datetime.fromtimestamp(row["end"], timezone.utc).date()
            if current_day != day:
                current_day, daily_realized, day_start = day, 0.0, cash - pnl
            daily_realized += pnl
            peak = max(peak, cash)
            max_drawdown = max(max_drawdown, (peak - cash) / peak if peak else 0.0)
            if cash <= peak * (1 - MAX_DRAWDOWN):
                halted_drawdown = True
            realized.append(dict(time=row["end"], pnl=pnl, r=row["r"],
                                 fill=row["fill"], reason=row["reason"], coin=row["coin"]))

    import heapq
    for _, group_it in __import__("itertools").groupby(selected, key=lambda r: r["time"]):
        group = list(group_it)
        now = group[0]["time"]
        close_through(now)
        signal_day = datetime.fromtimestamp(now, timezone.utc).date()
        if current_day != signal_day:
            current_day, daily_realized, day_start = signal_day, 0.0, cash
        for row in group:
            if halted_drawdown:
                skips["drawdown_kill"] += 1
                continue
            if daily_realized <= -day_start * DAILY_LOSS_LIMIT:
                skips["daily_halt"] += 1
                continue
            order = row["order"]
            budget = sleeve_cash[row["coin"]] * RISK_PER_SLEEVE
            qty = min(budget / order.risk, sleeve_cash[row["coin"]] / (order.entry * (1 + MAKER_FEE)))
            if qty <= 0 or qty * order.entry > sleeve_cash[row["coin"]] * NOTIONAL_CAP:
                skips["risk_cap"] += 1
                continue
            ticket = dict(row, quantity=float(qty), sized_pnl_scenarios={
                s: float(qty * row["pnl_scenarios"][s]) for s in SCENARIOS})
            tickets.append(ticket)
            if row["fill"]:
                heapq.heappush(pending, (row["end"], len(realized) + len(pending), row,
                                         qty, row["pnl_scenarios"]["maker_taker_stop"]))
            else:
                realized.append(dict(time=row["end"], pnl=0.0, r=0.0, fill=False,
                                     reason=row["reason"], coin=row["coin"]))
    close_through(10**20)
    return dict(realized=realized, tickets=tickets, skips=skips, selected=len(selected),
                cash=cash, initial=initial, max_drawdown=max_drawdown)


def _summarize(rows, policy, pnl_field, r_field="r"):
    trades = [r for r in rows if policy(r)]
    filled = [r for r in trades if r["fill"]]
    total = float(sum(r[pnl_field] for r in filled))
    rs = [float(r[r_field]) for r in filled]
    return dict(signals=len(trades), fills=len(filled), expired=sum(r["reason"] == "expired" for r in trades),
                targets=sum(r["reason"] == "target" for r in filled), stops=sum(r["reason"] == "stop" for r in filled),
                timeouts=sum(r["reason"] == "timeout" for r in filled),
                wins=sum(r[pnl_field] > 0 for r in filled), win_rate=(sum(r[pnl_field] > 0 for r in filled) / len(filled) if filled else None),
                net_usdt=total, mean_net_r=(float(np.mean(rs)) if rs else None), total_net_r=float(sum(rs)),
                net_r_per_signal=(float(sum(rs) / len(trades)) if trades else None))


def _daily_block_ci(rows, start=None, end=None, reps=BOOTSTRAP_REPS, seed=BOOTSTRAP_SEED):
    if not rows:
        return None
    first = min(r["time"] for r in rows) if start is None else start
    last = max(r["time"] for r in rows) if end is None else end
    start_day = (first if isinstance(first, date) else datetime.fromtimestamp(first, timezone.utc).date())
    end_day = (last if isinstance(last, date) else datetime.fromtimestamp(last, timezone.utc).date())
    dates = list((start_day.fromordinal(start_day.toordinal() + n))
                 for n in range((end_day - start_day).days + 1))
    day_index = {d: i for i, d in enumerate(dates)}
    by_day_r = np.zeros(len(dates))
    by_day_n = np.zeros(len(dates), dtype=int)
    by_day_usdt = np.zeros(len(dates))
    for r in rows:
        if not r["fill"]:
            continue
        d = datetime.fromtimestamp(r["time"], timezone.utc).date()
        idx = day_index[d]
        by_day_r[idx] += r["r"]
        by_day_n[idx] += 1
        by_day_usdt[idx] += r["pnl"]
    rng = np.random.default_rng(seed)
    samples = []
    n = len(dates)
    for _ in range(reps):
        ids = []
        while len(ids) < n:
            j = int(rng.integers(n))
            ids.extend((j + k) % n for k in range(BLOCK_DAYS))
        ids = np.asarray(ids[:n], dtype=int)
        count = int(by_day_n[ids].sum())
        if count:
            samples.append((float(by_day_r[ids].sum() / count), float(by_day_usdt[ids].sum())))
    if not samples:
        return None
    arr = np.asarray(samples)
    return dict(net_r_per_fill_95=[float(x) for x in np.percentile(arr[:, 0], [2.5, 97.5])],
                net_usdt_95=[float(x) for x in np.percentile(arr[:, 1], [2.5, 97.5])],
                block_days=BLOCK_DAYS, bootstrap_reps=reps, includes_zero_return_days=True)


def random_time_side_baseline(predictions, reps=2000, seed=8721):
    """Post-hoc matched random event times and directions; never used for tuning."""
    groups = {}
    for row in predictions:
        groups.setdefault((row["fold"], row["coin"]), []).append(row)
    wanted = {key: sum(bool(r["model_trade"]) for r in rows) for key, rows in groups.items()}
    rng = np.random.default_rng(seed)
    samples = {s: {"net_usdt": [], "net_r_per_fill": [], "win_rate": [], "fills": []}
               for s in SCENARIOS}
    for _ in range(reps):
        chosen = []
        for key, pool in groups.items():
            count = wanted[key]
            if count == 0:
                continue
            indices = rng.choice(len(pool), size=count, replace=False)
            for index in indices:
                row = dict(pool[int(index)])
                if rng.integers(0, 2):
                    row.update(order=row["continuation_order"],
                               fill=row["continuation_fill"],
                               reason=row["continuation_reason"],
                               end=row["continuation_end"],
                               r=row["continuation_r"],
                               pnl_scenarios=row["continuation_pnl_scenarios"])
                chosen.append(row)
        sized = _risk_sized_trades(chosen, lambda _: True)
        for scenario in SCENARIOS:
            filled = [r for r in sized["tickets"] if r["fill"]]
            pnls = [r["sized_pnl_scenarios"][scenario] for r in filled]
            rs = [p / (r["quantity"] * r["order"].risk)
                  for p, r in zip(pnls, filled)]
            samples[scenario]["net_usdt"].append(float(sum(pnls)))
            samples[scenario]["net_r_per_fill"].append(float(np.mean(rs)) if rs else 0.0)
            samples[scenario]["win_rate"].append(float(sum(p > 0 for p in pnls) / len(pnls)) if pnls else 0.0)
            samples[scenario]["fills"].append(len(filled))
    result = dict(method="random event time without replacement within quarter and coin; 50/50 fade or continuation",
                  seed=seed, repetitions=reps, matched_submitted_orders=sum(wanted.values()),
                  model_selected_by_group={f"{k[0]}/{k[1]}": v for k, v in wanted.items() if v})
    for scenario, metrics in samples.items():
        result[scenario] = {}
        for name, values in metrics.items():
            result[scenario][name] = dict(
                mean=float(np.mean(values)),
                quantiles_2_5_50_97_5=[float(x) for x in np.percentile(values, [2.5, 50, 97.5])])
    return result


def _save_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            flat = dict(row)
            for key, value in list(flat.items()):
                if isinstance(value, Order):
                    flat[key] = json.dumps(asdict(value), separators=(",", ":"))
                elif isinstance(value, dict):
                    flat[key] = json.dumps(value, separators=(",", ":"), default=str)
            writer.writerow(flat)


def load_inputs(end=DATA_END):
    markets = {}
    for coin in COINS:
        markets[coin] = load_market(coin, FIRST, end, depth_folder=Path("data/shock/no-depth"), include_options=False)
    return markets


def run(output=Path("research/shock")):
    output.mkdir(parents=True, exist_ok=True)
    with threadpool_limits(limits=2):
        markets = load_inputs()
        raw, candidates = event_rows(markets)
        predictions, fold_info = [], {}
        for name, first, last in FOLDS:
            tests = _eligible_in_window(candidates, first, last)
            if not tests:
                fold_info[name] = dict(training_rows=0, calibration_rows=0, test_events=0,
                                       model_available=False, reason="no complete test events")
                continue
            try:
                train, calibration = chronological_split(candidates, first)
                model = fit_model(train, calibration)
                pf, pt, ev = score_model(model, tests)
            except ValueError as error:
                fold_info[name] = dict(training_rows=0, calibration_rows=0, test_events=len(tests),
                                       model_available=False, reason=str(error))
                continue
            for row, pfill, ptp, exp in zip(tests, pf, pt, ev):
                predictions.append(dict(row, p_fill=float(pfill), p_tp_given_fill=float(ptp),
                                        expected_net_r=float(exp), model_trade=bool(exp > EV_HURDLE_R),
                                        fold=name))
            fold_info[name] = dict(training_rows=model["train_rows"], calibration_rows=model["calibration_rows"],
                                   calibration_fills=model["calibration_fills"], test_events=len(tests),
                                   model_available=True)

        # Out-of-sample totals are computed on identical candidate dates for each policy.
        order_rows = []
        strategy_metrics = {}
        for fold_name, first, last in FOLDS:
            base = [r for r in candidates if r["time"] >= _quarter_end_epoch(first)
                    and r["time"] + MAX_LIFETIME_SECONDS <= _quarter_end_epoch(last)]
            predicted = [r for r in predictions if r["fold"] == fold_name]
            by_key = {(r["coin"], r["time"]): r for r in predicted}
            for original in base:
                scored = by_key.get((original["coin"], original["time"]))
                if scored is None:
                    continue
                for scenario in SCENARIOS:
                    original["r_" + scenario] = original["pnl_scenarios"][scenario] / original["order"].risk
                row = dict(scored)
                row["fade_pnl_scenarios"] = original["pnl_scenarios"]
                row["continuation_pnl_scenarios"] = original["continuation_pnl_scenarios"]
                row["continuation_reason"] = original["continuation_outcome"].reason
                row["continuation_fill"] = original["continuation_outcome"].fill is not None
                row["continuation_r"] = (original["continuation_pnl_scenarios"]["maker_taker_stop"] /
                                          original["continuation_order"].risk if original["continuation_outcome"].fill is not None else 0.0)
                order_rows.append(row)
            if not predicted:
                continue
            policy_results = {}
            for policy_name, keep in (
                ("model", lambda r: r["model_trade"]),
                ("fade_every_confirmed_event", lambda r: True),
                ("continue_every_confirmed_event", lambda r: True),
            ):
                sample = [dict(r) for r in predicted]
                if policy_name == "continue_every_confirmed_event":
                    for row in sample:
                        row["order"] = row["continuation_order"]
                        row["outcome"] = row["continuation_outcome"]
                        row["fill"] = row["continuation_fill"]
                        row["reason"] = row["continuation_reason"]
                        row["end"] = row["continuation_end"]
                        row["pnl_scenarios"] = row["continuation_pnl_scenarios"]
                        row["r"] = row["continuation_r"]
                selected = [r for r in sample if keep(r)]
                sized = _risk_sized_trades(sample, lambda r: keep(r))
                for scenario in SCENARIOS:
                    pnl_rows = []
                    for r in sized["tickets"]:
                        pnl = r["sized_pnl_scenarios"][scenario] if r["fill"] else 0.0
                        pnl_rows.append(dict(time=r["end"], fill=r["fill"], reason=r["reason"],
                                             r=(pnl / (r["quantity"] * r["order"].risk) if r["fill"] else 0.0),
                                             pnl=pnl))
                    policy_results[policy_name + "/" + scenario] = _summarize(
                        pnl_rows, lambda _: True, "pnl")
                policy_results[policy_name + "/sizing"] = dict(net_usdt_after_risk_sizing=
                    float(sum(x["pnl"] for x in sized["realized"])), cash=sized["cash"],
                    max_drawdown=sized["max_drawdown"],
                    daily_halt_skips=sized["skips"]["daily_halt"],
                    drawdown_kill_skips=sized["skips"]["drawdown_kill"],
                    risk_cap_skips=sized["skips"]["risk_cap"],
                    risk_per_coin_sleeve=RISK_PER_SLEEVE, total_sleeve_fraction=SLEEVE_FRACTION,
                    max_notional_per_sleeve=NOTIONAL_CAP)
            # Calibration metrics use every OOS candidate, not only selected trades.
            policy_results["calibration"] = dict(
                fill_brier=float(brier_score_loss([int(r["fill"]) for r in predicted],
                                                  [r["p_fill"] for r in predicted])),
                tp_brier_filled=(float(brier_score_loss([int(r["tp"]) for r in predicted if r["fill"]],
                                                        [r["p_tp_given_fill"] for r in predicted if r["fill"]]))
                                 if sum(r["fill"] for r in predicted) else None),
                trades_above_ev_hurdle=sum(r["model_trade"] for r in predicted))
            strategy_metrics[fold_name] = policy_results

        # Pooled OOS summaries with scenario-sensitive cash P&L and a joint-day block CI.
        pooled = {}
        pooled_sizing = {}
        for policy in ("model", "fade_every_confirmed_event", "continue_every_confirmed_event"):
            selected = [r for r in predictions if (policy != "model" or r["model_trade"])]
            if policy == "continue_every_confirmed_event":
                filled_rows = []
                for r in selected:
                    item = dict(r, fill=r["continuation_fill"], reason=r["continuation_reason"],
                                end=r["continuation_end"], r=r["continuation_r"],
                                order=r["continuation_order"],
                                pnl_scenarios=r["continuation_pnl_scenarios"])
                    filled_rows.append(item)
                selected = filled_rows
            else:
                selected = [dict(r, pnl_scenarios=r["pnl_scenarios"]) for r in selected]
            scenario_reports = {}
            sized = _risk_sized_trades(selected, lambda _: True)
            pooled_sizing[policy] = dict(
                start_usdt=sized["initial"], end_usdt=sized["cash"],
                net_usdt=sized["cash"] - sized["initial"],
                max_drawdown=sized["max_drawdown"],
                daily_halt_skips=sized["skips"]["daily_halt"],
                drawdown_kill_skips=sized["skips"]["drawdown_kill"],
                risk_cap_skips=sized["skips"]["risk_cap"],
                risk_per_coin_sleeve=RISK_PER_SLEEVE,
                sleeve_fraction=SLEEVE_FRACTION,
                max_notional_per_sleeve=NOTIONAL_CAP)
            for scenario in SCENARIOS:
                subset = []
                for r in sized["tickets"]:
                    pnl = r["sized_pnl_scenarios"][scenario] if r["fill"] else 0.0
                    subset.append(dict(time=r["end"], fill=r["fill"], reason=r["reason"],
                                       r=(pnl / (r["quantity"] * r["order"].risk) if r["fill"] else 0.0),
                                       pnl=pnl))
                report = _summarize(subset, lambda _: True, "pnl")
                report["bootstrap"] = _daily_block_ci(subset,
                    start=date(2025, 1, 1), end=date(2026, 9, 30))
                scenario_reports[scenario] = report
            pooled[policy] = scenario_reports

        by_coin_side = {}
        for policy in ("model", "fade_every_confirmed_event", "continue_every_confirmed_event"):
            selected = [r for r in predictions if policy != "model" or r["model_trade"]]
            for coin in COINS:
                for side in (-1, 1):
                    group = [r for r in selected if r["coin"] == coin and
                             (r["shock_side"] if policy == "continue_every_confirmed_event" else r["side"]) == side]
                    if policy == "continue_every_confirmed_event":
                        pnl = [r["continuation_pnl_scenarios"]["maker_taker_stop"] for r in group
                               if r["continuation_fill"]]
                        fills = [r for r in group if r["continuation_fill"]]
                    else:
                        pnl = [r["pnl_scenarios"]["maker_taker_stop"] for r in group if r["fill"]]
                        fills = [r for r in group if r["fill"]]
                    risks = [(r["continuation_order"].risk if policy == "continue_every_confirmed_event"
                              else r["order"].risk) for r in fills]
                    net_r = [p / risk for p, risk in zip(pnl, risks)]
                    key = f"{policy}/{coin}/{'LONG' if side == 1 else 'SHORT'}"
                    by_coin_side[key] = dict(signals=len(group), fills=len(fills),
                        wins=sum(x > 0 for x in pnl),
                        win_rate=(sum(x > 0 for x in pnl) / len(pnl) if pnl else None),
                        mean_net_r=(float(np.mean(net_r)) if net_r else None),
                        total_net_r=float(sum(net_r)))

        # Calibrate a paper-only model using data through the fixed historical end.
        final_train, final_cal = chronological_split(candidates, DATA_END)
        final_model = fit_model(final_train, final_cal)
        model_path = Path("data/shock/model.joblib")
        model_path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(final_model, model_path)
        model_sha = __import__("hashlib").sha256(model_path.read_bytes()).hexdigest()

        freeze = dict(protocol="research/shock-plan.md", protocol_sha256=__import__("hashlib").sha256(
                      Path("research/shock-plan.md").read_bytes()).hexdigest(),
                      data={c: markets[c].fingerprint for c in COINS}, coins=COINS,
                      data_start=str(FIRST), data_end_exclusive=str(DATA_END),
                      features=FEATURES, xgb=dict(n_estimators=60, max_depth=2, learning_rate=0.05,
                                                 min_child_weight=10, subsample=0.8, colsample_bytree=0.8,
                                                 reg_lambda=5, random_state=421),
                      model_sha256=model_sha, training_rows=final_model["train_rows"],
                      calibration_rows=final_model["calibration_rows"],
                      expected_value_hurdle_r=EV_HURDLE_R)
        results = dict(protocol="shock-plan.md", dates=dict(start=str(FIRST), end_exclusive=str(DATA_END)),
                       raw_shock_events=len(raw), status_counts={}, eligible_candidates=len(candidates),
                       folds=fold_info, quarterly=strategy_metrics, pooled_oos=pooled,
                       pooled_sizing=pooled_sizing, by_coin_side=by_coin_side,
                       exploratory_random_control=random_time_side_baseline(predictions), freeze=freeze)
        for row in raw:
            results["status_counts"][row["status"]] = results["status_counts"].get(row["status"], 0) + 1
        (output / "results.json").write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
        _save_csv(output / "events.csv", raw,
                  ("coin", "event_time", "time", "shock_side", "side", "shock_z", "atr_regime",
                   "confirm_atr", "status", "reason", "fill", "net_r"))
        ledger = []
        for row in order_rows:
            data = dict(coin=row["coin"], signal_utc=utc_iso(row["time"]), event_utc=utc_iso(row["event_time"]),
                        fold=row["fold"], side="LONG" if row["side"] == 1 else "SHORT",
                        shock_z=row["shock_z"], features=row["values"], p_fill=row["p_fill"],
                        p_tp_given_fill=row["p_tp_given_fill"], expected_net_r=row["expected_net_r"],
                        model_trade=row["model_trade"], entry=row["order"].entry, stop=row["order"].stop,
                        target=row["order"].target, risk_per_coin=row["order"].risk, outcome=row["reason"],
                        fill=row["fill"], end_utc=utc_iso(row["end"]), net_r=row["r"],
                        net_pnl_scenarios=row["fade_pnl_scenarios"],
                        continuation_outcome=row["continuation_reason"],
                        continuation_net_pnl_scenarios=row["continuation_pnl_scenarios"])
            ledger.append(data)
        _save_csv(output / "signals.csv", ledger, tuple(ledger[0]) if ledger else
                  ("coin", "signal_utc", "fold", "side", "p_fill", "expected_net_r", "model_trade"))
        (output / "freeze.json").write_text(json.dumps(freeze, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps(dict(events=len(raw), candidates=len(candidates), folds=fold_info,
                              model_sha256=model_sha), indent=2))
        return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true",
                        help="download missing public Binance candle and funding archives")
    args = parser.parse_args(argv)
    if args.prepare:
        from flow_data import prepare_range
        for feed in ("candles", "funding"):
            prepare_range(feed, FIRST, DATA_END)
    run()


if __name__ == "__main__":
    main()
