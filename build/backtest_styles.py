#!/usr/bin/env python3
"""Backtest the page's score styles as monthly portfolios, using only information available on each rebalance date.

Usage: DUMP=1 python3 build/build.py WD   (saves WD/mats.pkl)
       python3 build/backtest_styles.py WD  (prints results, writes WD/styles_bt.json)

Each month-end: universe = 300 most-traded NSE stocks (60-day median turnover), price >= Rs 10, a year of history.
Each style scores the universe with the page's weights for its price-based factors (fundamentals and news have no history,
so they count as neutral and do not change the order), keeps stocks above their 200-day average, buys the top 30 in equal
amounts and holds to the next month-end. Costs 0.2% per round trip on the part of the portfolio that changes.
"""
import sys, json, numpy as np, pandas as pd
WD = sys.argv[1]
M = pd.read_pickle(f'{WD}/mats.pkl')
C, TO, U, s50, s200, ts, off = M['C'], M['TO'], M['U'], M['s50'], M['s200'], M['ts'], M['off']
BRK, TIGHT, PULL, MX, breadth, bavg = M['BRK'], M['TIGHT'], M['PULL'], M['MX'], M['breadth'], M['bavg']
ret = C.pct_change(fill_method=None).clip(-0.5, 0.5)
m121 = C.shift(21) / C.shift(252) - 1
vol = ret.rolling(126, min_periods=100).std() * 252 ** .5
tom = TO.rolling(60, min_periods=40).median()
CF = C.ffill(limit=30)
dates = C.index
me = pd.Series(dates, index=dates).groupby([dates.year, dates.month]).last().values
me = [pd.Timestamp(d) for d in me if d >= dates[260]]
if me and me[-1] == dates[-1]: pass

def seas_score(t, univ, min_n):
    tm = (t + pd.Timedelta(days=14)).month
    prior = MX[(MX.index < t - pd.Timedelta(days=20)) & (MX.index.month == tm)]
    if prior.empty: return pd.Series(np.nan, index=univ)
    cnt = prior[univ].count(); mean = prior[univ].mean()
    v = (mean * cnt / (cnt + 3)).where(cnt >= min_n)
    return v.rank(pct=True) * 100

def swing_score(i, univ):
    b3 = BRK.iloc[max(0, i - 2):i + 1][univ].any()
    tg, pl = TIGHT.iloc[i][univ], PULL.iloc[i][univ]
    c, a50, a200 = C.iloc[i][univ], s50.iloc[i][univ], s200.iloc[i][univ]
    base = np.where((c > a50) & (a50 > a200), 45, np.where(c > a200, 30, 8))
    return pd.Series(np.where(b3, 90, np.where(tg, 80, np.where(pl, 72, base))), index=univ, dtype=float)

STYLES = {
 'Balanced': dict(mom=35, trend=20, seas=15, swing=5),
 'Momentum': dict(mom=60, trend=25, seas=5, swing=0),
 'Swing trade': dict(mom=20, trend=25, seas=15, swing=30),
 'Long-term (price parts only)': dict(mom=25, trend=20, seas=5, swing=0),
 'Momentum + seasonality': dict(mom=70, trend=0, seas=30, swing=0),
}

def run(min_n=4):
    books = {k: [] for k in list(STYLES) + ['Momentum 30 (the tested model)', 'Basket: 300 most-traded']}
    prev = {k: set() for k in books}
    rows = []
    for j in range(len(me) - 1):
        t, t2 = me[j], me[j + 1]; i = dates.get_loc(t)
        ok = (C.iloc[i] >= 10) & C.shift(252).iloc[i].notna() & tom.iloc[i].notna()
        univ = tom.iloc[i][ok].nlargest(300).index
        mq = (m121.iloc[i][univ] / vol.iloc[i][univ]).replace([np.inf, -np.inf], np.nan)
        f = dict(mom=mq.rank(pct=True) * 100, trend=ts.iloc[i][univ], seas=seas_score(t, univ, min_n), swing=swing_score(i, univ))
        r = (CF.loc[t2, univ] / C.loc[t, univ] - 1).fillna(0).clip(-0.9, 3)
        up = C.iloc[i][univ] > s200.iloc[i][univ]
        picks = {}
        for k, w in STYLES.items():
            sc = sum(w[x] * f[x].fillna(50) for x in w) / sum(w.values())
            picks[k] = sc[up].nlargest(30).index
        picks['Momentum 30 (the tested model)'] = mq.dropna().nlargest(30).index
        picks['Basket: 300 most-traded'] = univ
        row = dict(date=t, rising=bool(breadth.iloc[i] > bavg.iloc[i]))
        for k, p in picks.items():
            p = list(p); g = r[p].mean() if p else 0.0
            chg = len(set(p) ^ prev[k]) / 2 / max(1, len(p)) if k != 'Basket: 300 most-traded' else 0.02
            row[k] = g - chg * 0.002; prev[k] = set(p)
        rows.append(row)
    return pd.DataFrame(rows).set_index('date')

def stats(s, d):
    eq = (1 + s).cumprod(); yrs = len(s) / 12
    cagr = eq.iloc[-1] ** (1 / yrs) - 1; dd = (eq / eq.cummax() - 1).min()
    sh = s.mean() / s.std() * 12 ** .5 if s.std() > 0 else 0
    by = {int(y): round(((1 + g).prod() - 1) * 100, 1) for y, g in s.groupby(s.index.year)}
    return dict(cagr=round(cagr * 100, 1), dd=round(dd * 100, 1), sharpe=round(sh, 2), years=by)

R = run(4)
out = dict(start=str(R.index[0].date()), end=str((me[-1]).date()), months=len(R), styles={})
basket = R['Basket: 300 most-traded']
for k in R.columns:
    if k == 'rising': continue
    st = stats(R[k], R.index); st['beat'] = int((R[k] > basket).sum()) if k != 'Basket: 300 most-traded' else None
    g = R[k].where(R['rising'], 0.0); st['cautious'] = stats(g, R.index)
    out['styles'][k] = st
R3 = run(3)
out['seas_min3'] = {k: stats(R3[k], R3.index)['cagr'] for k in STYLES}
for k, v in out['styles'].items():
    print(f"{k:34s} CAGR {v['cagr']:6.1f}%  worst fall {v['dd']:6.1f}%  Sharpe {v['sharpe']:5.2f}  beat basket {v['beat']}/{out['months']}  cautious CAGR {v['cautious']['cagr']:5.1f}% dd {v['cautious']['dd']:5.1f}%  {v['years']}")
print('seasonality needing 3 years instead of 4:', out['seas_min3'])
print('window', out['start'], out['end'], out['months'], 'months')
json.dump(out, open(f'{WD}/styles_bt.json', 'w'), indent=1)
