"""Cache point-in-time inputs for the two-sided perpetuals experiment."""
import argparse
import hashlib
import io
import json
import math
import os
import tempfile
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import ZipFile

from compare import COINS

ROOT = Path("data/perp-flow-v1")
FIRST = date(2025, 10, 1)
HOLDOUT = date(2026, 3, 1)
LAST = date(2026, 5, 1)
ARCHIVE = "https://data.binance.vision/data/futures/um"
FUTURES = "https://fapi.binance.com/fapi/v1"
DERIBIT = "https://history.deribit.com/api/v2/public"
LIVE_DERIBIT = "https://www.deribit.com/api/v2/public"


def epoch(day):
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def dates(start, end):
    return [start + timedelta(days=i) for i in range((end - start).days)]


def fetch(url):
    for attempt in range(5):
        try:
            with urlopen(Request(url, headers={"User-Agent": "algorithmic-trading-research/1.0"}),
                         timeout=30) as response:
                return response.read()
        except (HTTPError, URLError, TimeoutError, ConnectionError) as error:
            if isinstance(error, HTTPError) and error.code not in (408, 418, 429, 500, 502, 503, 504):
                raise
            if attempt == 4:
                raise
            delay = 2 ** attempt
            if isinstance(error, HTTPError):
                wait = error.headers.get("Retry-After", "")
                if wait.isdigit():
                    delay = max(delay, int(wait))
            time.sleep(delay)


def persist(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp:
        try:
            temp.write(data)
            temp.close()
            os.replace(temp.name, path)
        finally:
            Path(temp.name).unlink(missing_ok=True)


def save_json(path, value):
    persist(path, json.dumps(value, allow_nan=False, separators=(",", ":")).encode())


def archive(url):
    blob = fetch(url)
    digest = hashlib.sha256(blob).hexdigest()
    if digest != fetch(url + ".CHECKSUM").decode().split()[0].lower():
        raise ValueError(f"SHA-256 mismatch for {url}")
    return blob, digest


def request_json(url, params):
    return json.loads(fetch(url + "?" + urlencode(params)))


def options_window(currency, start_ms, stop_ms, host=DERIBIT):
    """Complete a half-open event window even when the API truncates a page."""
    params = dict(currency=currency, kind="option", start_timestamp=start_ms,
                  end_timestamp=stop_ms - 1, count=1000, sorting="asc")
    url = host + "/get_last_trades_by_currency_and_time"
    for attempt in range(5):
        payload = request_json(url, params)
        if payload.get("error", {}).get("code") != 10028:
            break
        time.sleep(2 ** attempt)
    if "result" not in payload:
        raise ValueError(f"Deribit {currency} {start_ms}: {payload.get('error')}")
    result = payload["result"]
    if result["has_more"]:
        mid = (start_ms + stop_ms) // 2
        if mid == start_ms:
            raise ValueError("Deribit trade count exceeds available millisecond resolution")
        return options_window(currency, start_ms, mid, host) + options_window(currency, mid, stop_ms, host)
    rows = result["trades"]
    if any(not start_ms <= row["timestamp"] < stop_ms for row in rows):
        raise ValueError("Deribit returned an event outside the requested window")
    return rows


def summarize_options(rows, currency):
    amounts = dict.fromkeys(("call_buy", "call_sell", "put_buy", "put_sell"), 0.0)
    seen = set()
    excluded = 0
    for t in rows:
        key = t["trade_id"]
        if key in seen:
            raise ValueError(f"Duplicate Deribit trade {currency} {key}")
        seen.add(key)
        parts = t["instrument_name"].split("-")
        if (len(parts) != 4 or parts[0] != currency or parts[-1] not in ("C", "P")
                or t.get("block_trade_id") or t.get("combo_trade_id") or t.get("combo_id")):
            excluded += 1
            continue
        kind = "call" if parts[-1] == "C" else "put"
        premium = t["amount"] * t["price"] * t["index_price"]
        if not math.isfinite(premium) or premium < 0:
            raise ValueError("Invalid option premium")
        amounts[f"{kind}_{t['direction']}"] += premium
    return dict(**amounts, trades=len(seen) - excluded, excluded=excluded)


def options_file(job):
    currency, day = job
    path = ROOT / "options" / currency / f"{day}.json"
    if path.exists():
        return
    samples = []
    for hour in (0, 6, 12, 18):
        end = epoch(day) + hour * 3600
        rows = options_window(currency, (end - 1200) * 1000, end * 1000)
        samples.append(dict(asof=end, **summarize_options(rows, currency)))
    save_json(path, samples)


def depth_samples(blob, day, interval=3600):
    """Keep the last complete snapshot in the final three minutes of each hour."""
    levels = {-1.0: "bid_near", 1.0: "ask_near", -2.0: "bid_wide", 2.0: "ask_wide"}
    books = defaultdict(dict)
    with ZipFile(io.BytesIO(blob)) as zipped:
        with zipped.open(zipped.namelist()[0]) as file:
            if file.readline().strip() != b"timestamp,percentage,depth,notional":
                raise ValueError("Unrecognized bookDepth format")
            for line in file:
                if interval == 3600 and line[14:16] < b"57":
                    continue
                stamp, pct, _, notional = line.strip().split(b",")
                band = float(pct)
                if band in levels:
                    value = float(notional)
                    if not math.isfinite(value) or value < 0:
                        raise ValueError("Invalid depth notional")
                    books[stamp][levels[band]] = value
    result = {}
    for stamp, book in sorted(books.items()):
        if len(book) != 4 or min(book.values()) <= 0:
            continue
        instant = datetime.fromisoformat(stamp.decode()).replace(tzinfo=timezone.utc)
        if instant.date() != day:
            raise ValueError("Depth timestamp outside archive date")
        t = int(instant.timestamp())
        result[(t // interval + 1) * interval] = dict(observed=t, **book)
    return result


def depth_file(job, interval=3600):
    coin, day = job
    folder = "depth-1-2pct" if interval == 3600 else "depth-5m"
    path = ROOT / folder / coin / f"{day}.json"
    if path.exists():
        return
    pair = coin + "USDT"
    url = f"{ARCHIVE}/daily/bookDepth/{pair}/{pair}-bookDepth-{day}.zip"
    try:
        blob, digest = archive(url)
    except HTTPError as error:
        if error.code != 404:
            raise
        save_json(path, dict(url=url, status="missing", samples={}))
        return
    save_json(path, dict(url=url, sha256=digest, samples=depth_samples(blob, day, interval)))


def candle_file(job):
    coin, day = job
    month = day.strftime("%Y-%m")
    pair = coin + "USDT"
    path = ROOT / "candles" / coin / f"{month}.zip"
    if path.exists():
        return
    url = f"{ARCHIVE}/monthly/klines/{pair}/5m/{pair}-5m-{month}.zip"
    blob, _ = archive(url)
    persist(path, blob)


def funding_file(job):
    coin, day = job
    path = ROOT / "funding" / coin / f"{day:%Y-%m}.json"
    if path.exists():
        return
    next_month = (day.replace(day=28) + timedelta(days=4)).replace(day=1)
    pair = coin + "USDT"
    first, end = epoch(day) * 1000, epoch(next_month) * 1000
    rows = request_json(FUTURES + "/fundingRate", dict(symbol=pair, startTime=first,
                                                        endTime=end - 1, limit=1000))
    if not isinstance(rows, list) or not rows or len(rows) >= 1000:
        raise ValueError(f"Incomplete funding response for {pair} {day}")
    stamps = [row["fundingTime"] for row in rows]
    if (stamps != sorted(set(stamps)) or stamps[0] < first or stamps[-1] >= end
            or max(b - a for a, b in zip([first] + stamps, stamps + [end])) > 9 * 3600_000):
        raise ValueError(f"Invalid funding coverage for {pair} {day}")
    for row in rows:
        if (row["symbol"] != pair or not math.isfinite(float(row["fundingRate"]))
                or not 0 < float(row["markPrice"]) < math.inf):
            raise ValueError("Invalid funding event")
    save_json(path, rows)


def prepare(kind, stage):
    first, last = (FIRST, HOLDOUT) if stage == "train" else (HOLDOUT, LAST)
    prepare_range(kind, first, last)


def prepare_range(kind, first, last):
    days = dates(first, last)
    task = {"candles": candle_file, "funding": funding_file, "depth": depth_file,
            "options": options_file}[kind]
    if kind in ("candles", "funding"):
        days = [d for d in days if d.day == 1]
    coins = ("BTC", "ETH") if kind == "options" else COINS
    jobs = [(c, d) for d in days for c in coins]
    with ThreadPoolExecutor(max_workers=2 if kind == "options" else 6) as pool:
        for n, _ in enumerate(pool.map(task, jobs), 1):
            if n % 100 == 0 or n == len(jobs):
                print(f"{first} {kind}: {n}/{len(jobs)}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("train", "test"), required=True)
    parser.add_argument("--feed", choices=("candles", "funding", "depth", "options", "all"), default="all")
    args = parser.parse_args()
    for feed in (("candles", "funding", "depth", "options") if args.feed == "all" else (args.feed,)):
        prepare(feed, args.stage)
