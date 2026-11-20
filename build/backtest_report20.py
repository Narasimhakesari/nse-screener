#!/usr/bin/env python3
"""Full report on the home page's rule, answering an outside review. Run on GitHub Actions.

Usage: python3 build/backtest_report20.py WD   (writes WD/report_bt.json; prints the report)

Rule: month-end, top 10 by momentum among the 300 most-traded stocks above their 200-day average (all chosen with data
available on that date), at most 2 per industry, equal amounts at the next open, sell what drops out; cash while an
equal-weight index of the 300 most-traded stocks is below its 100-day average. Red-flag checks are not in the test: there
is no history for them.

Scenarios: as tested (0.15% cost each side, cash earns nothing, before tax); realistic costs (0.25% each side: STT 0.1%,
stamp duty 0.015% on buys, exchange and SEBI fees, GST, DP charge, about 0.1% slippage at the open); plus cash in a liquid
fund at 6% a year; plus Indian capital-gains tax at today's rates (short-term 20.8%, long-term 13% above Rs 1.25 lakh a year,
for a Rs 10 lakh account), paid each April.
"""
import os, sys, json
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest_improve20 import (WD, sim, MOM, FILT, stats, bench, PERIODS, START, n, idx, dates, ISME)

M = MOM['12-1 vol-adjusted']; base = dict(score=M, N=10, filt=100)

def bounds():
    out = []
    for lab, a_, b_ in PERIODS:
        lo, hi = max(START, idx(a_)), min(n - 1, idx(b_) - 1 if idx(b_) < n else n - 1)
        if hi - lo >= 100: out.append((lab, lo, hi))
    return out

def metrics(e, trades=None):
    s = stats(e); r = e.pct_change().dropna()
    dn = r[r < 0]; s['sortino'] = round(float(r.mean() / (np.sqrt((dn ** 2).mean())) * 252 ** .5), 2) if len(dn) else None
    m = e.resample('ME').last(); r12 = m.pct_change(12).dropna()
    s['worst12m'] = round(float(r12.min()) * 100, 1); s['best12m'] = round(float(r12.max()) * 100, 1)
    s['neg12m_share'] = round(float((r12 < 0).mean()) * 100, 1)
    r36 = m.pct_change(36).dropna(); s['worst36m'] = round(float(r36.min()) * 100, 1)
    peak = e.cummax(); under = e < peak; longest = cur = 0; start = None
    for d, u in under.items():
        if u: cur = (d - start).days if start is not None else 0; start = start if start is not None else d
        else: longest = max(longest, cur); cur = 0; start = None
    s['longest_underwater_days'] = int(max(longest, cur))
    s['monthly_win'] = round(float((m.pct_change().dropna() > 0).mean()) * 100, 1)
    if trades:
        T = pd.DataFrame(trades, columns=['sym', 'buy', 'sell', 'days', 'ret'])
        yrs = (e.index[-1] - e.index[0]).days / 365.25
        s.update(trades_per_year=round(len(T) / yrs, 1), trade_win=round(float((T.ret > 0).mean()) * 100, 1),
                 avg_trade=round(float(T.ret.mean()), 2), avg_win=round(float(T.ret[T.ret > 0].mean()), 2), avg_loss=round(float(T.ret[T.ret <= 0].mean()), 2),
                 hold_avg_days=round(float(T.days.mean()), 0), hold_median_days=round(float(T.days.median()), 0),
                 held_over_1y=round(float((T.days > 365).mean()) * 100, 1),
                 turnover_per_year=round(len(T) / yrs / 10 * 100, 0),
                 best_trades=T.nlargest(5, 'ret')[['sym', 'buy', 'ret']].values.tolist(), worst_trades=T.nsmallest(5, 'ret')[['sym', 'buy', 'ret']].values.tolist())
    return s

if __name__ == '__main__':
    out = {}; B = bounds()
    up = FILT[100][START:][ISME[START:]]; out['time_in_cash'] = round(float((~up).mean()) * 100, 1)
    scen = [('As tested: 0.15% costs, cash earns nothing, before tax', dict()),
            ('Realistic costs: 0.25% each side', dict(cost=0.0025)),
            ('Realistic costs + cash in a liquid fund at 6%', dict(cost=0.0025, cash_rate=0.06)),
            ('Realistic costs + liquid fund + tax (what you keep)', dict(cost=0.0025, cash_rate=0.06, tax=True))]
    for lab, ch in scen:
        tr = []; e = sim(log=tr, **{**base, **ch}); s = metrics(e, tr)
        s['periods'] = [stats(sim(lo=lo, hi=hi, **{**base, **ch}))['cagr'] for _, lo, hi in B]
        out[lab] = s; out.setdefault('_curves', {})[lab] = e
        print(f"\n== {lab}\n   {s['cagr']}% a year | worst fall {s['dd']}% | Sharpe {s['sharpe']} | Sortino {s['sortino']} | periods {[float(x) for x in s['periods']]}")
        print(f"   worst 12 months {s['worst12m']}% | best 12 months {s['best12m']}% | 12-month spans that lost money {s['neg12m_share']}% | worst 3 years {s['worst36m']}% | longest below a previous peak {s['longest_underwater_days']} days | months up {s['monthly_win']}%")
        print(f"   trades a year {s['trades_per_year']} | trades that made money {s['trade_win']}% | average trade {s['avg_trade']}% (wins {s['avg_win']}%, losses {s['avg_loss']}%) | held {s['hold_avg_days']} days on average, median {s['hold_median_days']} | held over a year {s['held_over_1y']}% | turnover {s['turnover_per_year']}% a year", flush=True)
        if 'tax' in ch: print('   best trades', s['best_trades'], '\n   worst trades', s['worst_trades'])
    print(f"\ntime in cash (share of month-ends) {out['time_in_cash']}%")
    # benchmarks
    be = bench(); sb = metrics(be); out['Equal-weight 300 most-traded (price only)'] = sb
    print(f"\nEqual-weight 300 most-traded, price only: {sb['cagr']}% | worst {sb['dd']}% | Sharpe {sb['sharpe']} | Sortino {sb['sortino']} | worst 12m {sb['worst12m']}%")
    try:
        import yfinance as yf
        for tk, nm in (('^NSEI', 'NIFTY 50'), ('^CRSLDX', 'NIFTY 500')):
            px = yf.download(tk, start=str(dates[START].date()), end=str(dates[-1].date() + pd.Timedelta(days=1)), progress=False, auto_adjust=False)['Close']
            px = (px.iloc[:, 0] if isinstance(px, pd.DataFrame) else px).dropna()
            if len(px) < 500: print(nm, 'not enough data', len(px)); continue
            e = px / px.iloc[0]; s = metrics(e)
            s['from'] = str(px.index[0].date()); out[nm] = s
            print(f"{nm} (price index, from {s['from']}): {s['cagr']}% | worst {s['dd']}% | Sharpe {s['sharpe']} | Sortino {s['sortino']} | worst 12m {s['worst12m']}% | add about 1.2-1.5% a year for dividends (total return index)")
    except Exception as ex: print('index download failed', ex)
    # Monte Carlo: resample the realistic after-cost (before tax) monthly returns in 6-month blocks, 10,000 x 20 years
    e = out['_curves']['Realistic costs + cash in a liquid fund at 6%']; mr = e.resample('ME').last().pct_change().dropna().values
    rng = np.random.default_rng(7); P = 10000; Ly = 20; blk = 6; nb = Ly * 12 // blk
    cag, mdd, l3 = [], [], []
    for _ in range(P):
        st_ = rng.integers(0, len(mr) - blk, nb); path = np.concatenate([mr[s_:s_ + blk] for s_ in st_])
        eq = np.cumprod(1 + path); cag.append(eq[-1] ** (1 / Ly) - 1); mdd.append((eq / np.maximum.accumulate(eq) - 1).min())
        e36 = eq[36:] / eq[:-36]; l3.append((e36 < 1).any())
    q = lambda a, p: round(float(np.percentile(a, p)) * 100, 1)
    mc = dict(cagr_p5=q(cag, 5), cagr_p50=q(cag, 50), cagr_p95=q(cag, 95), dd_p5=q(mdd, 5), dd_p50=q(mdd, 50), dd_p95=q(mdd, 95),
              p_dd_over_40=round(float((np.array(mdd) < -0.4).mean()) * 100, 1), p_dd_over_50=round(float((np.array(mdd) < -0.5).mean()) * 100, 1),
              p_3y_loss=round(float(np.mean(l3)) * 100, 1), p_cagr_below_10=round(float((np.array(cag) < 0.10).mean()) * 100, 1))
    out['monte_carlo'] = mc
    print(f"\nMONTE CARLO (10,000 reshuffled 20-year paths, realistic costs, before tax): yearly return 5th/50th/95th percentile {mc['cagr_p5']}% / {mc['cagr_p50']}% / {mc['cagr_p95']}%")
    print(f"   worst fall 5th/50th/95th (worst/typical/mildest) {mc['dd_p5']}% / {mc['dd_p50']}% / {mc['dd_p95']}% | chance of a fall over 40% {mc['p_dd_over_40']}%, over 50% {mc['p_dd_over_50']}% | chance of some 3-year stretch losing money {mc['p_3y_loss']}% | chance of under 10% a year {mc['p_cagr_below_10']}%")
    out.pop('_curves')
    json.dump(out, open(f'{WD}/report_bt.json', 'w'), separators=(',', ':'), default=float)
    print('\nwrote report_bt.json')
