"""Post-hoc checks on the frozen trend rule: nearby parameters, and the same rule on coins it was not designed on."""
import itertools
import json

import numpy as np

import trend as T
from flow_data import save_json

OTHERS = {"BNBUSDT": (2018, 1), "XRPUSDT": (2018, 6), "ADAUSDT": (2018, 5), "LTCUSDT": (2018, 1),
          "LINKUSDT": (2019, 2), "DOGEUSDT": (2019, 8), "SOLUSDT": (2020, 9)}
GRID = dict(looks=[(10, 30, 60), (20, 60, 120), (40, 120, 240)], target=[.25, .40, .60], band=[.05, .10, .20])


def run(o, c, looks, target, band, rule="trend"):
    T.LOOKS, T.TARGET_VOL = looks, target
    T.WARM = max(looks) + T.VOL_WIN
    w = T.targets(c, rule)
    s = T.simulate(o, c, w, band=band)
    return s, T.stats(s, s["first"] - 1)


def frozen():
    return (20, 60, 120), .40, .10


def main():
    out = dict(note="Post-hoc diagnostics. The rule in trend-plan.md was fixed before these runs and is not changed by them.",
               grid={}, other_coins={})
    for sym in T.COINS:
        a = T.load(sym)
        o, c = a[:, 1], a[:, 4]
        rows = []
        for looks, target, band in itertools.product(*GRID.values()):
            _, st = run(o, c, looks, target, band)
            rows.append(dict(looks=list(looks), target=target, band=band, sharpe=st["sharpe"], cagr=st["cagr"],
                             maxdd=st["maxdd"], fees=st["fees"]))
        _, bh = run(o, c, (20, 60, 120), .40, .10, "bh")
        sh = [r["sharpe"] for r in rows]
        out["grid"][sym] = dict(bh_sharpe=bh["sharpe"], runs=rows, sharpe_min=min(sh), sharpe_median=float(np.median(sh)),
                                share_beating_bh=float(np.mean([s > bh["sharpe"] for s in sh])))
        print(sym, "grid sharpe min/median/max", round(min(sh), 2), round(float(np.median(sh)), 2), round(max(sh), 2),
              "bh", round(bh["sharpe"], 2), flush=True)
    for sym, first in OTHERS.items():
        a = T.load(sym, first, T.LAST)
        o, c = a[:, 1], a[:, 4]
        sims = {k: run(o, c, *frozen(), k) for k in T.RULES}
        f = sims["trend"][0]["first"]
        rets = {k: s["eq"][f:] / s["eq"][f - 1:-1] - 1 for k, (s, _) in sims.items()}
        out["other_coins"][sym] = dict(first_trade=T.day(a[f, 0]).isoformat(),
                                       **{k: {m: st[m] for m in ("cagr", "sharpe", "maxdd", "invested", "fees", "final")}
                                          for k, (_, st) in sims.items()},
                                       sharpe_diff_vs_bh=T.bootstrap(rets["trend"], rets["bh"]))
        r = out["other_coins"][sym]
        print(sym, "trend", round(r["trend"]["sharpe"], 2), "bh", round(r["bh"]["sharpe"], 2),
              "maxdd", round(r["trend"]["maxdd"], 2), round(r["bh"]["maxdd"], 2),
              "CI", round(r["sharpe_diff_vs_bh"]["lo"], 2), round(r["sharpe_diff_vs_bh"]["hi"], 2), flush=True)
    out["basket"] = basket()
    save_json(T.OUT / "robustness.json", out)


def basket(start=(2020, 9)):
    """Equal-weight, daily-rebalanced basket of all nine coins from the first month every coin trades."""
    rets = {k: [] for k in T.RULES}
    for sym in (*T.COINS, *OTHERS):
        a = T.load(sym, start, T.LAST)
        o, c = a[:, 1], a[:, 4]
        for k in T.RULES:
            s, _ = run(o, c, *frozen(), k)
            rets[k].append(s["eq"][1:] / s["eq"][:-1] - 1)
    n = min(len(r) - np.isnan(r).sum() for r in rets["trend"])
    pool = {k: np.nanmean([r[-n:] for r in v], axis=0) for k, v in rets.items()}
    res = {k: dict(sharpe=T.sharpe(r), cagr=float(np.prod(1 + r) ** (365 / n) - 1),
                   maxdd=float((np.cumprod(1 + r) / np.maximum.accumulate(np.cumprod(1 + r)) - 1).min()))
           for k, r in pool.items()}
    res["days"] = int(n)
    res["sharpe_diff_vs_bh"] = T.bootstrap(pool["trend"], pool["bh"])
    res["sharpe_diff_vs_vt"] = T.bootstrap(pool["trend"], pool["vt"])
    print("basket", json.dumps(res, indent=1), flush=True)
    return res


if __name__ == "__main__":
    main()
