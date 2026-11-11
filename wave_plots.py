"""Static heatmaps for the development run, from observed values only."""
import csv
from datetime import datetime,timezone
import io
from pathlib import Path
from urllib.request import Request,urlopen
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT=Path("data/aahil-wave")
REPORT=Path("research/aahil-wave")


def font(size):
    for name in ("DejaVuSans.ttf","arial.ttf"):
        try:
            return ImageFont.truetype(name,size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def records(path):
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def color(frac):
    anchor=np.asarray([[242,247,246],[143,207,191],[14,102,100],[14,43,64]])
    p=min(2.999,max(0.,3*frac));i=int(p)
    return tuple((anchor[i]*(1-(p-i))+anchor[i+1]*(p-i)).astype(int))


def panel(draw,bounds,values,xlabels,ylabels,title,sub,counts=None,digits=2):
    left,top,right,bottom=bounds
    draw.text((left,top),title,fill="#172a39",font=font(22))
    draw.text((left,top+33),sub,fill="#394654",font=font(15))
    x0=left+125; y0=top+72
    a=np.asarray(values)
    nr,nc=a.shape; cw=(right-x0)/nc; ch=(bottom-y0)/nr
    finite=a[np.isfinite(a)]
    lo=min(finite) if len(finite) else 0
    hi=max(finite) if len(finite) else 1
    for i,y in enumerate(ylabels):
        draw.text((x0-8,y0+(i+.5)*ch),str(y),anchor="rm",font=font(14),fill="#233443")
        for j,x in enumerate(xlabels):
            if i==nr-1:
                draw.text((x0+(j+.5)*cw,bottom+9),str(x),anchor="mt",font=font(13),fill="#233443")
            v=a[i,j]
            present=bool(np.isfinite(v))
            frac=(v-lo)/max(1e-10,hi-lo) if present else 0
            draw.rectangle((x0+j*cw,y0+i*ch,x0+(j+1)*cw-1,y0+(i+1)*ch-1),
                           fill=color(frac) if present else "#e5e7e9")
            if present:
                value=f"{v:.{digits}f}" if counts is None else str(int(counts[i,j]))
                draw.text((x0+(j+.5)*cw,y0+(i+.5)*ch),value,anchor="mm",
                          font=font(12),fill="white" if frac>.52 else "#10252c")
    draw.text((left,bottom+33),f"Light to dark: {lo:.3f} to {hi:.3f}    Grey: no observations",
              font=font(13),fill="#455661")


def plot_policy():
    pred=records(OUT/"predictions.csv")
    ledger=records(REPORT/"wave-orders.csv")
    im=Image.new("RGB",(1500,980),"white");draw=ImageDraw.Draw(im)
    draw.text((40,22),"Aahil Wave   /   2025 development folds",font=font(29),fill="#19333b")
    g=np.zeros((7,24)); n=np.zeros_like(g)
    for r in ledger:
        if r["status"]!="filled":
            continue
        d=datetime.fromtimestamp(int(r["decision"]),timezone.utc)
        k=(d.weekday(),d.hour);n[k]+=1;g[k]+=float(r["net_r"])
    panel(draw,(30,85,735,428),np.divide(g,n,out=np.full_like(g,np.nan),where=n>0),range(24),
          ("Mon","Tue","Wed","Thu","Fri","Sat","Sun"),"Net R per fill by decision time",
          "UTC hour across columns. Cell text counts fills.",n)
    a=np.array([[float(r[k]) for k in ("offset_bps","atr_frac","fill","p_fill","ev","r")] for r in pred])
    g=np.zeros((4,4));n=np.zeros_like(g)
    for off,vol,f,*_ in a:
        k=(np.searchsorted([.001,.002,.004],vol),np.searchsorted([3,6,12],off))
        n[k]+=1;g[k]+=f
    panel(draw,(770,85,1465,428),np.divide(g,n,out=np.full_like(g,np.nan),where=n>0),
          ["≤3","3–6","6–12",">12"],["≤10","10–20","20–40",">40"],"Observed standalone fill fractions",
          "Rows: five-minute ATR (bp). Columns: entry offset (bp).")
    cuts=(0,.025,.05,.075,.10); minimum=(0,.3,.5,.7,.9)
    v=np.full((5,5),np.nan)
    for i,p in enumerate(minimum):
        for j,e in enumerate(cuts):
            keep=(a[:,3]>=p)&(a[:,4]>e)
            if keep.any():
                v[i,j]=a[keep,5].mean()
    panel(draw,(30,530,735,896),v,cuts,minimum,"Threshold sensitivity",
          "Mean net R per proposal. Rows: minimum P(fill). Columns: EV floor.")
    shap=[r for r in records(REPORT/"shap.csv") if r["role"]=="direction"]
    keys=sorted({x["feature"] for x in shap},key=lambda k:-sum(float(x["mean_abs_shap"]) for x in shap if x["feature"]==k))[:10]
    vals=[[float(next(x["mean_abs_shap"] for x in shap if x["feature"]==k and int(x["fold"])==f)) for f in range(1,5)] for k in keys]
    panel(draw,(770,530,1465,896),vals,range(1,5),keys,"Conditional TP model · TreeSHAP",
          "Mean absolute contribution to the raw margin, by quarterly test fold.",digits=3)
    im.save(REPORT/"diagnostics.png")


def prefix(kind):
    url=f"https://datasets.tardis.dev/v1/binance-futures/{kind}/2025/01/01/BTCUSDT.csv.gz"
    with urlopen(Request(url,headers={"Range":"bytes=0-524287"}),timeout=30) as response:
        data=zlib.decompressobj(31).decompress(response.read(524288))
    return list(csv.DictReader(io.StringIO(data[:data.rfind(b"\n")].decode())))


def plot_depth():
    b,tr=prefix("book_snapshot_25"),prefix("trades")
    first=max(int(b[0]["timestamp"]),int(tr[0]["timestamp"]))
    end=min(first+60_000_000,int(b[-1]["timestamp"]),int(tr[-1]["timestamp"]))
    if end<=first:
        raise ValueError("Nonoverlapping depth and trades")
    depths={};prices=[]
    for r in b:
        t=int(r["timestamp"])
        if first<=t<end:
            depths[int((t-first)/(end-first)*100)]=r
            prices.extend([float(r["bids[24].price"]),float(r["asks[24].price"])])
    lo,hi=min(prices),max(prices);edges=np.linspace(lo,hi,81)
    grid=np.full((80,100),np.nan)
    for j,r in depths.items():
        grid[:,j]=0
        for side in ("asks","bids"):
            for level in range(25):
                px=float(r[f"{side}[{level}].price"]);idx=min(79,max(0,np.searchsorted(edges,px)-1))
                grid[idx,j]+=float(r[f"{side}[{level}].amount"])*px
    im=Image.new("RGB",(1300,560),"white");draw=ImageDraw.Draw(im)
    draw.text((45,20),"BTCUSDT perpetual   /   Visible depth and executed trades",font=font(27),fill="#19333b")
    draw.text((45,62),"Top 25 levels per side. Depth shades show log(1 + displayed USDT). Orange dots: taker buys. Blue dots: taker sells.",
              font=font(16),fill="#354b54")
    x0,y0,w,h=110,110,1140,350
    logged=np.log1p(grid);peak=np.nanmax(logged)
    for (i,j),v in np.ndenumerate(logged):
        draw.rectangle((x0+w*j/100,y0+h*(79-i)/80,x0+w*(j+1)/100,y0+h*(80-i)/80),
                       fill=color(v/peak) if np.isfinite(v) else "#e5e7e9")
    for r in tr:
        t=int(r["timestamp"]);price=float(r["price"])
        if first<=t<end and lo<=price<=hi:
            x=x0+w*(t-first)/(end-first);y=y0+h*(hi-price)/(hi-lo)
            rad=min(5,max(1.5,3*float(r["amount"])**.5))
            draw.ellipse((x-rad,y-rad,x+rad,y+rad),fill="#e55e24" if r["side"]=="buy" else "#3873f3")
    for j in range(6):
        draw.text((x0+w*j/5,y0+h+10),f"{(end-first)/1e6*j/5:.1f}",font=font(14),anchor="mt",fill="#172a39")
        draw.text((x0-6,y0+h*j/5),f"{hi-(hi-lo)*j/5:.1f}",font=font(14),anchor="rm",fill="#172a39")
    draw.text((x0,y0+h+46),"Seconds since "+datetime.fromtimestamp(first/1e6,timezone.utc).isoformat(timespec="milliseconds")+"   ·   Price in USDT",
              font=font(17),fill="#172a39")
    im.save(REPORT/"depth-trades.png")


if __name__=="__main__":
    plot_policy()
    plot_depth()
