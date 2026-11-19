#!/usr/bin/env python3
"""The site's rule tested over about 20 years of NSE prices (2006 onward), run on GitHub Actions.

Usage: python3 build/backtest_20y.py WD        (writes WD/long_bt.json; prints a summary)

Data: NSE daily equity bhavcopy files. Old format (cmDDMONYYYYbhav.csv.zip, archives.nseindia.com/content/historical/
EQUITIES/...) up to the start of the 5-year cache, then the sec_bhavdata_full files the nightly job already keeps in
WD/bhav. Series EQ only; ETFs and similar removed. Every stock that traded on a day is included, so companies that
later delisted or went bust are in the test up to their last trading day (no survivorship bias).
Splits, bonuses and rights: NSE publishes an adjusted previous close on ex-dates, so the adjustment factor on each
day is yesterday's close divided by today's PREVCLOSE (applied when it differs by more than 3%). Real crashes are kept.

Rule tested (same as the site): each evening, stocks that have just entered the top 50 of the 300 most-traded
stocks by 12-month momentum (return from 12 months to 1 month ago, divided by 6-month volatility; price >= Rs 10,
a year of history), not in the top 50 in the 20 trading days before; buy at the next open, strongest first, at most
5 at a time with 1/5 of equity each; sell at +20% or -8% (gaps fill at the open; stop assumed first if both touched)
or at the open after 30 trading days; 0.15% cost each side.
"""
import os, sys, io, re, zipfile, time, json, itertools, subprocess, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from adjust import factors

WD = sys.argv[1]; B20 = f'{WD}/bhav20'; BH = f'{WD}/bhav'
os.makedirs(B20, exist_ok=True)
START_DL = dt.date(2006, 1, 1)
MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
HOSTS = ['https://archives.nseindia.com/', 'https://nsearchives.nseindia.com/']

def fetch_old(d):
    f = f'{B20}/{d:%Y%m%d}.csv'
    if os.path.exists(f) and os.path.getsize(f) > 2000: return 1
    if os.path.exists(f'{f}.none'): return 0
    rel = f'content/historical/EQUITIES/{d.year}/{MON[d.month-1]}/cm{d:%d}{MON[d.month-1]}{d.year}bhav.csv.zip'
    for attempt in range(3):
        for h in HOSTS:
            r = subprocess.run(['curl', '-s', '-m', '40', '-A', 'Mozilla/5.0 (X11; Linux x86_64)', '-H', 'Accept: */*', '-w', '%{http_code}', '-o', f + '.zip', h + rel], capture_output=True, text=True)
            code = r.stdout.strip()
            if code == '200' and os.path.exists(f + '.zip'):
                try:
                    with zipfile.ZipFile(f + '.zip') as z: open(f, 'wb').write(z.read(z.namelist()[0]))
                    os.remove(f + '.zip'); return 1
                except Exception: pass
            if code == '404':
                open(f'{f}.none', 'w').close()
                if os.path.exists(f + '.zip'): os.remove(f + '.zip')
                return 0
        time.sleep(2 + 3 * attempt)
    if os.path.exists(f + '.zip'): os.remove(f + '.zip')
    return 0

def load():
    # recent files from the nightly cache decide where the old format stops
    rec = sorted(x for x in os.listdir(BH) if x.endswith('.csv')) if os.path.isdir(BH) else []
    first_recent = dt.datetime.strptime(rec[0][:8], '%Y%m%d').date() if rec else dt.date.today()
    days = [START_DL + dt.timedelta(k) for k in range((first_recent - START_DL).days)]
    days = [d for d in days if d.weekday() < 5]
    t0 = time.time()
    if os.environ.get('SKIP_DL'): days = []
    with ThreadPoolExecutor(8) as ex: got = sum(ex.map(fetch_old, days))
    print(f'old-format files: {got} of {len(days)} weekdays from {START_DL} to {first_recent} ({time.time()-t0:.0f}s)', flush=True)
    if got < 100:
        for f in os.listdir(B20):
            if f.endswith('.none'): os.remove(f'{B20}/{f}')
    fr = []
    for f in sorted(os.listdir(B20)):
        if not f.endswith('.csv'): continue
        try:
            d = pd.read_csv(f'{B20}/{f}', skipinitialspace=True, encoding_errors='ignore')
            d.columns = [c.strip().upper() for c in d.columns]
            d = d[d.SERIES.astype(str).str.strip() == 'EQ']
            fr.append(pd.DataFrame(dict(SYMBOL=d.SYMBOL.astype(str).str.strip(), DATE=pd.to_datetime(d.TIMESTAMP.astype(str).str.strip(), format='%d-%b-%Y', errors='coerce'), O=d.OPEN, H=d.HIGH, L=d.LOW,
                                        C=d.CLOSE, PC=d.PREVCLOSE, V=d.TOTTRDQTY, TO=d.TOTTRDVAL / 1e5)))
        except Exception as e: print('skip', f, e)
    for f in rec:
        try:
            d = pd.read_csv(f'{BH}/{f}', skipinitialspace=True, encoding_errors='ignore')
            d.columns = [c.strip() for c in d.columns]
            d = d[d.SERIES.astype(str).str.strip() == 'EQ']
            fr.append(pd.DataFrame(dict(SYMBOL=d.SYMBOL.astype(str).str.strip(), DATE=pd.to_datetime(d.DATE1.astype(str).str.strip(), format='%d-%b-%Y', errors='coerce'), O=d.OPEN_PRICE, H=d.HIGH_PRICE,
                                        L=d.LOW_PRICE, C=d.CLOSE_PRICE, PC=d.PREV_CLOSE, V=d.TTL_TRD_QNTY, TO=d.TURNOVER_LACS)))
        except Exception as e: print('skip', f, e)
    a = pd.concat(fr).dropna(subset=['DATE'])
    for c in ['O', 'H', 'L', 'C', 'PC', 'V', 'TO']: a[c] = pd.to_numeric(a[c], errors='coerce')
    rx = re.compile(r'ETF|BEES|NIFTY|GOLD|SILVER|LIQUID|SENSEX|GILT|NV20|N100|NASDAQ|GSEC|CPSE|BBETF|SDL|HNGSNG|MAFANG|MON100|SML100|MID150|SMALL250|LOWVOL|MOMENTUM|ALPHA$|CASE$|ADD$|1D$|\dIETF')
    a = a[~a.SYMBOL.map(lambda s: bool(rx.search(s)))].drop_duplicates(['SYMBOL', 'DATE']).sort_values(['SYMBOL', 'DATE'])
    # corporate actions: yesterday's close / today's adjusted previous close
    a = a.reset_index(drop=True)
    a['k'] = factors(a, use_yahoo=not os.environ.get('NO_YAHOO'))
    a['f'] = a.groupby('SYMBOL').k.transform(lambda x: x[::-1].cumprod()[::-1].shift(-1).fillna(1.0))
    for c in ['O', 'H', 'L', 'C']: a[c] = a[c] / a.f
    a['V'] = a.V * a.f
    print('rows', len(a), 'symbols', a.SYMBOL.nunique(), 'adjustments', int((a.k != 1).sum()), flush=True)
    W = lambda c: a.pivot(index='DATE', columns='SYMBOL', values=c).astype('float32')
    return {c: W(c) for c in ['O', 'H', 'L', 'C', 'V', 'TO']}

P = load()
O, H, L, C, V, TO = (P[k] for k in ['O', 'H', 'L', 'C', 'V', 'TO'])
dates = C.index; n, m = C.shape
print('panel', C.shape, dates[0].date(), dates[-1].date(), flush=True)
COST = 0.0015
ret = C.pct_change(fill_method=None).clip(-0.5, 0.5)
tom = TO.rolling(60, min_periods=40).median()
LIQ = (tom.where(C >= 10).rank(axis=1, ascending=False) <= 300) & C.shift(252).notna()
mq = ((C.shift(21) / C.shift(252) - 1) / (ret.rolling(126, min_periods=100).std() * 252 ** .5)).where(LIQ)
MR = mq.rank(axis=1, ascending=False)
s200 = C.rolling(200, min_periods=150).mean()
breadth = (C > s200).where(LIQ).sum(axis=1) / LIQ.sum(axis=1).replace(0, np.nan) * 100
UP = (breadth > breadth.rolling(50, min_periods=20).mean()).values
Ov, Hv, Lv, Cv = O.values, H.values, L.values, C.ffill(limit=10).values
START = int(np.argmax(LIQ.sum(axis=1).values >= 250)) + 5
bret = ret.where(LIQ.shift(1).fillna(False)).mean(axis=1).fillna(0)
me = set(pd.Series(dates, index=dates).groupby([dates.year, dates.month]).last().values)
ISME = np.array([d_ in me for d_ in dates])

def fresh(cond, k=20):
    return cond & ~(cond.rolling(k, min_periods=1).max().shift(1).fillna(0).astype(bool))

def sim(entry, prio, target=None, stop=.08, days=30, maxpos=5, lo=None, hi=None, mood=False, rebalance=None):
    lo = START if lo is None else lo; hi = n - 1 if hi is None else hi
    Ev = None if entry is None else entry.reindex(index=dates, columns=C.columns).fillna(False).values
    Pv = prio.reindex(index=dates, columns=C.columns).values
    cash, pos, eq, trades, pend, eqv, why = 1.0, {}, [], [], [], 1.0, []
    for i in range(lo, hi + 1):
        for j in list(pos):
            p = pos[j]; o, l, h = Ov[i, j], Lv[i, j], Hv[i, j]
            px = r = None
            if not np.isfinite(Cv[i, j]) and i > p['bi']: px, r = p.get('lc', p['e']), 'gone'
            elif p.get('sell_open') and np.isfinite(o): px, r = o, 'time'
            elif stop and i > p['bi'] and np.isfinite(o) and o <= p['stop']: px, r = o, 'stop'
            elif stop and np.isfinite(l) and l <= p['stop']: px, r = p['stop'], 'stop'
            elif target and i > p['bi'] and np.isfinite(o) and o >= p['tgt']: px, r = o, 'target'
            elif target and np.isfinite(h) and h >= p['tgt']: px, r = p['tgt'], 'target'
            if px is not None:
                cash += p['sh'] * px * (1 - COST); trades.append(px / p['e'] - 1 - 2 * COST); why.append(r); del pos[j]
        if pend:
            for j in pend:
                if len(pos) >= maxpos: break
                o = Ov[i, j]
                if j in pos or not np.isfinite(o) or o <= 0: continue
                val = min(cash, eqv / maxpos)
                if val < eqv / maxpos * 0.5: break
                cash -= val
                pos[j] = dict(e=o, sh=val / (o * (1 + COST)), bi=i, stop=o * (1 - (stop or 1)), tgt=o * (1 + (target or 9)))
        for j, p in pos.items():
            if np.isfinite(Cv[i, j]): p['lc'] = Cv[i, j]
        eqv = cash + sum(p['sh'] * p.get('lc', p['e']) for p in pos.values())
        eq.append(eqv)
        pend = []
        if rebalance:
            if ISME[i]:
                pr = Pv[i]; ok = np.isfinite(pr)
                tgt = set(np.argsort(-np.where(ok, pr, -np.inf))[:rebalance][:ok.sum()])
                for j, p in pos.items():
                    if j not in tgt: p['sell_open'] = True
                pend = [j for j in tgt if j not in pos]
            continue
        for j, p in pos.items():
            if days and i - p['bi'] + 1 >= days: p['sell_open'] = True
        if (not mood) or UP[i]:
            sg = np.nonzero(Ev[i])[0]
            if len(sg):
                sg = sg[np.argsort(-np.nan_to_num(Pv[i, sg], nan=-1e9))]
                pend = [j for j in sg if j not in pos]
    return pd.Series(eq, index=dates[lo:hi + 1]), np.array(trades), why

def stats(e, tr=np.array([])):
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    cagr = e.iloc[-1] ** (1 / yrs) - 1 if yrs > 0.2 else e.iloc[-1] - 1; dd = (e / e.cummax() - 1).min()
    r = e.pct_change().dropna(); sh = r.mean() / r.std() * 252 ** .5 if r.std() > 0 else 0
    by = {int(y): round((g.iloc[-1] / (e[e.index < g.index[0]].iloc[-1] if (e.index < g.index[0]).any() else 1.0) - 1) * 100, 1) for y, g in e.groupby(e.index.year)}
    return dict(cagr=round(cagr * 100, 1), dd=round(dd * 100, 1), sharpe=round(float(sh), 2), trades=int(len(tr)),
                win=round(float((tr > 0).mean()) * 100, 1) if len(tr) else None, avg=round(float(tr.mean()) * 100, 2) if len(tr) else None, years=by)

def bench(lo=None, hi=None):
    lo = START if lo is None else lo; hi = n - 1 if hi is None else hi
    return (1 + bret.iloc[lo:hi + 1]).cumprod()

PERIODS = [('2007-2010 (incl. the 2008 crash)', '2007-01-01', '2010-12-31'), ('2011-2015', '2011-01-01', '2015-12-31'),
           ('2016-2020 (incl. the 2020 crash)', '2016-01-01', '2020-12-31'), ('2021-2026', '2021-01-01', '2026-12-31')]
def idx(d): return int(dates.searchsorted(pd.Timestamp(d)))

if __name__ == '__main__':
    F50 = fresh(MR <= 50); PR = -MR
    out = dict(built=pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%MZ'), start=str(dates[START].date()), end=str(dates[-1].date()), files=int(len(dates)))
    be = bench(); out['bench'] = stats(be)
    e, tr, why = sim(F50, PR, .20, .08, 30, 5); s = stats(e, tr)
    s['why'] = pd.Series(why).value_counts(normalize=True).mul(100).round(1).to_dict()
    out['rule'] = s
    print(f"\nBENCHMARK (300 most-traded, equal weight) {out['bench']['cagr']}% a year, worst fall {out['bench']['dd']}%")
    print(f"SITE RULE {s['cagr']}% a year, worst fall {s['dd']}%, sharpe {s['sharpe']}, {s['trades']} trades, win {s['win']}%, avg {s['avg']}%, exits {s['why']}")
    print('years rule ', s['years']); print('years bench', out['bench']['years'], flush=True)
    per = []
    for lab, a_, b_ in PERIODS:
        lo, hi = max(START, idx(a_)), min(n - 1, idx(b_) - 1 if idx(b_) < n else n - 1)
        if hi - lo < 100: continue
        er, trr, _ = sim(F50, PR, .20, .08, 30, 5, lo=lo, hi=hi); sr = stats(er, trr); sb = stats(bench(lo, hi))
        per.append(dict(period=lab, rule=sr['cagr'], rule_dd=sr['dd'], bench=sb['cagr'], bench_dd=sb['dd']))
        print(f"{lab:36s} rule {sr['cagr']:6.1f}% (worst {sr['dd']}%)  market {sb['cagr']:6.1f}% (worst {sb['dd']}%)", flush=True)
    out['periods'] = per
    em, trm, _ = sim(F50, PR, .20, .08, 30, 5, mood=True); out['mood'] = stats(em, trm)
    print('with mood filter', out['mood']['cagr'], out['mood']['dd'])
    # robustness grid over the whole 20 years
    grid = []
    for tg, sp, dy, mp in itertools.product([None, .10, .15, .20, .30], [.05, .08, .10, .15], [20, 30, 40], [5, 10]):
        e2, t2, _ = sim(F50, PR, tg, sp, dy, mp); s2 = stats(e2, t2)
        grid.append(dict(target=tg, stop=sp, days=dy, maxpos=mp, cagr=s2['cagr'], dd=s2['dd'], sharpe=s2['sharpe']))
    g = pd.DataFrame(grid); out['grid'] = grid
    print('\nGRID over 20 years (target x stop, 30 days, 5 at a time):')
    print(g[(g.days == 30) & (g.maxpos == 5)].assign(t=lambda x: x.target.fillna(0)).pivot(index='t', columns='stop', values='cagr').to_string())
    print('best 10 settings:'); print(g.sort_values('cagr', ascending=False).head(10).to_string())
    print('median of all settings', g.cagr.median(), 'share beating market', round((g.cagr > out['bench']['cagr']).mean() * 100))
    # other approaches over the same 20 years
    others = {}
    hi250 = C.rolling(250, min_periods=200).max(); vol50 = V.rolling(50, min_periods=40).mean(); s50 = C.rolling(50, min_periods=40).mean()
    e20 = C.ewm(span=20, adjust=False).mean(); r126 = C.pct_change(126, fill_method=None)
    hi30p = H.rolling(30).max().shift(1); lo30p = L.rolling(30).min().shift(1)
    up_tr = LIQ & (C > s200) & (s50 > s200)
    tests = {
        'Monthly top 5 by momentum, no stop': (None, PR, dict(target=None, stop=None, days=None, maxpos=5, rebalance=5)),
        'Monthly top 10 by momentum, no stop': (None, PR, dict(target=None, stop=None, days=None, maxpos=10, rebalance=10)),
        'Newly in the momentum top 30, 20% / 10%, 21 days': (fresh(MR <= 30), PR, dict(target=.2, stop=.1, days=21, maxpos=5)),
        'Breakout to a 52-week high on 1.5x volume, 20% / 8%, 30 days': (LIQ & (C >= hi250) & (V > 1.5 * vol50), V / vol50, dict(target=.2, stop=.08, days=30, maxpos=5)),
        'Base breakout (30-day range < 15%) on 1.5x volume, 20% / 8%, 20 days': (LIQ & (C > s200) & ((hi30p / lo30p - 1) < .15) & (C > hi30p) & (V > 1.5 * vol50), V / vol50, dict(target=.2, stop=.08, days=20, maxpos=5)),
        'Pullback to the 20-day average in an uptrend, then a bounce, 20% / 5%, 30 days': (up_tr & (L.rolling(3).min() <= e20 * 1.01) & (C > H.shift(1)) & (C > e20), r126, dict(target=.2, stop=.05, days=30, maxpos=5)),
    }
    for k_, (en, pr, kw) in tests.items():
        e3, t3, _ = sim(en, pr, **kw); s3 = stats(e3, t3)
        pp = []
        for lab, a_, b_ in PERIODS:
            lo, hi = max(START, idx(a_)), min(n - 1, idx(b_) - 1 if idx(b_) < n else n - 1)
            if hi - lo < 100: continue
            pp.append(stats(sim(en, pr, lo=lo, hi=hi, **kw)[0])['cagr'])
        others[k_] = dict(s3, periods=pp)
        print(f"{k_:80s} {s3['cagr']:6.1f}% worst {s3['dd']:6.1f}% | periods {pp}", flush=True)
    out['others'] = others
    # walk-forward contest: each idea's settings chosen on 2007-2016, then checked on 2017-2026
    MID = idx('2017-01-01')
    if MID - START > 500:
        rng_ = H - L; nr7 = rng_ <= rng_.rolling(7).min(); r63 = C.pct_change(63, fill_method=None)
        macd = C.ewm(span=12, adjust=False).mean() - C.ewm(span=26, adjust=False).mean(); sgl = macd.ewm(span=9, adjust=False).mean()
        sd20 = C.rolling(20).std(); ma20 = C.rolling(20).mean(); bwd = 4 * sd20 / ma20; bwlow = bwd <= bwd.rolling(120, min_periods=100).min() * 1.1
        rk = lambda x, top: x.where(LIQ).rank(axis=1, ascending=False) <= top
        IDEAS = {
          "12-month momentum: newly in the top 50 (this site's rule)": (F50, PR),
          '12-month momentum: newly in the top 30': (fresh(MR <= 30), PR),
          '6-month momentum: newly in the top 30': (fresh(rk(r126 / ret.rolling(126, min_periods=100).std(), 30)), r126),
          '3-month momentum: newly in the top 30': (fresh(rk(r63, 30)), r63),
          'Near the 52-week high, strongest 3-month gain, newly in the top 30': (fresh(rk(r63.where(C >= .95 * hi250), 30)), r63),
          'First new 52-week high in a month, above-average volume': (fresh(LIQ & (C >= hi250), 20) & (V > vol50), r126),
          'Pullback to the 20-day average in an uptrend, then a bounce': (up_tr & (L.rolling(3).min() <= e20 * 1.01) & (C > H.shift(1)) & (C > e20), r126),
          'Pullback in a momentum leader (top 50), then a bounce': (up_tr & (MR <= 50) & (L.rolling(3).min() <= e20 * 1.01) & (C > H.shift(1)) & (C > e20), PR),
          'Base breakout: 30-day range under 15%, 1.5x volume': (LIQ & (C > s200) & ((hi30p / lo30p - 1) < .15) & (C > hi30p) & (V > 1.5 * vol50), V / vol50),
          'NR7 day in an uptrend, then a close above its high': (up_tr & nr7.shift(1).fillna(False) & (C > H.shift(1)), r126),
          'MACD crosses up above zero, above 200-day': (LIQ & (C > s200) & (macd > sgl) & (macd.shift(1) <= sgl.shift(1)) & (macd > 0), r126),
          'Bollinger squeeze breakout': (LIQ & (C > s200) & bwlow.shift(1).fillna(False) & (C > ma20 + 2 * sd20), V / vol50),
          'Golden cross: 50-day crosses above 200-day': (LIQ & (s50 > s200) & (s50.shift(1) <= s200.shift(1)), r63),
        }
        bT, bS = stats(bench(START, MID - 1)), stats(bench(MID, n - 1))
        print(f"\nWALK-FORWARD: settings chosen on {dates[START].date()}..2016, checked on 2017..{dates[-1].date()}. Market: {bT['cagr']}% then {bS['cagr']}%", flush=True)
        wf = {}
        for k_, (en, pr) in IDEAS.items():
            rows = []
            for tg, sp, dy, mp in itertools.product([None, .10, .20, .30], [.05, .08, .12], [20, 30, 40], [5, 10]):
                s_ = stats(sim(en, pr, tg, sp, dy, mp, hi=MID - 1)[0]); rows.append((s_['sharpe'], s_['cagr'], tg, sp, dy, mp))
            rows.sort(key=lambda r: (-r[0], -r[1])); sh, cg, tg, sp, dy, mp = rows[0]
            et, tt, _ = sim(en, pr, tg, sp, dy, mp, lo=MID); st_ = stats(et, tt)
            t10 = [stats(sim(en, pr, r[2], r[3], r[4], r[5], lo=MID)[0])['cagr'] for r in rows[:5]]
            wf[k_] = dict(target=tg, stop=sp, days=dy, maxpos=mp, train=cg, test=st_['cagr'], test_dd=st_['dd'], test_top5_median=float(np.median(t10)))
            print(f"{k_:70s} pick T{tg} S{sp} D{dy} N{mp} | 2007-16 {cg:6.1f}% | 2017-26 {st_['cagr']:6.1f}% (worst {st_['dd']}%) | top-5 settings median {np.median(t10):.1f}%", flush=True)
        out['walkforward'] = dict(train_bench=bT['cagr'], test_bench=bS['cagr'], ideas=wf)
    wk = e.resample('W-FRI').last().dropna(); bw = be.reindex(wk.index, method='ffill')
    out['curve'] = dict(dates=[f"{x:%Y-%m-%d}" for x in wk.index], rule=[round(float(v) * 100, 2) for v in wk.values], bench=[round(float(v) * 100, 2) for v in bw.values])
    json.dump(out, open(f'{WD}/long_bt.json', 'w'), separators=(',', ':'), default=float)
    print('\nwrote long_bt.json')
