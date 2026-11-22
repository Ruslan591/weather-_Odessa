import json,collections,statistics as S,datetime as D
d=json.load(open("/opt/trading-bot/positions_regr/shadow.json"))["items"]
START=int(D.datetime(2026,11,20,0,0,41,tzinfo=D.UTC).timestamp()*1000)
def f(t): return D.datetime.fromtimestamp(t/1000,D.UTC).strftime("%d %H:%M")
rows=[]
for x in d:
    if x.get("var") not in ("A",None): continue
    p=x.get("p")
    if p and p.get("legacy"): continue
    if x.get("status")=="closed" and p and p.get("r_mult") is not None: pp=p;src="in"
    elif x.get("status")=="filtered" and x.get("cf") and x["cf"].get("r_mult") is not None: pp=x["cf"];src="cf"
    else: continue
    if pp["t_in"]<START: continue
    o=x.get("o0") or {}
    atr=o.get("atr"); px=pp["entry"]
    atrp=atr/px*100 if atr and px else None
    rg=x.get("rg") or {}
    plan=x.get("plan") or {}
    R0=pp["R"]
    slip=((pp["entry"]-plan["entry"])/R0*(1 if x["side"]=="long" else -1)) if plan.get("entry") else None
    rows.append(dict(sn=x.get("sn"),tf=x["tf"],kind=x["kind"],side=x["side"],src=src,reg=rg.get("regime"),raw=rg.get("raw"),st=rg.get("strength"),
      delay=(pp["t_in"]-(x.get("t_sig") or pp["t_in"]))/60000, rpct=pp["R_pct"], atrp=atrp, riskatr=(pp["R_pct"]/atrp if atrp else None), slip=slip,
      mfe=pp["mfe_pct"]/pp["R_pct"], mae=pp["mae_pct"]/pp["R_pct"], r=pp["r_mult"], reason=pp.get("reason"), t=pp["t_in"], tp=abs(pp["tp"]-pp["entry"])/R0, why=(x.get("why") or "")[:0]))
print("rows",len(rows))
print("tf  src n  | medMFE medMAE | medR_pct riskATR medDelayMin medSlipR | sumR")
for tf in ("5m","15m","1h","4h","1d"):
    for src in ("in","cf"):
        v=[q for q in rows if q["tf"]==tf and q["src"]==src]
        if not v: continue
        g=lambda k:[q[k] for q in v if q[k] is not None]
        print("%-3s %-2s %2d | %.2f %.2f | %.2f %.2f %.1f %.2f | %.2f"%(tf,src,len(v),S.median(g("mfe")),S.median(g("mae")),S.median(g("rpct")),S.median(g("riskatr")) if g("riskatr") else 0,S.median(g("delay")),S.median(g("slip")) if g("slip") else 0,sum(q["r"] for q in v)))
print("--- all non-5m rows")
for q in sorted([q for q in rows if q["tf"]!="5m"],key=lambda q:q["t"]):
    print("#%s %s %s %s %s %s/%s str=%.2f in=%s delay=%.1fm rpct=%.2f riskATR=%.2f slip=%.2f mfe=%.2f mae=%.2f tpR=%.1f -> %s %.2f"%(q["sn"],q["tf"],q["kind"][:2],q["side"][0],q["src"],q["reg"],q["raw"],q["st"] or 0,f(q["t"]),q["delay"],q["rpct"],q["riskatr"] or 0,q["slip"] or 0,q["mfe"],q["mae"],q["tp"],q["reason"],q["r"]))
# 5m reference MFE/MAE share
for tf in ("5m","15m"):
    v=[q for q in rows if q["tf"]==tf]
    print(tf,"share mfe<0.3R: %.0f%% ; mfe>=1R: %.0f%% ; mae>=1R: %.0f%%"%(100*sum(1 for q in v if q["mfe"]<0.3)/len(v),100*sum(1 for q in v if q["mfe"]>=1)/len(v),100*sum(1 for q in v if q["mae"]>=1)/len(v)))
