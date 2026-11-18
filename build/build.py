#!/usr/bin/env python3
"""Rebuild data.json for the NSE Stock Screener. Usage: python3 build.py <workdir>
Writes <workdir>/data.json (prices, indicators, signals, market breadth). Static parts of the site live in static.json.
Needs pandas, numpy and network access to archives.nseindia.com. About 5 years of daily files are kept in <workdir>/bhav (cached between runs by the workflow)."""
import sys, os, re, json, subprocess, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import pandas as pd, numpy as np
WD=sys.argv[1]; BH=os.path.join(WD,'bhav'); os.makedirs(BH,exist_ok=True)
A='https://archives.nseindia.com/'
def curl(u,f,t=40): subprocess.run(['curl','-s','-m',str(t),'-A','Mozilla/5.0','-o',f,u])
def get(d):
    f=f"{BH}/{d:%Y%m%d}.csv"
    if os.path.exists(f) and os.path.getsize(f)>10000: return 1
    curl(f"{A}products/content/sec_bhavdata_full_{d:%d%m%Y}.csv",f)
    ok=os.path.exists(f) and os.path.getsize(f)>10000 and not open(f,'rb').read(200).lstrip().startswith(b'<')
    if not ok and os.path.exists(f): os.remove(f)
    return int(ok)
today=dt.date.today(); days=[today-dt.timedelta(k) for k in range(0,1900)]; days=[d for d in days if d.weekday()<5]
with ThreadPoolExecutor(12) as ex: got=sum(ex.map(get,days))
for nm,u in[('n50','content/indices/ind_nifty50list.csv'),('n500','content/indices/ind_nifty500list.csv'),('tm','content/indices/ind_niftytotalmarket_list.csv'),('eql','content/equities/EQUITY_L.csv'),('etf','content/equities/eq_etfseclist.csv')]: curl(A+u,f"{WD}/{nm}.csv")
fr=[]
for f in sorted(os.listdir(BH)):
    try: d=pd.read_csv(f"{BH}/{f}",skipinitialspace=True,usecols=['SYMBOL','SERIES','DATE1','OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY','TURNOVER_LACS','DELIV_PER'])
    except Exception: continue
    fr.append(d[d.SERIES=='EQ'])
a=pd.concat(fr).drop_duplicates(['SYMBOL','DATE1']); a['DATE1']=pd.to_datetime(a.DATE1,format='%d-%b-%Y')
cols=['OPEN_PRICE','HIGH_PRICE','LOW_PRICE','CLOSE_PRICE','TTL_TRD_QNTY','TURNOVER_LACS']
for c in cols+['DELIV_PER']: a[c]=pd.to_numeric(a[c],errors='coerce').astype(float)
try: etf=set(pd.read_csv(f"{WD}/etf.csv",skipinitialspace=True).iloc[:,0].astype(str).str.strip())
except Exception: etf=set()
rx=re.compile(r'ETF|BEES|NIFTY|GOLD|SILVER|LIQUID|SENSEX|GILT|NV20|N100|NASDAQ|GSEC|CPSE|BBETF|SDL|HNGSNG|MAFANG|MON100|SML100|MID150|SMALL250|LOWVOL|MOMENTUM|ALPHA$|CASE$|ADD$|1D$|\dIETF')
a=a[~a.SYMBOL.isin(etf)&~a.SYMBOL.map(lambda s:bool(rx.search(s)))].sort_values(['SYMBOL','DATE1'])
r=a.CLOSE_PRICE/a.groupby('SYMBOL').CLOSE_PRICE.shift(); STD=np.array([1.25,4/3,1.5,2,2.5,3,4,5,6,10,11])
def snap(x):
    if not x<0.75: return 1.0
    j=STD[np.argmin(np.abs(1/STD-x))]; return float(j) if abs(1/j-x)/x<0.06 else 1/x
a['k']=r.map(snap); a['f']=a.groupby('SYMBOL').k.transform(lambda x:x[::-1].cumprod()[::-1].shift(-1).fillna(1.0))
ADJ={}
for s,dte,k in a.loc[a.k!=1,['SYMBOL','DATE1','k']].itertuples(index=False):
    std=np.min(np.abs(STD-k))<1e-9; ADJ.setdefault(s,[]).append(f"{dte:%d %b %Y} ÷{k:.3g}"+('' if std else ' (non-standard, possible demerger or crash)'))
for c in cols[:4]: a[c]/=a.f
a['TTL_TRD_QNTY']*=a.f
W=lambda c:a.pivot(index='DATE1',columns='SYMBOL',values=c)
O,H,L,C,V,TO=[W(c) for c in cols]; n=len(C); asof=C.index[-1]
dv20=W('DELIV_PER').rolling(20,min_periods=10).mean().iloc[-1]
DEALS={}
for kind in('bulk','block'):
    try:
        curl(A+f'content/equities/{kind}.csv',f"{WD}/{kind}.csv"); q=pd.read_csv(f"{WD}/{kind}.csv",skipinitialspace=True); q.columns=[c.strip() for c in q.columns]
        q['d']=pd.to_datetime(q['Date'],format='%d-%b-%Y',errors='coerce'); q=q[q.d==asof]
        for _,r_ in q.iterrows():
            DEALS.setdefault(str(r_['Symbol']).strip(),[]).append(dict(kind=kind,who=str(r_['Client Name']).strip()[:60],side=str(r_['Buy/Sell']).strip().upper(),qty=float(str(r_['Quantity Traded']).replace(',','')),px=float(str(r_['Trade Price / Wght. Avg. Price']).replace(',',''))))
    except Exception as e: print('deals',kind,'skipped',e)
U=(TO.rolling(20,min_periods=15).median()>=200)&(C>=10)
s50=C.rolling(50).mean(); s200=C.rolling(200).mean(); e20=C.ewm(span=20,adjust=False,ignore_na=True).mean()
dl=C.diff(); up_=dl.clip(lower=0).ewm(alpha=1/14,adjust=False,ignore_na=True).mean(); dn_=(-dl.clip(upper=0)).ewm(alpha=1/14,adjust=False,ignore_na=True).mean(); rsi=100-100/(1+up_/dn_)
macd=C.ewm(span=12,adjust=False,ignore_na=True).mean()-C.ewm(span=26,adjust=False,ignore_na=True).mean(); sg=macd.ewm(span=9,adjust=False,ignore_na=True).mean(); mh=macd-sg
pc=C.shift(); atr=np.maximum(H-L,np.maximum((H-pc).abs(),(L-pc).abs())).ewm(alpha=1/14,adjust=False,ignore_na=True).mean()
hi52=H.rolling(250,min_periods=200).max(); lo52=L.rolling(250,min_periods=200).min(); off=(C/hi52-1)*100
base=U&s200.notna()&off.notna()
mom=(C.pct_change(126,fill_method=None).where(base).rank(axis=1,pct=True)+C.pct_change(63,fill_method=None).where(base).rank(axis=1,pct=True))/2
breadth=((C>s200)&base).sum(axis=1)/base.sum(axis=1)*100; bavg=breadth.rolling(50).mean(); rising=bool(breadth.iloc[-1]>bavg.iloc[-1])
volr=V.rolling(20).mean()/V.rolling(60).mean(); ret=C.pct_change(fill_method=None).clip(-0.5,0.5)
tom=TO.rolling(60,min_periods=40).median().iloc[-1]; m121=(C.shift(21)/C.shift(252)-1).iloc[-1]; vol=(ret.rolling(126,min_periods=100).std()*252**.5).iloc[-1]
liq=tom.where(C.iloc[-1]>=10).nlargest(300).index; sc=(m121/vol)[liq].dropna().sort_values(ascending=False); rank={s:i+1 for i,s in enumerate(sc.index)}; liqs=set(liq)
ts=20*(C>s200)+12*(s50>s200)+8*(s200>s200.shift(20))+10*(C>s50)+5*(C>e20)
ts=ts+np.where((rsi>=50)&(rsi<=70),10,np.where(rsi>70,6,np.where(rsi>=40,4,0)))+6*(mh>0)+4*(mh>mh.shift())+15*mom.fillna(0)+np.where(off>-10,7,np.where(off>-20,4,0))+3*(volr>1)
el=pd.read_csv(f"{WD}/eql.csv",skipinitialspace=True).set_index('SYMBOL')['NAME OF COMPANY'].to_dict()
tm=pd.read_csv(f"{WD}/tm.csv").set_index('Symbol').Industry.to_dict(); n50=set(pd.read_csv(f"{WD}/n50.csv").Symbol); n500=set(pd.read_csv(f"{WD}/n500.csv").Symbol)
cnt=C.notna().sum(); L1=lambda X:X.iloc[-1]; last_e20=e20.iloc[-1]
last={k:L1(v) for k,v in dict(c=C,s50=s50,s200=s200,rsi=rsi,macd=macd,sig=sg,mh=mh,atr=atr,hi52=hi52,lo52=lo52,off=off,volr=volr,mom=mom,ts=ts).items()}
med20=TO.iloc[-20:].median()/100; prev=C.iloc[-2]; s200p=s200.iloc[-21]
f4=lambda x: None if x is None or not np.isfinite(x) else (float(f"{x:.4g}") if abs(x)<1000 else round(float(x),1))
r2=lambda x: None if x is None or not np.isfinite(x) else round(float(x),2)
def rt(s,k): 
    v=C[s].iloc[-1-k] if n>k else np.nan
    return r2((last['c'][s]/v-1)*100) if np.isfinite(v) else None
stocks=[]
for s in C.columns:
    c=last['c'][s]
    if not np.isfinite(c) or cnt[s]<220 or s not in el or not med20[s]>=2 or c<10 or not np.isfinite(last['s200'][s]) or not np.isfinite(last['hi52'][s]): continue
    r=rank.get(s); a_=last['atr'][s]
    if r and r<=30: sig,why=('BUY','In the Momentum 30 model portfolio and market breadth is rising') if rising else ('WAIT','In the Momentum 30 but market breadth is falling; the gated model is in cash')
    elif c>last['s200'][s]: sig='WAIT'; why=(f"Ranked {r} of {len(sc)} on momentum; the model holds only the top 30" if r else ('Among the 300 most-traded stocks but has under a year of history' if s in liqs else 'Above its 200-day average but outside the 300 most-traded stocks, so not covered by the tested model'))
    else: sig,why='AVOID','Below its 200-day average: downtrend'
    x=dict(sym=s,name=el[s],sector=tm.get(s,'Not classified'),idx='Nifty 50' if s in n50 else 'Nifty 500' if s in n500 else 'Other',close=r2(c),chg=r2((c/prev[s]-1)*100),
      s50=r2(last['s50'][s]),s200=r2(last['s200'][s]),rsi=r2(last['rsi'][s]),macd=r2(last['macd'][s]),sig=r2(last['sig'][s]),mh=r2(last['mh'][s]),atr=r2(a_),
      hi52=r2(last['hi52'][s]),lo52=r2(last['lo52'][s]),offHigh=r2(last['off'][s]),r1m=rt(s,21),r3m=rt(s,63),r6m=rt(s,126),r12m=rt(s,250),volr=r2(last['volr'][s]),
      s200up=bool(last['s200'][s]>s200p[s]),to=r2(med20[s]),adj=ADJ.get(s,[]),px=[f4(v) for v in C[s].iloc[-120:]],p50=[f4(v) for v in s50[s].iloc[-120:].iloc[::-5].iloc[::-1]],p200=[f4(v) for v in s200[s].iloc[-120:].iloc[::-5].iloc[::-1]],
      mom=r2(last['mom'][s]*100) if np.isfinite(last['mom'][s]) else 0,tscore=r2(last['ts'][s]),signal=sig,why=why,entry=r2(c),stop=r2(c-2*a_),target=None,riskPct=r2(2*a_/c*100),
      mrank=r,liq300=s in liqs,deliv=r2(dv20[s]) if s in dv20 else None,deals=DEALS.get(s,[]),m121=r2(m121[s]*100) if s in m121 else None,vol=r2(vol[s]*100) if s in vol else None)
    stocks.append(x)

# ---------- Agent factors: momentum for every stock, seasonality, swing setups, and evidence tests ----------
SYMS=[x['sym'] for x in stocks]
mq=(m121/vol).reindex(SYMS); mq=mq.where(np.isfinite(mq)); mscore=(mq.rank(pct=True)*100)
# Seasonality: complete calendar months only; excess = stock's month return minus the median liquid stock that month
CM=C.resample('ME').last(); UM=U.resample('ME').last().shift(1).fillna(False).astype(bool)
MR=CM.pct_change(fill_method=None).clip(-0.6,1.5).where(UM).iloc[1:-1]
MX=MR.sub(MR.median(axis=1),axis=0)
tmon=(asof+pd.Timedelta(days=14)).month
SEAS={}
for s_ in SYMS:
    r_=MR[s_] if s_ in MR else None
    if r_ is None: continue
    av=[];nn=[];hit=[]
    for m_ in range(1,13):
        q_=r_[r_.index.month==m_].dropna(); x_=MX[s_][MX.index.month==m_].dropna()
        av.append(r2(q_.mean()*100) if len(q_) else None); nn.append(int(len(q_))); hit.append(int((q_>0).sum()))
    xm=MX[s_][MX.index.month==tmon].dropna()
    SEAS[s_]=dict(avg=av,n=nn,up=hit,tx=(float(xm.mean()*len(xm)/(len(xm)+3)) if len(xm)>=4 else None))
tx=pd.Series({k:v['tx'] for k,v in SEAS.items()},dtype=float); sscore=tx.rank(pct=True)*100
# Seasonality evidence: each month, pick the top 10% by their average excess in that calendar month in earlier years (2+ years), measure next month
sev=[]
for i,t in enumerate(MX.index):
    prior=MX.iloc[:i]; prior=prior[prior.index.month==t.month]
    if len(prior)<2: continue
    sig_=prior.mean().where(prior.count()>=2).dropna(); now=MX.loc[t]
    sig_=sig_[now.reindex(sig_.index).notna()]
    if len(sig_)<100: continue
    top=sig_[sig_>=sig_.quantile(0.9)].index; bot=sig_[sig_<=sig_.quantile(0.1)].index
    sev.append(dict(m=f"{t:%Y-%m}",top=float(now[top].mean()*100),bot=float(now[bot].mean()*100)))
sev=pd.DataFrame(sev)
# Swing setups
vol50=V.rolling(50,min_periods=40).mean(); r126=C.pct_change(126,fill_method=None)
up=(C>s200)&(s50>s200)
PULL=base&up&(s200>s200.shift(20))&((C/e20-1).abs()<0.02)&(rsi>=40)&(rsi<=55)&(r126>0)
BRK=base&(C>s200)&(C>=C.rolling(50,min_periods=50).max())&(V>1.5*vol50)
TIGHT=base&up&(C>s50)&(off>-8)&((H.rolling(15).max()/L.rolling(15).min()-1)<0.10)
f20=C.shift(-20)/C-1; f20x=f20.sub(f20.where(base).mean(axis=1),axis=0)
def evid(M,label,how):
    e=f20x.where(M&f20x.notna()).stack().dropna()
    if not len(e): return dict(label=label,how=how,n=0)
    yrs={int(y):r2(g.mean()*100) for y,g in e.groupby(e.index.get_level_values(0).year)}
    return dict(label=label,how=how,n=int(len(e)),avg=r2(e.mean()*100),hit=r2((e>0).mean()*100),years=yrs)
top30=pd.DataFrame(False,index=C.index,columns=C.columns)
EV=dict(asof=f"{asof:%d %b %Y}",start=f"{C.index[0]:%b %Y}",
  setups=[evid(BRK,'Breakout','New 50-day closing high on 1.5× normal volume, above the 200-day average'),
          evid(TIGHT,'Tight base','In an uptrend, within 8% of the 52-week high, last 15 days in a range under 10%'),
          evid(PULL,'Pullback','Uptrend, price back within 2% of the 20-day EMA, RSI 40–55')],
  seas=dict(months=int(len(sev)),top=r2(sev.top.mean()) if len(sev) else None,bot=r2(sev.bot.mean()) if len(sev) else None,
            beat=int((sev.top>sev.bot).sum()) if len(sev) else 0,target=int(tmon)))
recent=lambda M,k:M.iloc[-k:].any()
SET={}
for s_ in SYMS:
    if recent(BRK,3).get(s_,False): SET[s_]=('Breakout',90)
    elif TIGHT.iloc[-1].get(s_,False): SET[s_]=('Tight base',80)
    elif PULL.iloc[-1].get(s_,False): SET[s_]=('Pullback',72)
for x in stocks:
    s_=x['sym']; sp=SET.get(s_)
    x['setup']=sp[0] if sp else None
    x['fSwing']=sp[1] if sp else (45 if (x['close']>x['s50']>x['s200']) else 30 if x['close']>x['s200'] else 8)
    x['fMom']=r2(mscore.get(s_)) if pd.notna(mscore.get(s_,np.nan)) else None
    x['fSeas']=r2(sscore.get(s_)) if pd.notna(sscore.get(s_,np.nan)) else None
    x['seas']=SEAS.get(s_)
    if x['seas']: x['seas'].pop('tx',None)
    x['e20']=r2(last_e20[s_]) if np.isfinite(last_e20[s_]) else None
b=breadth.iloc[-120:]
bt=dict(breadth=[r2(v) for v in b],bavg=[r2(v) for v in bavg.iloc[-120:]],rising=rising,bnow=round(float(breadth.iloc[-1]),1),nrank=len(sc))
SC={}; scasof=None
fp=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','fundamentals.csv')
if os.path.exists(fp):
    try:
        q=pd.read_csv(fp); norm=lambda c: re.sub(r'[^a-z0-9]','',str(c).lower()); cm={norm(c):c for c in q.columns}
        def col(*pats):
            for p in pats:
                for k,c in cm.items():
                    if re.search(p,k): return c
        M=dict(sym=col(r'^nsecode$',r'^symbol$',r'^nsesymbol$'),mcap=col(r'^marketcap'),pe=col(r'^pricetoearning',r'^pe$'),roe=col(r'^returnonequity',r'^roe'),roce=col(r'^returnoncapital',r'^roce'),de=col(r'^debttoequity'),s3=col(r'^salesgrowth3'),p3=col(r'^profitgrowth3'),npg=col(r'^yoyquarterlyprofit'),sg=col(r'^yoyquarterlysales'),prom=col(r'^promoterholding'),promc=col(r'^changeinpromoter'),pledge=col(r'^pledged'),fii=col(r'^fiiholding'),fiic=col(r'^changeinfii'),dii=col(r'^diiholding'),diic=col(r'^changeindii'))
        def num(r_,k):
            if not M.get(k): return None
            v=pd.to_numeric(r_[M[k]],errors='coerce'); return float(v) if pd.notna(v) else None
        if M['sym']:
            for _,r_ in q.iterrows():
                s=str(r_[M['sym']]).strip().upper()
                if not s or s=='NAN': continue
                d={k:num(r_,k) for k in('mcap','pe','roe','roce','de','s3','p3','npg','sg','pledge')}
                for k,ck in(('prom','promc'),('fii','fiic'),('dii','diic')):
                    v=num(r_,k); c_=num(r_,ck); d[k]=None if v is None else [round(v-(c_ or 0),2),v]
                SC[s]=d
            try: scasof=dt.datetime.strptime(subprocess.run(['git','log','-1','--format=%cs','--','fundamentals.csv'],capture_output=True,text=True,cwd=os.path.dirname(fp)).stdout.strip(),'%Y-%m-%d').strftime('%d %b %Y')
            except Exception: scasof=f"{asof:%d %b %Y}"
        else: print('fundamentals.csv skipped: no "NSE Code" or "Symbol" column')
    except Exception as e: print('fundamentals.csv skipped:',e)
out=dict(sc=SC,scAsof=scasof,asof=f"{asof:%d %b %Y}",built=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),dates=[f"{d:%Y-%m-%d}" for d in C.index[-120:]],stocks=stocks,bt=bt,ev=EV,tmon=int(tmon))
if os.environ.get('DUMP'): pd.to_pickle(dict(C=C,H=H,L=L,V=V,TO=TO,U=U,s50=s50,s200=s200,e20=e20,rsi=rsi,off=off,ts=ts,BRK=BRK,TIGHT=TIGHT,PULL=PULL,MR=MR,MX=MX,breadth=breadth,bavg=bavg),f"{WD}/mats.pkl")
json.dump(out,open(f"{WD}/data.json",'w'),separators=(',',':'),ensure_ascii=False)
buys=sorted([x for x in stocks if x['mrank'] and x['mrank']<=30],key=lambda x:x['mrank'])
print(json.dumps(dict(fundamentals=len(SC),files=got,days=n,asof=out['asof'],stocks=len(stocks),buy=sum(x['signal']=='BUY' for x in stocks),rising=rising,breadth=bt['bnow'],top5=[x['sym'] for x in buys[:5]])))
