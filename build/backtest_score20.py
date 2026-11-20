#!/usr/bin/env python3
"""The home page's top 10 tested over about 20 years, with and without extra filters. Run on GitHub Actions.

Usage: python3 build/backtest_score20.py WD     (writes WD/score_bt.json; prints a summary)

Reuses the 20-year price panel from backtest_20y.py (NSE daily files from 2006, split-adjusted, delisted stocks kept).

What is copied from the page (index.html + build/build.py):
- Universe: the 300 most-traded stocks (60-day median turnover, price >= Rs 10, a year of history), above their 200-day average.
- Score = weighted average of parts scored 0-100. Momentum: percentile of 12-month return skipping the last month,
  divided by 6-month volatility. Trend: build.py's trend score. Seasonality: shrunk average excess return in the coming
  calendar month in earlier years (4+ years needed). Swing setup: breakout 90, tight base 80, pullback 72, else 45/30/8.
  Company results and news have no history here, so they count as 50 for every stock, as the page does for missing
  parts; that leaves the ranking to the price parts.
- On the last trading day of each month, hold the 10 best-scoring stocks in equal amounts from the next open; sell what
  drops out. 0.15% cost each side. No stop-loss.

Filters tested on top:
- Sector limit: at most 2 stocks from one industry (NSE's industry list; stocks no longer listed have no industry and
  are not limited).
- Near the 52-week high: only stocks within 10% of their 52-week high.
- Market filter: hold cash while an equal-weight index of the 300 most-traded stocks is below its 200-day average.
"""
import os, sys, json, subprocess
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('SKIP_DL', '1')
from backtest_20y import (WD, O, H, L, C, V, TO, LIQ, mq, s200, ret, bret, dates, n, START, ISME, PERIODS, idx, sim, stats, bench)

f32 = lambda x: x.astype('float32')
print('building score parts', flush=True)
s50 = C.rolling(50, min_periods=40).mean(); e20 = C.ewm(span=20, adjust=False, ignore_na=True).mean()
dl = C.diff(); up_ = dl.clip(lower=0).ewm(alpha=1/14, adjust=False, ignore_na=True).mean(); dn_ = (-dl.clip(upper=0)).ewm(alpha=1/14, adjust=False, ignore_na=True).mean()
rsi = 100 - 100 / (1 + up_ / dn_)
macd = C.ewm(span=12, adjust=False, ignore_na=True).mean() - C.ewm(span=26, adjust=False, ignore_na=True).mean(); mh = macd - macd.ewm(span=9, adjust=False, ignore_na=True).mean()
hi52 = H.rolling(250, min_periods=200).max(); off = (C / hi52 - 1) * 100
U = (TO.rolling(20, min_periods=15).median() >= 200) & (C >= 10)
base = U & s200.notna() & off.notna()
mom = (C.pct_change(126, fill_method=None).where(base).rank(axis=1, pct=True) + C.pct_change(63, fill_method=None).where(base).rank(axis=1, pct=True)) / 2
volr = V.rolling(20).mean() / V.rolling(60).mean()
ts = 20 * (C > s200) + 12 * (s50 > s200) + 8 * (s200 > s200.shift(20)) + 10 * (C > s50) + 5 * (C > e20)
ts = ts + np.where((rsi >= 50) & (rsi <= 70), 10, np.where(rsi > 70, 6, np.where(rsi >= 40, 4, 0))) + 6 * (mh > 0) + 4 * (mh > mh.shift()) + 15 * mom.fillna(0) \
     + np.where(off > -10, 7, np.where(off > -20, 4, 0)) + 3 * (volr > 1)
TREND_S = f32(ts)
FMOM = f32(mq.rank(axis=1, pct=True) * 100)
# swing setups (build.py)
vol50 = V.rolling(50, min_periods=40).mean(); r126 = C.pct_change(126, fill_method=None); upt = (C > s200) & (s50 > s200)
PULL = base & upt & (s200 > s200.shift(20)) & ((C / e20 - 1).abs() < 0.02) & (rsi >= 40) & (rsi <= 55) & (r126 > 0)
BRK = base & (C > s200) & (C >= C.rolling(50, min_periods=50).max()) & (V > 1.5 * vol50)
TIGHT = base & upt & (C > s50) & (off > -8) & ((H.rolling(15).max() / L.rolling(15).min() - 1) < 0.10)
SW = np.where(BRK.rolling(3, min_periods=1).max().fillna(0).astype(bool), 90, np.where(TIGHT, 80, np.where(PULL, 72, np.where((C > s50) & (s50 > s200), 45, np.where(C > s200, 30, 8)))))
FSW = pd.DataFrame(SW, index=dates, columns=C.columns).astype('float32')
# seasonality, decided at each month-end for the coming calendar month, from earlier years only
CM = C.resample('ME').last(); UM = U.resample('ME').last().shift(1).fillna(False).astype(bool)
MRm = CM.pct_change(fill_method=None).clip(-0.6, 1.5).where(UM).iloc[1:]
MX = MRm.sub(MRm.median(axis=1), axis=0)
FS = np.full((n, len(C.columns)), np.nan)
me_days = [dates[i] for i in range(n) if ISME[i]]
for d in me_days:
    nxt = (d + pd.offsets.MonthBegin(1)).month
    prior = MX[(MX.index <= d) & (MX.index.month == nxt)]
    cnt = prior.count(); avg = prior.mean()
    tx = (avg * cnt / (cnt + 3)).where(cnt >= 4)
    FS[dates.get_loc(d)] = (tx.where(LIQ.loc[d]).rank(pct=True) * 100).reindex(C.columns).values.astype('float64')
FSEAS = pd.DataFrame(FS, index=dates, columns=C.columns)
print('score parts ready', flush=True)

ELIG = LIQ & (C > s200)
def score(w):
    tw = sum(w.values()) + 25  # company results 15 + news 10 (balanced) count as 50 everywhere: constant
    s = (w['mom'] * FMOM.fillna(50) + w['trend'] * TREND_S.fillna(50) + w['seas'] * FSEAS.fillna(50) + w['swing'] * FSW.fillna(50)) / sum(w.values())
    return s.where(ELIG)

# industries
SEC = {}
try:
    subprocess.run(['curl', '-s', '-m', '40', '-A', 'Mozilla/5.0', '-o', f'{WD}/tm.csv', 'https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv'])
    SEC = pd.read_csv(f'{WD}/tm.csv').set_index('Symbol').Industry.to_dict()
except Exception as e: print('industry list skipped', e)
print('industries known for', sum(1 for s in C.columns if s in SEC), 'of', len(C.columns), 'symbols', flush=True)
secv = np.array([SEC.get(s, '_' + s) for s in C.columns])

def capped(P, k=2, N=10):
    A = P.values.astype('float64').copy()
    for i in range(n):
        if not ISME[i]: continue
        row = A[i]; ok = np.isfinite(row)
        if not ok.any(): continue
        order = np.argsort(-np.where(ok, row, -np.inf))[:ok.sum()]
        keep, cnt = [], {}
        for j in order:
            s_ = secv[j]
            if cnt.get(s_, 0) >= k: continue
            cnt[s_] = cnt.get(s_, 0) + 1; keep.append(j)
            if len(keep) >= N: break
        nr = np.full_like(row, np.nan); nr[keep] = row[keep]; A[i] = nr
    return pd.DataFrame(A, index=P.index, columns=P.columns)

bidx = (1 + bret).cumprod(); TREND = (bidx > bidx.rolling(200, min_periods=150).mean()).values
NEAR = off > -10

def run(P, filt=None):
    kw = dict(target=None, stop=None, days=None, maxpos=10, rebalance=10, filt=filt)
    e, tr, _ = sim(None, P, **kw); s = stats(e, tr)
    pp = []
    for lab, a_, b_ in PERIODS:
        lo, hi = max(START, idx(a_)), min(n - 1, idx(b_) - 1 if idx(b_) < n else n - 1)
        if hi - lo < 100: continue
        pp.append(stats(sim(None, P, lo=lo, hi=hi, **kw)[0])['cagr'])
    s['periods'] = pp
    return s, e

if __name__ == '__main__':
    out = dict(built=pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%MZ'), start=str(dates[START].date()), end=str(dates[-1].date()), periods=[p[0] for p in PERIODS])
    be = bench(); out['bench'] = stats(be); out['bench']['periods'] = [stats(bench(max(START, idx(a_)), min(n - 1, idx(b_) - 1 if idx(b_) < n else n - 1)))['cagr'] for _, a_, b_ in PERIODS]
    print(f"\nMARKET (300 most-traded, equal weight): {out['bench']['cagr']}% a year, worst fall {out['bench']['dd']}% | periods {out['bench']['periods']}")
    SCORES = {
        'Momentum rank only (12-1 month, volatility-adjusted)': (-mq.rank(axis=1, ascending=False)).where(ELIG),
        'Balanced score (price parts)': score(dict(mom=35, trend=20, seas=15, swing=5)),
        'Momentum style score (price parts)': score(dict(mom=60, trend=25, seas=5, swing=0)),
    }
    res = {}; curves = {}
    for nm, P in SCORES.items():
        variants = [('as on the page', P, None), ('+ at most 2 per industry', capped(P), None), ('+ within 10% of the 52-week high', P.where(NEAR), None),
                    ('+ cash when the market is below its 200-day average', P, TREND),
                    ('+ 2 per industry + 52-week high', capped(P.where(NEAR)), None),
                    ('+ 2 per industry + market filter', capped(P), TREND),
                    ('+ all three', capped(P.where(NEAR)), TREND)]
        for vn, PP, fl in variants:
            k = f'{nm} {vn}'
            s, e = run(PP, fl); res[k] = s
            if vn in ('as on the page', '+ all three', '+ 2 per industry + market filter'): curves[k] = e
            print(f"{k:105s} {s['cagr']:6.1f}% worst {s['dd']:6.1f}% sharpe {s['sharpe']:.2f} | periods {s['periods']}", flush=True)
    out['results'] = res
    # by year for the main candidates
    print('\nBY YEAR')
    for k in curves: print(f"{k[:90]:90s}", res[k]['years'])
    print(f"{'market':90s}", out['bench']['years'])
    wk = be.resample('W-FRI').last().dropna()
    out['curve'] = dict(dates=[f"{x:%Y-%m-%d}" for x in wk.index], bench=[round(float(v) * 100, 2) for v in wk.values],
                        **{k: [round(float(v) * 100, 2) for v in e.reindex(wk.index, method='ffill').values] for k, e in curves.items()})
    json.dump(out, open(f'{WD}/score_bt.json', 'w'), separators=(',', ':'), default=float)
    print('\nwrote score_bt.json')
