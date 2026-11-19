#!/usr/bin/env python3
"""A fair contest between strategy families, each run as a real portfolio.

Usage: DUMP=1 python3 build/build.py WD ; python3 build/backtest_algos.py WD   (writes WD/algos_bt.json)

Same rules for every strategy: universe = the 300 most-traded NSE stocks that day (price >= Rs 10, a year of history);
at most 10 positions, each bought with 1/10 of current equity; signals are read at the close and traded at the next
open; stop-losses fill at the stop, or at the open if the price gaps through it; 0.15% cost on each side.
Settings are standard textbook values, chosen before testing, not tuned.
Also reported: each strategy taking new trades only while market breadth is rising ("mood filter"), and the two halves
of the period separately, to check the result is not one lucky stretch.
"""
import sys, json, numpy as np, pandas as pd
WD = sys.argv[1]
M = pd.read_pickle(f'{WD}/mats.pkl')
O, H, L, C, V, TO, DV = M['O'], M['H'], M['L'], M['C'], M['V'], M['TO'], M['DV']
s50, s200, rsi14, BRK = M['s50'], M['s200'], M['rsi'], M['BRK']
breadth, bavg = M['breadth'], M['bavg']
COST, MAXPOS, START = 0.0015, 10, 260
dates = C.index; n, m = C.shape
ret = C.pct_change(fill_method=None).clip(-0.5, 0.5)
tom = TO.rolling(60, min_periods=40).median()
LIQ = (tom.where(C >= 10).rank(axis=1, ascending=False) <= 300) & C.shift(252).notna()
mq = ((C.shift(21) / C.shift(252) - 1) / (ret.rolling(126, min_periods=100).std() * 252 ** .5)).where(LIQ)
MR = mq.rank(axis=1, ascending=False)
vol20 = V.rolling(20, min_periods=15).mean(); vol50 = V.rolling(50, min_periods=40).mean()
d = C.diff(); up_ = d.clip(lower=0).ewm(alpha=1/2, adjust=False).mean(); dn_ = (-d.clip(upper=0)).ewm(alpha=1/2, adjust=False).mean()
rsi2 = 100 - 100 / (1 + up_ / dn_)
sma5 = C.rolling(5).mean(); ema20 = C.ewm(span=20, adjust=False).mean()
hi250 = C.rolling(250, min_periods=200).max(); low20 = L.rolling(20).min()
dv20 = DV.rolling(20, min_periods=10).mean()
vola = ret.rolling(126, min_periods=100).std()
UP = (breadth > bavg).reindex(dates).fillna(False).values
Ov, Hv, Lv, Cv = O.values, H.values, L.values, C.ffill(limit=10).values
me = set(pd.Series(dates, index=dates).groupby([dates.year, dates.month]).last().values)
ISME = np.array([d_ in me for d_ in dates])

def strat_defs():
    in30 = MR <= 30
    fresh = in30 & ~(in30.rolling(20, min_periods=1).max().shift(1).fillna(0).astype(bool))
    S = {}
    # name: (entry signal, priority (higher first), exit spec)
    S['Momentum: fresh top-30 entry, 21 days, 10% stop'] = (fresh, -MR, dict(stop=.10, days=21))
    S['Momentum: monthly top 5, rebalance each month-end (the site\'s rule)'] = ('monthly', -MR, dict(rebalance=5, maxpos=5))
    S['Momentum: monthly top 10, rebalance each month-end'] = ('monthly', -MR, dict(rebalance=10))
    S['Momentum: monthly top 20, rebalance each month-end'] = ('monthly', -MR, dict(rebalance=20, maxpos=20))
    S['Momentum: monthly top 10 with a 10% stop-loss'] = ('monthly', -MR, dict(rebalance=10, stop=.10))
    S['Momentum: dip in a leader (top-30, RSI14 < 40), 15 days'] = (in30 & (rsi14 < 40), -MR, dict(stop=.10, days=15))
    S['Breakout: new 52-week high on 1.5x volume, exit below 20-day low'] = (LIQ & (C >= hi250) & (V > 1.5 * vol50), mq, dict(stop=.10, trail_low20=True, days=60))
    S['Breakout: 50-day high on 1.5x volume, 20% target / 10% stop, 40 days'] = (LIQ & BRK, V / vol50, dict(stop=.10, target=.20, days=40))
    S['Trend: 20-EMA crosses above 50-day, above 200-day; exit on cross down'] = (LIQ & (ema20 > s50) & (ema20.shift(1) <= s50.shift(1)) & (C > s200), mq, dict(stop=.10, cross_down=True, days=60))
    S['Mean reversion: RSI(2) < 5 above 200-day, sell above 5-day average'] = (LIQ & (rsi2 < 5) & (C > s200), -rsi2, dict(stop=.10, above_sma5=True, days=10))
    S['Reversal: biggest 5-day losers, hold 5 days'] = (LIQ & (C.pct_change(5, fill_method=None) < -0.08), -C.pct_change(5, fill_method=None), dict(stop=.10, days=5))
    S['Event drift: +6% day on 3x volume, closing near the high, 20 days'] = (LIQ & (C.pct_change(fill_method=None) > .06) & (V > 3 * vol50) & ((C - L) / (H - L) > .75), V / vol50, dict(stop=.10, days=20))
    S['Delivery surge: delivery 1.5x normal, up 2%+, above 50-day, 20 days'] = (LIQ & (DV > 1.5 * dv20) & (C.pct_change(fill_method=None) > .02) & (C > s50), DV / dv20, dict(stop=.10, days=20))
    S['Low volatility: 10 calmest stocks, monthly'] = ('monthly', -vola.where(LIQ), dict(rebalance=10))
    return S

def simulate(entry, prio, ex, mood=False, lo=START, hi=None):
    hi = hi or n - 1
    mp = ex.get('maxpos', MAXPOS)
    Pv = prio.reindex(index=dates, columns=C.columns).values
    Ev = None if isinstance(entry, str) else entry.reindex(index=dates, columns=C.columns).fillna(False).values
    cash, pos, eq, trades = 1.0, {}, [], []
    s5, e20v, s50v, l20v = sma5.values, ema20.values, s50.values, low20.values
    for i in range(lo, hi + 1):
        # 1) exits that happen during day i (stops) or at its open (decided at the previous close)
        for j in list(pos):
            p = pos[j]; o, l, h = Ov[i, j], Lv[i, j], Hv[i, j]
            px = None
            if not np.isfinite(Cv[i, j]) and i > p['bi']: px = p.get('lc', p['e'])   # stopped trading: out at the last price
            elif p.get('sell_open') and np.isfinite(o): px = o
            elif i > p['bi'] and ex.get('stop') and np.isfinite(o) and o <= p['stop']: px = o
            elif ex.get('stop') and np.isfinite(l) and l <= p['stop']: px = p['stop']
            elif ex.get('target') and i > p['bi'] and np.isfinite(o) and o >= p['tgt']: px = o
            elif ex.get('target') and np.isfinite(h) and h >= p['tgt']: px = p['tgt']
            if px is not None:
                cash += p['sh'] * px * (1 - COST); trades.append(px / p['e'] - 1 - 2 * COST); del pos[j]
        # 2) buys at today's open from yesterday's signals
        if i > lo and pend:
            for j in pend:
                if len(pos) >= mp: break
                o = Ov[i, j]
                if j in pos or not np.isfinite(o) or o <= 0: continue
                val = min(cash, eqv / mp)
                if val < eqv / mp * 0.5: break
                sh = val / (o * (1 + COST)); cash -= val
                pos[j] = dict(e=o, sh=sh, bi=i, stop=o * (1 - ex.get('stop', 1)), tgt=o * (1 + ex.get('target', 9)))
        # 3) mark to market at the close
        for j, p in pos.items():
            if np.isfinite(Cv[i, j]): p['lc'] = Cv[i, j]
        eqv = cash + sum(p['sh'] * p.get('lc', p['e']) for j, p in pos.items())
        eq.append(eqv)
        # 4) decisions at the close: exits for tomorrow's open, then new signals
        for j, p in pos.items():
            held = i - p['bi'] + 1
            c = Cv[i, j]
            if ex.get('days') and held >= ex['days']: p['sell_open'] = True
            if ex.get('above_sma5') and np.isfinite(c) and c > s5[i, j]: p['sell_open'] = True
            if ex.get('cross_down') and e20v[i, j] < s50v[i, j]: p['sell_open'] = True
            if ex.get('trail_low20') and held > 1 and np.isfinite(c) and c < l20v[i - 1, j]: p['sell_open'] = True
        pend = []
        allow = (not mood) or UP[i]
        if ex.get('rebalance'):
            if ISME[i]:
                pr = Pv[i]; ok = np.isfinite(pr)
                tgt = set(np.argsort(-np.where(ok, pr, -np.inf))[:ex['rebalance']][:ok.sum()])
                for j, p in pos.items():
                    if j not in tgt: p['sell_open'] = True
                if allow: pend = [j for j in tgt if j not in pos]
                else:
                    for p in pos.values(): p['sell_open'] = True
        elif allow:
            sig = np.nonzero(Ev[i])[0]
            if len(sig):
                pr = Pv[i, sig]; sig = sig[np.argsort(-np.nan_to_num(pr, nan=-1e9))]
                pend = [j for j in sig if j not in pos]
    e = pd.Series(eq, index=dates[lo:hi + 1])
    return e, np.array(trades)

def stats(e, tr):
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    cagr = e.iloc[-1] ** (1 / yrs) - 1; dd = (e / e.cummax() - 1).min()
    r = e.pct_change().dropna(); sh = r.mean() / r.std() * 252 ** .5 if r.std() > 0 else 0
    by = {int(y): round((g.iloc[-1] / g.iloc[0] - 1) * 100, 1) for y, g in e.groupby(e.index.year)}
    return dict(cagr=round(cagr * 100, 1), dd=round(dd * 100, 1), sharpe=round(sh, 2), trades=int(len(tr)),
                win=round((tr > 0).mean() * 100, 1) if len(tr) else None, avg=round(tr.mean() * 100, 2) if len(tr) else None, years=by)

if __name__ == '__main__':
    S = strat_defs(); out = {}
    mid = dates.searchsorted(pd.Timestamp('2025-01-01'))
    # benchmark: equal-weight 300 most-traded, rebalanced monthly (no cap)
    bret = ret.where(LIQ.shift(1).fillna(False)).mean(axis=1).fillna(0).iloc[START:]
    be = (1 + bret).cumprod(); out['Benchmark: 300 most-traded, equal weight'] = dict(full=stats(be, np.array([])))
    print(f"{'Benchmark: 300 most-traded, equal weight':72s} {out['Benchmark: 300 most-traded, equal weight']['full']}")
    for name, (en, pr, ex) in S.items():
        e, tr = simulate(en, pr, ex); em, trm = simulate(en, pr, ex, mood=True)
        a, _ = simulate(en, pr, ex, lo=START, hi=mid - 1); b, _ = simulate(en, pr, ex, lo=mid)
        sa, sb = stats(a, np.array([])), stats(b, np.array([]))
        out[name] = dict(full=stats(e, tr), mood=stats(em, trm), first=sa['cagr'], second=sb['cagr'])
        f, mo = out[name]['full'], out[name]['mood']
        print(f"{name:72s} CAGR {f['cagr']:6.1f}% DD {f['dd']:6.1f}% Sharpe {f['sharpe']:5.2f} trades {f['trades']:4d} win {f['win']}% avg {f['avg']}% | "
              f"halves {sa['cagr']:+.1f}% / {sb['cagr']:+.1f}% | mood filter CAGR {mo['cagr']:.1f}% DD {mo['dd']:.1f}% | {f['years']}")
    # detail for the site's rule: weekly growth of Rs 100 against the benchmark
    k = [x for x in S if "site's rule" in x][0]; en, pr, ex = S[k]
    e, _ = simulate(en, pr, ex)
    wk = e.resample('W-FRI').last().dropna(); bw = be.reindex(wk.index, method='ffill')
    out['curve'] = dict(dates=[f"{x:%Y-%m-%d}" for x in wk.index], rule=[round(v * 100, 2) for v in wk.values], bench=[round(v * 100, 2) for v in bw.values])
    out['pick'] = k
    json.dump(dict(built=pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%MZ'), start=str(dates[START].date()), end=str(dates[-1].date()),
                   split='2025-01-01', results={k_: v for k_, v in out.items() if k_ not in ('curve', 'pick')}, curve=out['curve'], pick=out['pick']), open(f'{WD}/algos_bt.json', 'w'), indent=1)
