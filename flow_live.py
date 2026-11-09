"""Record real depth snapshots, executed buy/sell flow and option prints without an account."""
import argparse
import gzip
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from compare import COINS
from flow_data import FUTURES, LIVE_DERIBIT, options_window, persist, request_json, save_json, summarize_options


FORWARD = Path("data/forward-flow")


def band_depth(bids, asks, mid, fraction):
    low, high = mid * (1 - fraction), mid * (1 + fraction)
    bid = sum(p * q for p, q in bids if p >= low)
    ask = sum(p * q for p, q in asks if p <= high)
    complete = bids[-1][0] <= low and asks[-1][0] >= high
    return dict(bid_usdt=bid, ask_usdt=ask, complete=complete,
                imbalance=(bid - ask) / (bid + ask) if complete and bid + ask else None)


def snapshot_book(raw):
    bids, asks = [[(float(p), float(q)) for p, q in raw[k]] for k in ("bids", "asks")]
    if (not bids or not asks or bids[0][0] >= asks[0][0]
            or any(p <= 0 or q < 0 or not (math.isfinite(p) and math.isfinite(q)) for p, q in bids + asks)
            or any(a[0] <= b[0] for a, b in zip(bids, bids[1:]))
            or any(a[0] >= b[0] for a, b in zip(asks, asks[1:]))):
        raise ValueError("Invalid public depth snapshot")
    mid = 0.5 * (bids[0][0] + asks[0][0])
    bands = {str(bps): band_depth(bids, asks, mid, bps / 10_000) for bps in (5, 10, 20, 100, 200)}
    return dict(observed_ms=raw["T"], seq=raw["lastUpdateId"], mid=mid,
                spread_bps=10_000 * (asks[0][0] - bids[0][0]) / mid,
                bands_bps=bands)


def taker_flow(coin, end_ms):
    rows = request_json(FUTURES + "/klines", dict(symbol=coin + "USDT", interval="1m",
                                                  startTime=end_ms - 3600_000, endTime=end_ms - 1, limit=60))
    expected = list(range(end_ms - 3600_000, end_ms, 60_000))
    if [r[0] for r in rows] != expected or any(r[6] != r[0] + 59_999 for r in rows):
        raise ValueError(f"{coin} incomplete closed minute candles")
    out = {}
    for minutes in (15, 60):
        subset = rows[-minutes:]
        total = sum(float(r[7]) for r in subset)
        buy = sum(float(r[10]) for r in subset)
        if not 0 <= buy <= total or not math.isfinite(total):
            raise ValueError("Invalid taker quote volume")
        out[str(minutes)] = dict(buy_usdt=buy, sell_usdt=total - buy,
                                 buy_pct=100 * buy / total if total else None)
    return out


def record_coin(coin, cutoff_ms):
    raw = request_json(FUTURES + "/depth", dict(symbol=coin + "USDT", limit=1000))
    received = time.time_ns() // 1_000_000
    book = snapshot_book(raw)
    # Prefer missing data over silently presenting an old cached book as live.
    if not -5_000 <= received - book["observed_ms"] <= 15_000:
        raise ValueError(f"{coin} depth clock is stale or local clock needs synchronization")
    return coin, dict(received_ms=received, book=book, taker=taker_flow(coin, cutoff_ms)), raw


def options_at(currency, cutoff_ms):
    rows = options_window(currency, cutoff_ms - 1200_000, cutoff_ms, host=LIVE_DERIBIT)
    return dict(asof_ms=cutoff_ms, received_ms=time.time_ns() // 1_000_000, **summarize_options(rows, currency))


@lru_cache(maxsize=4)
def anchored_options(currency, cutoff_ms):
    return options_at(currency, cutoff_ms)


def capture():
    now = request_json(FUTURES + "/time", {})["serverTime"]
    end = (now - 2000) // 60_000 * 60_000
    anchor = end // 21_600_000 * 21_600_000
    with ThreadPoolExecutor(max_workers=3) as pool:
        coin_rows = list(pool.map(lambda c: record_coin(c, end), COINS))
        option_rows = dict(zip(("BTC", "ETH"), pool.map(lambda c: options_at(c, end), ("BTC", "ETH"))))
        training_options = dict(zip(("BTC", "ETH"), pool.map(lambda c: anchored_options(c, anchor), ("BTC", "ETH"))))
    summary = dict(captured_ms=now, taker_end_exclusive_ms=end, options_window_minutes=20,
                   coins={c: record for c, record, _ in coin_rows}, options=option_rows,
                   options_6h_anchor=training_options)
    raw = {c: book for c, _, book in coin_rows}
    stamp = datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%Y-%m-%d/%H%M%S-%f")
    capture_path = FORWARD / "snapshots" / f"{stamp}.json.gz"
    persist(capture_path, gzip.compress(json.dumps(dict(summary=summary, books=raw)).encode()))
    save_json(FORWARD / "latest.json", summary)
    print("15-minute taker buy share through", datetime.fromtimestamp(end / 1000, timezone.utc).isoformat())
    for coin, record, _ in coin_rows:
        buy = record["taker"]["15"]["buy_pct"]
        bands = record["book"]["bands_bps"]
        pct = "no trades" if buy is None else f"{buy:.1f}%"
        print(coin, pct, "| complete +/-2% book:", bands["200"]["complete"])
    return summary


def comparable_book(record):
    """Only timely, complete samples can replace the archived hourly book in a later replay."""
    b = record["book"]
    observed = b["observed_ms"] // 1000
    boundary = (observed // 3600 + 1) * 3600
    bands = b["bands_bps"]
    if (boundary - observed > 180 or record["received_ms"] > (boundary + 300) * 1000
            or not all(bands[k]["complete"] for k in ("100", "200"))):
        return None
    return boundary, dict(observed=observed, bid_near=bands["100"]["bid_usdt"],
                          ask_near=bands["100"]["ask_usdt"], bid_wide=bands["200"]["bid_usdt"],
                          ask_wide=bands["200"]["ask_usdt"])


def export_hourly():
    """Emit the same daily schema used by load_market, preserving gaps in the capture."""
    by_day = {}
    for path in sorted((FORWARD / "snapshots").glob("*/*.json.gz")):
        with gzip.open(path, "rt", encoding="utf-8") as file:
            batch = json.load(file)["summary"]
        for coin, record in batch["coins"].items():
            sample = comparable_book(record)
            if sample:
                boundary, book = sample
                day = datetime.fromtimestamp(book["observed"], timezone.utc).date()
                daily = by_day.setdefault((coin, day), {})
                if boundary not in daily or daily[boundary]["observed"] <= book["observed"]:
                    daily[boundary] = book
    for (coin, day), samples in by_day.items():
        save_json(FORWARD / "hourly-depth" / coin / f"{day}.json", dict(source="live captures", samples=samples))
    print("Complete observable coin-hours:", sum(map(len, by_day.values())))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1, help="number of complete six-coin snapshots")
    parser.add_argument("--interval", type=int, default=60, help="seconds between snapshots (minimum 5)")
    parser.add_argument("--export-hourly", action="store_true", help="export comparable historical depth records")
    args = parser.parse_args()
    if args.count < 1 or args.interval < 5:
        parser.error("count must be positive and interval must be at least five seconds")
    if args.export_hourly:
        export_hourly()
    else:
        for i in range(args.count):
            if i:
                time.sleep(args.interval)
            capture()
