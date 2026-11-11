"""Pooled, causal Wave 5 candidate research. Times are UTC Unix seconds."""
import csv
from bisect import bisect_left
from datetime import date, datetime, timezone
import json
from statistics import median

import numpy as np
from sklearn.linear_model import LogisticRegression
from xgboost import XGBClassifier

from backtest import FEE, SLIP
from flow_data import ROOT, epoch
from perp_market import load_market
from perp_orders import Order, HOLD_BARS, net_r, resolve, trade_pnl
from quote_replay import QUOTE_TTL_BARS
from wave_inputs import COINS, END, FIRST, OUT, months, next_month

FAMILIES = {
    "price": ["side","atr_frac","offset_atr","ret_1h","ret_1d"],
    "wave": ["w2_retrace","w3_extension","w4_retrace","fib_w2","fib_w4","wave_age","w4_overlap"],
    "cvd": ["signed_volume_1h"],
    "carry": ["last_rate","spot_basis"],
    "lead": ["btc_lag_return"],
    "ofi": ["ofi"],
    "micro": ["microprice_bps"],
    "oi": ["oi_change"],
    "liquidation": ["liquidation_delta"],
}
MAIN = ("price","wave","cvd","carry","lead")
MIN_EV = .05
GAP = 86400
HORIZON = (QUOTE_TTL_BARS+HOLD_BARS)*300


def names(families):
    return [n for f in families for n in FAMILIES[f]] + ["is_"+c for c in COINS]


def pivot_sequence(closes, reversal):
    """Pivot (index, price, sign, confirmation index), based on closed observations only."""
    trend, high, low = 0, 0, 0
    pivots = []
    for i,x in enumerate(closes):
        if trend >= 0:
            if x >= closes[high]:
                high = i
            elif closes[high]-x >= reversal[i]:
                pivots.append((high,closes[high],1,i))
                low, trend = i,-1
                continue
        if trend <= 0:
            if x <= closes[low]:
                low = i
            elif x-closes[low] >= reversal[i]:
                pivots.append((low,closes[low],-1,i))
                high, trend = i,1
    return pivots


def indicators(bars):
    close = np.asarray([b.close for b in bars])
    prev = np.r_[close[0],close[:-1]]
    tr = np.maximum([b.high for b in bars],prev)-np.minimum([b.low for b in bars],prev)
    atr = np.convolve(tr,np.ones(14)/14,mode="full")[:len(close)]
    return close,atr


def geometry(side, price, atr):
    entry = price-side*.5*atr
    distance = max(2*atr,4*(2*FEE+SLIP)*entry)
    stop, target = entry-side*distance, entry+side*1.5*distance
    if min(entry,stop,target,distance)<=0:
        raise ValueError("invalid prices")
    return Order(side,entry,stop,target,-trade_pnl(side,entry,stop*(1-side*SLIP)))


def candidate(c, bars, i, close, atr, btc_lag, spot, rate):
    """Compute a setup from 72 hours of confirmed five-minute bars ending at i-1."""
    if i < 865 or min(atr[i-1],spot)<=0:
        return None
    base = i-864
    pivots = pivot_sequence(close[base:i],2*atr[base:i])
    if len(pivots)<5:
        return None
    a,b,p,d,e = pivots[-5:]
    side = -e[2]
    first = side*(b[1]-a[1])
    third = side*(d[1]-p[1])
    if min(first,third)<=0:
        return None
    w2,w4 = side*(b[1]-p[1])/first,side*(d[1]-e[1])/third
    price=close[i-1]
    order = geometry(side,price,atr[i-1])
    group=bars[i-12:i]
    quote=sum(b.quote for b in group)
    if quote<=0:
        return None
    values=dict(side=side,atr_frac=atr[i-1]/price,offset_atr=abs(price-order.entry)/atr[i-1],
                ret_1h=price/close[i-13]-1,ret_1d=price/close[i-289]-1,
                w2_retrace=w2,w3_extension=third/first,w4_retrace=w4,
                fib_w2=int(.382<=w2<=.786),fib_w4=int(.236<=w4<=.5),
                wave1_price=float(b[1]),
                wave_age=len(close[base:i])-1-e[3],w4_overlap=int(side*(e[1]-b[1])<=0),
                signed_volume_1h=2*sum(b.buy_quote for b in group)/quote-1,
                btc_lag_return=btc_lag,spot_basis=price/spot-1,last_rate=rate)
    values.update({"is_"+coin:int(c==coin) for coin in COINS})
    return values,order


def membership(markets, observation_month):
    """Use prior month volume and prior first-day spread/depth. Missing quotes exclude."""
    start,end = epoch(observation_month),epoch(next_month(observation_month))
    volumes={c:sum(b.quote for b in markets[c].bars if start<=b.time<end) for c in COINS}
    return _rank_month(observation_month,volumes)


def membership_for_month(month):
    """Load liquidity inputs for a live month using only the previous calendar month."""
    from wave_context import csv_zip
    from wave_inputs import prepare
    from datetime import timedelta
    from regime_data import rest_candles
    prior=(month.replace(day=1)-timedelta(days=1)).replace(day=1)
    volumes={}
    for c in COINS:
        prepare((c,prior))
        path=ROOT/"candles"/c/f"{prior:%Y-%m}.zip"
        quotes={int(r[0])//1000:float(r[7]) for r in csv_zip(path.read_bytes()) if r[0].isdigit()}
        expected=range(epoch(prior),epoch(next_month(prior)),300)
        missing=[t for t in expected if t not in quotes]
        if missing:
            repair=rest_candles(c,missing[0],missing[-1]+300)
            quotes.update({r[0]//1000:float(r[7]) for r in repair})
        if set(quotes)!=set(expected):
            raise ValueError(f"Incomplete liquidity-ranking month for {c}")
        volumes[c]=sum(quotes.values())
    return _rank_month(prior,volumes)


def _rank_month(observation_month,volumes):
    start,end=epoch(observation_month),epoch(next_month(observation_month))
    rows=[]
    for c in COINS:
        volume=volumes[c]
        q=json.loads((OUT/"l1"/c/f"{observation_month}.json").read_bytes())
        books=json.loads((ROOT/"depth-1-2pct"/c/f"{observation_month}.json").read_bytes())["samples"]
        depths=[min(v["bid_near"],v["ask_near"]) for v in books.values() if start<=v["observed"]<end]
        depth=median(depths) if depths else None
        spread=q["spread_bps"]
        rows.append(dict(coin=c,month=str(next_month(observation_month)),volume=volume,
                         spread_bps=spread,depth_usdt=depth,eligible=bool(depth and depth>=100000
                         and spread is not None and spread<=5 and volume>0)))
    rank=sorted((r for r in rows if r["eligible"]),key=lambda r:(-r["volume"],r["coin"]))
    for r in rows:
        r["member"]=r in rank[:3]
    return rows


def label(m,i,o):
    if o.side*(o.entry-m.bars[i+1].open)>=0:
        return i+1,False,False,0.
    outcome=resolve(m,o,i+1,entry_bars=QUOTE_TTL_BARS)
    return outcome.end,outcome.fill is not None,outcome.reason=="target",float(net_r(o,outcome))


def load_inputs():
    markets={c:load_market(c,FIRST,END,ROOT/"depth-1-2pct",include_options=False) for c in COINS}
    return markets


def events(markets):
    members=[row for m in months() if next_month(m)<END for row in membership(markets,m)]
    allowed={(r["month"],r["coin"]) for r in members if r["member"]}
    btc=np.asarray([b.close for b in markets["BTC"].bars])
    all_rows=[]
    for c,m in markets.items():
        close,atr=indicators(m.bars)
        for month in months(date(2024,1,1),END):
            if (str(month),c) not in allowed:
                continue
            data=json.loads((OUT/"context"/c/f"{month}.json").read_bytes())
            l1=json.loads((OUT/"l1"/c/f"{month}.json").read_bytes())["bars"]
            start=(epoch(month)-m.bars[0].time)//300
            stop=min(len(close)-HOLD_BARS-QUOTE_TTL_BARS,(epoch(next_month(month))-m.bars[0].time)//300)
            # Hourly grid plus first-day quotes every five minutes for the sparse matched L1 study.
            grid=set(range(start,stop,12))
            grid.update((int(t)-m.bars[0].time)//300 for t in l1)
            for i in sorted(j for j in grid if start<=j<stop):
                t=m.bars[i].time
                spot=data["spot"].get(str(t-300))
                k=bisect_left(m.funding_times,t*1000)-1
                if not spot or k<0 or t*1000-m.funding_times[k]>9*3600_000:
                    continue
                info=candidate(c,m.bars,i,close,atr,btc[i-2]/btc[i-14]-1,spot,m.funding[k].rate)
                if info is None:
                    continue
                v,o=info
                if str(t) in l1:
                    book=l1[str(t)]
                    v.update(ofi=book["ofi"]/book["liquidity"],microprice_bps=book["microprice_bps"])
                oi0,oi1=(data["oi"].get(str(t-d)) for d in (600,300))
                if oi0 and oi1:
                    v["oi_change"]=oi1/oi0-1
                if data["liq_covered"] and epoch(month)+3600<=t<=epoch(month)+86400:
                    v["liquidation_delta"]=sum(data["liquidations"].get(str(t-j*300),0.)
                                               for j in range(1,13))/sum(b.quote for b in m.bars[i-12:i])
                end,filled,tp,r=label(m,i,o)
                all_rows.append(dict(coin=c,time=t,end=m.bars[end].time+300,index=i,order=o,
                                     fill=filled,tp=tp,r=r,values=v,main=i%12==0))
    return sorted(all_rows,key=lambda a:a["time"]),members


def matrix(rows,columns):
    return np.asarray([[r["values"][c] for c in columns] for r in rows])


def fit_classifier(x,y,xcal,ycal):
    if min(len(set(y)),len(set(ycal)))<2:
        raise ValueError("Need both classes in fitting and calibration")
    tree=XGBClassifier(n_estimators=50,max_depth=2,learning_rate=.07,n_jobs=2,random_state=17)
    tree.fit(x,y)
    cal=LogisticRegression().fit(tree.predict(xcal,output_margin=True).reshape(-1,1),ycal)
    return tree,cal


def fit(rows, families):
    rows=sorted(rows,key=lambda r:r["time"])
    start_cal=rows[int(.8*len(rows))]["time"]
    train=[r for r in rows if r["end"]+GAP<start_cal]
    cal=[r for r in rows if r["time"]>=start_cal]
    cols=names(families)
    result=dict(columns=cols)
    for key,label_name in (("fill","fill"),("direction","tp")):
        a,b=train,cal
        if key=="direction":
            a=[r for r in a if r["fill"]]
            b=[r for r in b if r["fill"]]
        result[key]=fit_classifier(matrix(a,cols),[int(r[label_name]) for r in a],
                                   matrix(b,cols),[int(r[label_name]) for r in b])
    filled=[r for r in cal if r["fill"]]
    result["mean_tp"]=float(np.mean([r["r"] for r in filled if r["tp"]]))
    result["mean_other"]=float(np.mean([r["r"] for r in filled if not r["tp"]]))
    return result


def scores(model,x):
    def probability(name):
        tree,cal=model[name]
        return cal.predict_proba(tree.predict(x,output_margin=True).reshape(-1,1))[:,1]
    pf,pt=probability("fill"),probability("direction")
    ev=pf*(pt*model["mean_tp"]+(1-pt)*model["mean_other"])
    return pf,pt,ev


def score_candidate(model, values):
    x=np.asarray([[values[k] for k in model["columns"]]])
    return {k:float(v[0]) for k,v in zip(("p_fill","p_tp_given_fill","expected_net_r"),scores(model,x))}
