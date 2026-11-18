"""Historical simulation of cross-sectional funding carry (rules: research/cross-carry-plan.md)."""
import argparse
import csv
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from zipfile import ZipFile

import numpy as np

from flow_data import fetch, persist, save_json
from wave_validation import write_csv

DATA = Path("data/cross-carry")
OUT = Path("research/cross-carry")
BUCKET = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"
ARCH = "https://data.binance.vision/data"
FUT, SPOT = "futures/um/monthly", "spot/monthly"
FIRST, LAST = date(2021, 1, 1), date(2026, 10, 1)
RECENT = date(2024, 1, 1)
CAPITAL = 10_000.
SPOT_FEE, PERP_FEE, SLIP, LIQ_PAD = .001, .0005, .0005, .002
HURDLE, LOOKBACK, MIN_PRINTS, UNIVERSE, TOP20 = .04, 30, 30, 40, 20
MAINT = .05
DAY_MS = 86_400_000
BOOT_N, BOOT_BLOCK, SEED = 2000, 30, 20260101
EPOCH = date(1970, 1, 1)


def dnum(d):
    return (d - EPOCH).days


def next_month(d):
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def months(start, end):
    out = []
    while start <= end:
        out.append(start)
        start = next_month(start)
    return out


def listing(prefix, delimiter=True):
    out, marker = [], ""
    while True:
        url = f"{BUCKET}?prefix={prefix}" + ("&delimiter=/" if delimiter else "") + (f"&marker={marker}" if marker else "")
        body = fetch(url).decode()
        out += re.findall(r"<Prefix>([^<]+)</Prefix>" if delimiter else r"<Key>([^<]+)</Key>",
                          body.split("<CommonPrefixes>", 1)[-1] if delimiter else body)
        if "<IsTruncated>true</IsTruncated>" not in body:
            return out
        marker = out[-1]


def universe_symbols():
    path = DATA / "listing.json"
    if path.exists():
        return [x for x in json.loads(path.read_text()) if x.isascii()]
    perp = {p.split("/")[-2] for p in listing(f"data/{FUT}/fundingRate/")}
    spot = {p.split("/")[-2] for p in listing(f"data/{SPOT}/klines/")}
    syms = sorted(s for s in perp & spot if s.endswith("USDT") and s.isascii() and s.isalnum() and not s[0].isdigit())
    save_json(path, syms)
    return syms


def symbol_months(sym):
    keys = listing(f"data/{FUT}/fundingRate/{sym}/", delimiter=False)
    found = sorted(m.group(1) for k in keys if (m := re.search(r"-(\d{4}-\d{2})\.zip$", k)))
    return [date(int(m[:4]), int(m[5:]), 1) for m in found if m >= "2020-12"]


def files(sym, month):
    m = f"{month:%Y-%m}"
    return {"funding": f"{FUT}/fundingRate/{sym}/{sym}-fundingRate-{m}.zip",
            "perp": f"{FUT}/klines/{sym}/1d/{sym}-1d-{m}.zip",
            "spot": f"{SPOT}/klines/{sym}/1d/{sym}-1d-{m}.zip"}


def cached(rel):
    path = DATA / rel
    if path.exists():
        return path.read_bytes()
    try:
        blob = fetch(f"{ARCH}/{rel}")
    except HTTPError as error:
        if error.code != 404:
            raise
        blob = b""
    persist(path, blob)
    return blob


def download(syms, workers=16):
    def plan(sym):
        ms = symbol_months(sym)
        return [(rel) for m in months(ms[0], min(ms[-1], LAST)) for rel in files(sym, m).values()] if ms else []
    with ThreadPoolExecutor(workers) as pool:
        rels = [r for rs in pool.map(plan, syms) for r in rs]
        done = 0
        for _ in pool.map(cached, rels):
            done += 1
            if done % 2000 == 0:
                print(f"{done}/{len(rels)} files", flush=True)
    return len(rels)


def rows_of(blob):
    if not blob:
        return []
    with ZipFile(io.BytesIO(blob)) as z:
        text = z.read(z.namelist()[0]).decode()
    return [r for r in csv.reader(text.splitlines()) if r and r[0].strip().isdigit()]


def parse_klines(blob):
    out = {}
    for r in rows_of(blob):
        t = int(r[0])
        while t > 10**13:
            t //= 1000
        out[t // DAY_MS] = tuple(float(r[i]) for i in (1, 2, 3, 4, 7))
    return out


def parse_funding(blob):
    return [(int(r[0]), float(r[2]), float(r[1]) if r[1] else 8.) for r in rows_of(blob)]


@dataclass
class Sym:
    name: str
    po: np.ndarray
    ph: np.ndarray
    pc: np.ndarray
    pq: np.ndarray
    so: np.ndarray
    sc: np.ndarray
    sq: np.ndarray
    ft: np.ndarray
    fr: np.ndarray
    fh: np.ndarray


def make_sym(name, base, n, perp, spot, funding):
    """perp/spot: {day: (open, high, low, close, quote_volume)}; funding: [(ms, rate, hours)]."""
    def col(d, k):
        a = np.full(n, np.nan)
        for day, v in d.items():
            if 0 <= day - base < n:
                a[day - base] = v[k]
        return a
    f = sorted(set(funding))
    ft = np.array([x[0] for x in f], dtype=np.int64)
    return Sym(name, col(perp, 0), col(perp, 1), col(perp, 3), col(perp, 4),
               col(spot, 0), col(spot, 3), col(spot, 4), ft,
               np.array([x[1] for x in f]), np.array([x[2] for x in f]))


def load(syms, base, n):
    out = {}
    for s in syms:
        perp, spot, fund = {}, {}, []
        for path in sorted((DATA / FUT / "klines" / s / "1d").glob("*.zip")):
            perp.update(parse_klines(path.read_bytes()))
        for path in sorted((DATA / SPOT / "klines" / s / "1d").glob("*.zip")):
            spot.update(parse_klines(path.read_bytes()))
        for path in sorted((DATA / FUT / "fundingRate" / s).glob("*.zip")):
            fund += parse_funding(path.read_bytes())
        if perp and spot and fund:
            out[s] = make_sym(s, base, n, perp, spot, fund)
    return out


def round_trip(mult):
    return 2 * (SPOT_FEE + PERP_FEE + 2 * SLIP * mult)


def clears(score, mult):
    """Annualised score must beat round-trip costs (over 30 days) plus 4% on slot capital (= 2x leg notional)."""
    return score > 2 * HURDLE + round_trip(mult) * 365 / LOOKBACK


def slip_mult(rank):
    return 1 if rank is not None and rank <= TOP20 else 2


def decide(syms, base, first):
    """Eligible universe at 00:00 of `first` (day number). Uses only bars and prints strictly before it."""
    i1 = first - base
    i0 = i1 - LOOKBACK
    if i0 < 0:
        return []
    cut, start = first * DAY_MS, (first - LOOKBACK) * DAY_MS
    found = []
    for s in syms.values():
        w = slice(i0, i1)
        if np.isnan(s.pc[w]).any() or np.isnan(s.sc[w]).any():
            continue
        lo, hi = np.searchsorted(s.ft, start, "left"), np.searchsorted(s.ft, cut, "left")
        if hi - lo < MIN_PRINTS:
            continue
        score = float(np.mean(s.fr[lo:hi] * 8760 / s.fh[lo:hi]))
        found.append((min(s.pq[w].sum(), s.sq[w].sum()), s.name, score))
    found.sort(key=lambda x: (-x[0], x[1]))
    return [{"sym": n, "rank": k + 1, "vol": v, "score": sc} for k, (v, n, sc) in enumerate(found[:UNIVERSE])]


def picks(uni, mode):
    if mode == "ew":
        return list(uni)
    ok = [u for u in uni if clears(u["score"], slip_mult(u["rank"]))]
    return sorted(ok, key=lambda u: (-u["score"], u["sym"]))[:10]


def trade_cost(spot_notional, perp_notional, mult):
    return spot_notional * SPOT_FEE + perp_notional * PERP_FEE, (spot_notional + perp_notional) * SLIP * mult


def run(syms, base, n, mons, mode, halve=False, liq_margin=.5, weight=None):
    """Daily marked simulation. liq_margin: perp margin as a share of notional (.5 = 2x)."""
    weight = weight or (.025 if mode == "ew" else .10)
    d0 = dnum(mons[0])
    d_end = dnum(next_month(mons[-1])) - 1
    days = d_end - d0 + 1
    decisions = {m: decide(syms, base, dnum(m)) for m in mons}
    chosen = {m: picks(decisions[m], mode) for m in mons}
    trade_day = {dnum(m) + 1: m for m in mons}
    cash, pos = CAPITAL, {}
    eq = np.zeros(days)
    led = np.zeros((days, 4))
    cm = {}

    def row(m, s):
        return cm.setdefault((m, s), dict(funding=0., basis=0., fees=0., slippage=0., liquidated=0, delisted=0))

    def mark(d, p):
        s = syms[p["sym"]]
        return p["q"] * s.sc[d - base] + p["margin"] + p["q"] * (p["p0"] - s.pc[d - base])

    def close(p, d, ps, pp, mult, ledger_i, r):
        nonlocal cash
        fees, slip = trade_cost(p["q"] * ps, p["q"] * pp, mult)
        cash += p["q"] * ps + p["margin"] + p["q"] * (p["p0"] - pp) - fees - slip
        led[ledger_i, 2] += fees
        led[ledger_i, 3] += slip
        r["fees"] += fees
        r["slippage"] += slip
        del pos[p["sym"]]

    prev_eq = CAPITAL
    for k in range(days):
        d = d0 + k
        day = date.fromordinal(EPOCH.toordinal() + d)
        m = day.replace(day=1)
        i = d - base
        if d in trade_day:
            tm = trade_day[d]
            target = {u["sym"]: u for u in chosen[tm]}
            rank = {u["sym"]: u["rank"] for u in decisions[tm]}
            edec = eq[k - 2] if k >= 2 else CAPITAL
            for sym in [s for s in pos if s not in target]:
                p, s = pos[sym], syms[sym]
                r = row(m, sym)
                if np.isnan(s.pc[i]) or np.isnan(s.sc[i]):
                    continue
                gap = p["q"] * ((s.so[i] - p["ps"]) + (p["pp"] - s.po[i]))
                led[k, 1] += gap
                r["basis"] += gap
                close(p, d, s.so[i], s.po[i], slip_mult(rank.get(sym)), k, r)
            for u in chosen[tm]:
                sym, s = u["sym"], syms[u["sym"]]
                if sym in pos or any(np.isnan(x[i]) for x in (s.so, s.po, s.sc, s.pc, s.ph)):
                    continue
                mult = slip_mult(u["rank"])
                c = min(weight * edec, cash / (1 + 2 * (SPOT_FEE + PERP_FEE + 2 * SLIP * mult)))
                if c <= 0:
                    continue
                q = c / 2 / s.so[i]
                margin = q * s.po[i]
                fees, slip = trade_cost(q * s.so[i], q * s.po[i], mult)
                cash -= q * s.so[i] + margin + fees + slip
                pos[sym] = dict(sym=sym, q=q, p0=s.po[i], margin=margin, ps=s.so[i], pp=s.po[i], mult=mult, entry=d)
                r = row(m, sym)
                led[k, 2] += fees
                led[k, 3] += slip
                r["fees"] += fees
                r["slippage"] += slip
        for sym in list(pos):
            p, s = pos[sym], syms[sym]
            r = row(m, sym)
            if np.isnan(s.pc[i]) or np.isnan(s.sc[i]) or np.isnan(s.ph[i]):
                r["delisted"] = 1
                close(p, d, p["ps"], p["pp"], p["mult"], k, r)
                continue
            q = p["q"]
            lo = np.searchsorted(s.ft, d * DAY_MS, "right" if d == p["entry"] else "left")
            hi = np.searchsorted(s.ft, (d + 1) * DAY_MS, "left")
            flow = float(q * (s.fr[lo:hi] * s.pc[i]).sum()) if hi > lo else 0.
            ratio = (liq_margin * q * p["p0"] - q * (s.ph[i] - p["p0"])) / (q * s.ph[i])
            if ratio < MAINT:
                pb = s.ph[i] * (1 + LIQ_PAD)
                flow = min(flow, 0.)
                basis = q * ((s.sc[i] - p["ps"]) + (p["pp"] - pb))
                r["liquidated"] = 1
                cash += flow
                led[k, 0] += flow
                led[k, 1] += basis
                r["funding"] += flow
                r["basis"] += basis
                fees, slip = trade_cost(q * s.sc[i], q * pb, p["mult"])
                slip -= q * pb * SLIP * p["mult"]
                cash += q * s.sc[i] + p["margin"] + q * (p["p0"] - pb) - fees - slip
                led[k, 2] += fees
                led[k, 3] += slip
                r["fees"] += fees
                r["slippage"] += slip
                del pos[sym]
                continue
            if halve and flow > 0:
                flow *= .5
            basis = q * ((s.sc[i] - p["ps"]) + (p["pp"] - s.pc[i]))
            cash += flow
            led[k, 0] += flow
            led[k, 1] += basis
            r["funding"] += flow
            r["basis"] += basis
            p["ps"], p["pp"] = s.sc[i], s.pc[i]
        if k == days - 1:
            for sym in list(pos):
                p, s = pos[sym], syms[sym]
                close(p, d, p["ps"], p["pp"], p["mult"], k, row(m, sym))
        eq[k] = cash + sum(mark(d, p) for p in pos.values())
        change = eq[k] - prev_eq
        if abs(change - (led[k, 0] + led[k, 1] - led[k, 2] - led[k, 3])) > 1e-6 * max(1., abs(eq[k])):
            raise ValueError(f"Ledger does not reconcile on {day}: {change} vs {led[k]}")
        prev_eq = eq[k]
    return dict(eq=eq, led=led, d0=d0, cm=cm, decisions=decisions, chosen=chosen)


def period_stats(res, start, end, base_eq=CAPITAL):
    k0, k1 = max(dnum(start) - res["d0"], 0), min(dnum(end) - res["d0"], len(res["eq"]))
    eq = res["eq"][k0:k1]
    first = res["eq"][k0 - 1] if k0 > 0 else base_eq
    path = np.concatenate([[first], eq])
    r = path[1:] / path[:-1] - 1
    led = res["led"][k0:k1].sum(axis=0)
    years = len(r) / 365
    dd = (path / np.maximum.accumulate(path) - 1).min()
    ends = [i for i in range(len(eq)) if date.fromordinal(EPOCH.toordinal() + res["d0"] + k0 + i + 1).day == 1 or i == len(eq) - 1]
    mp = path[[0] + [i + 1 for i in ends]]
    mret = mp[1:] / mp[:-1] - 1
    sd = r.std(ddof=1) if len(r) > 1 else 0.
    return dict(days=len(r), net_usdt=float(path[-1] - first), return_on_10000=float((path[-1] - first) / CAPITAL),
                cagr=float((path[-1] / first) ** (1 / years) - 1) if years > 0 and path[-1] > 0 else None,
                vol=float(sd * np.sqrt(365)), sharpe=float(r.mean() / sd * np.sqrt(365)) if sd > 1e-5 else None,
                max_drawdown=float(dd), funding=float(led[0]), basis=float(led[1]), fees=float(led[2]),
                slippage=float(led[3]), months=len(mret), months_positive=int((mret > 0).sum()))


def bootstrap(res, start, end, n=BOOT_N, block=BOOT_BLOCK, seed=SEED):
    k0, k1 = max(dnum(start) - res["d0"], 0), min(dnum(end) - res["d0"], len(res["eq"]))
    first = res["eq"][k0 - 1] if k0 > 0 else CAPITAL
    path = np.concatenate([[first], res["eq"][k0:k1]])
    lr = np.log(path[1:] / path[:-1])
    m = len(lr)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, m, size=(n, -(-m // block)))
    idx = ((starts[:, :, None] + np.arange(block)) % m).reshape(n, -1)[:, :m]
    annual = np.exp(lr[idx].sum(axis=1) * 365 / m) - 1
    lo, hi = np.percentile(annual, [2.5, 97.5])
    return dict(lower=float(lo), upper=float(hi), median=float(np.median(annual)), blocks_days=block, resamples=n)


def cash_result(d0, days, rate):
    eq = CAPITAL * (1 + rate * (np.arange(days) + 1) / 365)
    return dict(eq=eq, led=np.zeros((days, 4)), d0=d0)


def evaluate(syms, base, n, mons):
    full = (FIRST, next_month(LAST))
    periods = {"full": full, "recent_2024+": (RECENT, next_month(LAST)), "pre_2024": (FIRST, RECENT)}
    periods.update({str(y): (date(y, 1, 1), min(date(y + 1, 1, 1), next_month(LAST))) for y in range(2021, 2027)})
    days = dnum(next_month(LAST)) - dnum(FIRST)
    runs = {"top10": run(syms, base, n, mons, "top10"), "ew40": run(syms, base, n, mons, "ew")}
    stress = {"top10": run(syms, base, n, mons, "top10", halve=True), "ew40": run(syms, base, n, mons, "ew", halve=True)}
    cash = {"cash": cash_result(dnum(FIRST), days, 0.), "cash_4pct": cash_result(dnum(FIRST), days, .04)}
    lev1 = {"top10": run(syms, base, n, mons, "top10", liq_margin=1.), "ew40": run(syms, base, n, mons, "ew", liq_margin=1.)}
    out = {"label": "historical simulation", "strategies": {}}
    for name, res in {**runs, **cash}.items():
        out["strategies"][name] = {p: period_stats(res, *w) for p, w in periods.items()}
    for name in runs:
        s = out["strategies"][name]
        s["bootstrap_full"] = bootstrap(runs[name], *periods["full"])
        s["bootstrap_recent_2024+"] = bootstrap(runs[name], *periods["recent_2024+"])
        s["halved_positive_funding"] = {p: period_stats(stress[name], *periods[p]) for p in ("full", "recent_2024+")}
        s["halved_positive_funding"]["bootstrap_full"] = bootstrap(stress[name], *periods["full"])
        s["liquidations"] = sum(r["liquidated"] for r in runs[name]["cm"].values())
        s["delistings"] = sum(r["delisted"] for r in runs[name]["cm"].values())
        s["sensitivity_1x_margin"] = {"liquidations": sum(r["liquidated"] for r in lev1[name]["cm"].values()),
                                      "bootstrap_full": bootstrap(lev1[name], *periods["full"]),
                                      **{p: period_stats(lev1[name], *periods[p]) for p in ("full", "recent_2024+")}}
    t = out["strategies"]["top10"]
    out["pass"] = bool(t["bootstrap_full"]["lower"] > 0 and (t["recent_2024+"]["cagr"] or -1) > .04)
    out["pass_rule"] = "full-period bootstrap 95% lower bound > 0 and recent (2024-01+) CAGR > 4%"
    return out, runs


def ledger_rows(runs):
    rows = []
    for mode, res in runs.items():
        for m in sorted(res["chosen"]):
            uni = {u["sym"]: u for u in res["decisions"][m]}
            held = {u["sym"] for u in res["chosen"][m]}
            for sym in sorted(set(uni) | {s for (mm, s) in res["cm"] if mm == m}):
                r = res["cm"].get((m, sym), {})
                u = uni.get(sym, {})
                net = sum(r.get(k, 0.) for k in ("funding", "basis")) - r.get("fees", 0.) - r.get("slippage", 0.)
                rows.append(dict(strategy=mode, month=f"{m:%Y-%m}", symbol=sym, rank=u.get("rank", ""),
                                 score_ann=round(u["score"], 6) if u else "", selected=int(sym in held),
                                 funding=round(r.get("funding", 0.), 4), basis=round(r.get("basis", 0.), 4),
                                 fees=round(r.get("fees", 0.), 4), slippage=round(r.get("slippage", 0.), 4),
                                 net=round(net, 4), liquidated=r.get("liquidated", 0), delisted=r.get("delisted", 0)))
    return rows


def plots(runs, out, cash_eq):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    d0 = runs["top10"]["d0"]
    xs = [date.fromordinal(EPOCH.toordinal() + d0 + k) for k in range(len(runs["top10"]["eq"]))]
    fig, ax = plt.subplots(figsize=(10, 5))
    for name, c in (("top10", "#1f6feb"), ("ew40", "#d9822b")):
        ax.plot(xs, runs[name]["eq"], label={"top10": "Top-10 carry", "ew40": "Equal-weight 40"}[name], color=c)
    ax.plot(xs, np.full(len(xs), CAPITAL), label="Cash (0%)", color="#888")
    ax.plot(xs, cash_eq, label="Cash at 4% simple", color="#888", ls="--")
    ax.set_title("Cross-sectional funding carry, historical simulation, start 10,000 USDT")
    ax.set_ylabel("Equity (USDT)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(out / "equity-curves.png", dpi=130)
    plt.close(fig)
    res = runs["top10"]
    eq = np.concatenate([[CAPITAL], res["eq"]])
    mat = np.full((6, 12), np.nan)
    for m in months(FIRST, LAST):
        k0, k1 = dnum(m) - d0, dnum(next_month(m)) - d0
        mat[m.year - 2021, m.month - 1] = (eq[k1] / eq[k0] - 1) * 100
    fig, ax = plt.subplots(figsize=(9, 4))
    lim = np.nanmax(np.abs(mat))
    im = ax.imshow(mat, cmap="RdBu", vmin=-lim, vmax=lim, aspect="auto")
    ax.set_xticks(range(12), list("JFMAMJJASOND"))
    ax.set_yticks(range(6), range(2021, 2027))
    for (y, x), v in np.ndenumerate(mat):
        if not np.isnan(v):
            ax.text(x, y, f"{v:.1f}", ha="center", va="center", fontsize=7)
    fig.colorbar(im, label="Monthly return (%)")
    ax.set_title("Top-10 carry monthly net return, historical simulation")
    fig.tight_layout()
    fig.savefig(out / "monthly-returns.png", dpi=130)
    plt.close(fig)
    ms = months(FIRST, LAST)
    count = {}
    for m in ms:
        for u in res["chosen"][m]:
            count[u["sym"]] = count.get(u["sym"], 0) + 1
    top = sorted(count, key=lambda s: (-count[s], s))[:25]
    sc = np.full((len(top), len(ms)), np.nan)
    for j, m in enumerate(ms):
        for u in res["decisions"][m]:
            if u["sym"] in top:
                sc[top.index(u["sym"]), j] = u["score"] * 100
    fig, ax = plt.subplots(figsize=(13, 7))
    im = ax.imshow(sc, cmap="RdBu_r", vmin=-100, vmax=100, aspect="auto")
    ax.set_yticks(range(len(top)), [s[:-4] for s in top], fontsize=7)
    ax.set_xticks(range(0, len(ms), 6), [f"{m:%Y-%m}" for m in ms[::6]], fontsize=7, rotation=60)
    fig.colorbar(im, label="Prior-30-day funding, annualised (%), clipped at 100")
    ax.set_title("Funding heatmap: 25 most-selected coins, score at each monthly decision (blank = not in universe)")
    fig.tight_layout()
    fig.savefig(out / "funding-heatmap.png", dpi=130)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--skip-download", action="store_true")
    a = ap.parse_args()
    syms = universe_symbols()
    print(f"{len(syms)} USDT symbols on both legs", flush=True)
    if not a.skip_download:
        print(f"{download(syms, a.workers)} files", flush=True)
    base = dnum(date(2020, 12, 1))
    n = dnum(next_month(LAST)) - base
    data = load(syms, base, n)
    mons = months(FIRST, LAST)
    out, runs = evaluate(data, base, n, mons)
    sizes = [len(runs["top10"]["decisions"][m]) for m in mons]
    held = [len(runs["top10"]["chosen"][m]) for m in mons]
    out["coverage"] = dict(symbols_listed=len(syms), symbols_with_data=len(data), months=len(mons),
                           mean_universe=float(np.mean(sizes)), min_universe=int(min(sizes)),
                           mean_top10_held=float(np.mean(held)), months_no_top10=int(sum(h == 0 for h in held)),
                           coins_ever_held=len({u["sym"] for m in mons for u in runs["top10"]["chosen"][m]}))
    OUT.mkdir(parents=True, exist_ok=True)
    save_json(OUT / "results.json", out)
    write_csv(OUT / "months.csv", ledger_rows(runs))
    plots(runs, OUT, cash_result(runs["top10"]["d0"], len(runs["top10"]["eq"]), .04)["eq"])
    t, e = out["strategies"]["top10"], out["strategies"]["ew40"]
    print("PASS" if out["pass"] else "no established edge", t["full"]["net_usdt"], e["full"]["net_usdt"], flush=True)


if __name__ == "__main__":
    main()
