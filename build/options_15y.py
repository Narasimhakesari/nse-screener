#!/usr/bin/env python3
"""NSE index options: which strategies made money over 15 years? Runs on GitHub Actions (NSE files are not reachable
from elsewhere).

Usage: python3 build/options_15y.py WD     (writes WD/options_bt.json and prints a summary)

Data: NSE F&O daily bhavcopy files: the old format (foDDMONYYYYbhav.csv.zip) up to 5 Jul 2024 and the UDiFF format
(BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip) from 8 Jul 2024. NIFTY and BANKNIFTY index options and futures only,
strikes within 25% of the underlying. Filtered days are cached in WD/fo.

Method (end-of-day only, so positional strategies; intraday moves between closes are not seen):
  * every trade is entered at a day's closing price and marked at each later close; options that did not trade that
    day are valued at NSE's settlement price, else the last price;
  * costs: each leg pays max(0.5 point, 1% of its price) when bought or sold (bid-ask spread, brokerage, STT,
    exchange charges); nothing when it expires;
  * stop-loss and profit target are checked at each close and filled at that close (real intraday spikes can be
    worse for sellers: a stated limitation);
  * returns are stated on a fixed capital of 20% of the contract's notional value per lot (about what a naked
    seller needs in margin plus a buffer), the same for every strategy so they can be compared;
  * walk-forward: each strategy's settings are chosen on 2011-2018 (monthly) or 2019-2022 (weekly), then checked on
    the later years, which played no part in choosing them.
"""
import os, sys, io, re, zipfile, time, json, itertools, subprocess, datetime as dt
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd

WD = sys.argv[1]; FO = f'{WD}/fo'; os.makedirs(FO, exist_ok=True)
SYMS = ('NIFTY', 'BANKNIFTY')
START = dt.date(int(os.environ.get('OPT_START', '2011')), 1, 1)
MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'

def curl(u, f):
    r = subprocess.run(['curl', '-s', '-m', '60', '-A', UA, '-H', 'Accept: */*', '-w', '%{http_code}', '-o', f, u], capture_output=True, text=True)
    return r.stdout.strip()

def parse_old(raw, d):
    x = pd.read_csv(io.BytesIO(raw), skipinitialspace=True)
    x.columns = [c.strip().upper() for c in x.columns]
    x = x[x.SYMBOL.astype(str).str.strip().isin(SYMS) & x.INSTRUMENT.astype(str).str.strip().isin(['OPTIDX', 'FUTIDX'])]
    return pd.DataFrame(dict(date=pd.Timestamp(d), sym=x.SYMBOL.str.strip(), typ=np.where(x.INSTRUMENT.str.strip() == 'FUTIDX', 'FUT', x.OPTION_TYP.astype(str).str.strip()),
                             exp=pd.to_datetime(x.EXPIRY_DT.astype(str).str.strip(), format='%d-%b-%Y', errors='coerce'), k=pd.to_numeric(x.STRIKE_PR, errors='coerce'),
                             close=pd.to_numeric(x.CLOSE, errors='coerce'), settle=pd.to_numeric(x.SETTLE_PR, errors='coerce'),
                             vol=pd.to_numeric(x.CONTRACTS, errors='coerce'), oi=pd.to_numeric(x.OPEN_INT, errors='coerce'), und=np.nan))

def parse_new(raw, d):
    x = pd.read_csv(io.BytesIO(raw), skipinitialspace=True, low_memory=False)
    x = x[x.TckrSymb.astype(str).str.strip().isin(SYMS) & x.FinInstrmTp.astype(str).str.strip().isin(['IDO', 'IDF'])]
    return pd.DataFrame(dict(date=pd.Timestamp(d), sym=x.TckrSymb.str.strip(), typ=np.where(x.FinInstrmTp.str.strip() == 'IDF', 'FUT', x.OptnTp.astype(str).str.strip()),
                             exp=pd.to_datetime(x.XpryDt.astype(str).str.strip(), errors='coerce'), k=pd.to_numeric(x.StrkPric, errors='coerce'),
                             close=pd.to_numeric(x.ClsPric, errors='coerce'), settle=pd.to_numeric(x.SttlmPric, errors='coerce'),
                             vol=pd.to_numeric(x.TtlTradgVol, errors='coerce'), oi=pd.to_numeric(x.OpnIntrst, errors='coerce'),
                             und=pd.to_numeric(x.UndrlygPric, errors='coerce')))

def fetch(d):
    out = f'{FO}/{d:%Y%m%d}.pkl'
    if os.path.exists(out): return 1
    if os.path.exists(out + '.none'): return 0
    tmp = f'{FO}/{d:%Y%m%d}.zip'
    if d < dt.date(2024, 7, 8):
        rel = f'content/historical/DERIVATIVES/{d.year}/{MON[d.month-1]}/fo{d:%d}{MON[d.month-1]}{d.year}bhav.csv.zip'; parse = parse_old
        urls = ['https://archives.nseindia.com/' + rel, 'https://nsearchives.nseindia.com/' + rel]
    else:
        rel = f'content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip'; parse = parse_new
        urls = ['https://nsearchives.nseindia.com/' + rel, 'https://archives.nseindia.com/' + rel]
    for attempt in range(3):
        codes = []
        for u in urls:
            code = curl(u, tmp); codes.append(code)
            if code == '200':
                try:
                    with zipfile.ZipFile(tmp) as z: raw = z.read(z.namelist()[0])
                    x = parse(raw, d)
                    keep = []
                    for s, g in x.groupby('sym'):
                        fut = g[g.typ == 'FUT'].sort_values('exp')
                        u0 = fut.close.iloc[0] if len(fut) else g.und.dropna().median()
                        keep.append(g[(g.typ == 'FUT') | ((g.k > u0 * 0.75) & (g.k < u0 * 1.25))] if np.isfinite(u0) else g)
                    x = pd.concat(keep) if keep else x
                    x.to_pickle(out); os.remove(tmp); return 1
                except Exception as e:
                    print('parse failed', d, e, flush=True)
        if all(c == '404' for c in codes):
            open(out + '.none', 'w').close(); break
        time.sleep(2 + 4 * attempt)
    if os.path.exists(tmp): os.remove(tmp)
    return 0

def load():
    end = dt.date.today()
    days = [START + dt.timedelta(k) for k in range((end - START).days)]
    days = [d for d in days if d.weekday() < 5]
    t0 = time.time()
    with ThreadPoolExecutor(8) as ex: got = sum(ex.map(fetch, days))
    print(f'F&O files: {got} of {len(days)} weekdays since {START} ({time.time()-t0:.0f}s)', flush=True)
    if got < 50:
        for f in os.listdir(FO):
            if f.endswith('.none'): os.remove(f'{FO}/{f}')
    fr = [pd.read_pickle(f'{FO}/{f}') for f in sorted(os.listdir(FO)) if f.endswith('.pkl')]
    a = pd.concat(fr, ignore_index=True)
    a = a[a.typ.isin(['CE', 'PE', 'FUT'])].dropna(subset=['exp'])
    a['px'] = np.where((a.vol > 0) & (a.close > 0), a.close, np.where(a.settle > 0, a.settle, a.close))
    return a

A = load()
CAL = {s: sorted(A[A.sym == s].date.unique()) for s in SYMS}
print({s: (str(pd.Timestamp(CAL[s][0]).date()), str(pd.Timestamp(CAL[s][-1]).date()), len(CAL[s])) for s in SYMS}, flush=True)

class Book:
    """Prices for one symbol: per expiry a table date x (type, strike); the near-month future; the expiry calendar."""
    def __init__(self, s):
        x = A[A.sym == s]
        self.cal = pd.DatetimeIndex(CAL[s]); self.pos = {d: i for i, d in enumerate(self.cal)}
        f = x[x.typ == 'FUT'].sort_values(['date', 'exp'])
        self.fut = f.groupby('date').first().px.reindex(self.cal).ffill()          # near-month future: the underlying
        self.monthly = sorted(set(f.exp.unique()))
        o = x[x.typ != 'FUT']
        self.all_exp = sorted(set(o.exp.unique()))
        self.weekly = [e for e in self.all_exp if e not in set(self.monthly)]
        self.tab = {}
        for e, g in o.groupby('exp'):
            t = g.pivot_table(index='date', columns=['typ', 'k'], values='px', aggfunc='last').sort_index()
            self.tab[e] = t.ffill()
        self.sma50 = self.fut.rolling(50).mean(); self.hi20 = self.fut.rolling(20).max().shift(1); self.lo20 = self.fut.rolling(20).min().shift(1)
        self.cost_min = 0.5 if s == 'NIFTY' else 1.0
    def strike(self, e, d, typ, target):
        t = self.tab.get(e)
        if t is None or d not in t.index or typ not in t.columns.get_level_values(0): return None
        row = t.loc[d, typ].dropna(); row = row[row > 0]
        if not len(row): return None
        k = row.index.values; return float(k[np.argmin(np.abs(k - target))])
    def price(self, e, d, typ, k):
        try: return float(self.tab[e].at[d, (typ, k)])
        except KeyError: return np.nan

B = {s: Book(s) for s in SYMS}

def run_trade(bk, e, i0, legs, sl=None, pt=None, max_days=None):
    """legs: list of (typ, k, side) with side +1 bought / -1 sold. Entered at the close of day i0, held until expiry e,
    the stop-loss / profit target (fractions of the credit or debit), or max_days. Returns P&L in index points."""
    d0 = bk.cal[i0]
    p0 = [bk.price(e, d0, t, k) for t, k, s in legs]
    if any(not np.isfinite(p) or p <= 0 for p in p0): return None
    cost = sum(max(bk.cost_min, 0.01 * p) for p in p0)
    v0 = sum(s * p for (t, k, s), p in zip(legs, p0))             # >0 debit, <0 credit
    base = abs(v0)
    ie = bk.pos.get(pd.Timestamp(e))
    if ie is None: return None
    last = min(ie, i0 + max_days) if max_days else ie
    for i in range(i0 + 1, last + 1):
        d = bk.cal[i]
        p = [bk.price(e, d, t, k) for t, k, s in legs]
        if any(not np.isfinite(x) for x in p): continue
        v = sum(s * x for (t, k, s), x in zip(legs, p)); pnl = v - v0
        at_exp = (i == ie)
        hit = (sl is not None and pnl <= -sl * base) or (pt is not None and pnl >= pt * base) or i == last
        if hit:
            ex_cost = 0 if at_exp else sum(max(bk.cost_min, 0.01 * x) for x in p)
            return dict(pnl=pnl - cost - ex_cost, entry=str(d0.date()), exit=str(d.date()), days=i - i0, und=float(bk.fut.iloc[i0]),
                        why='expiry' if at_exp else ('stop' if sl is not None and pnl <= -sl * base else 'target' if pt is not None and pnl >= pt * base else 'time'))
    return None

# ---------- strategy families ----------
def legs_for(bk, e, d, kind, p):
    U = bk.fut.loc[d]; st = lambda typ, m: bk.strike(e, d, typ, U * m)
    if kind == 'short_straddle':
        k = st('CE', 1.0); return [('CE', k, -1), ('PE', k, -1)] if k else None
    if kind == 'short_strangle':
        a, b = st('CE', 1 + p['otm']), st('PE', 1 - p['otm']); return [('CE', a, -1), ('PE', b, -1)] if a and b else None
    if kind == 'iron_condor':
        a, b = st('CE', 1 + p['otm']), st('PE', 1 - p['otm']); c, f = st('CE', 1 + p['otm'] + p['w']), st('PE', 1 - p['otm'] - p['w'])
        return [('CE', a, -1), ('PE', b, -1), ('CE', c, 1), ('PE', f, 1)] if a and b and c and f and c > a and f < b else None
    if kind == 'trend_credit_spread':
        up = U > bk.sma50.loc[d]
        if up:
            a, b = st('PE', 1 - p['otm']), st('PE', 1 - p['otm'] - p['w']); return [('PE', a, -1), ('PE', b, 1)] if a and b and b < a else None
        a, b = st('CE', 1 + p['otm']), st('CE', 1 + p['otm'] + p['w']); return [('CE', a, -1), ('CE', b, 1)] if a and b and b > a else None
    if kind == 'long_straddle':
        k = st('CE', 1.0); return [('CE', k, 1), ('PE', k, 1)] if k else None
    if kind == 'trend_long_call':      # buy a call when above the 50-day average, else a put
        up = U > bk.sma50.loc[d]; typ = 'CE' if up else 'PE'
        k = st(typ, (1 + p['otm']) if up else (1 - p['otm'])); return [(typ, k, 1)] if k else None
    if kind == 'trend_debit_spread':
        up = U > bk.sma50.loc[d]
        if up:
            a, b = st('CE', 1.0), st('CE', 1 + p['w']); return [('CE', a, 1), ('CE', b, -1)] if a and b and b > a else None
        a, b = st('PE', 1.0), st('PE', 1 - p['w']); return [('PE', a, 1), ('PE', b, -1)] if a and b and b < a else None

def cycle(sym, kind, p, cycle='monthly', lo=None, hi=None):
    bk = B[sym]; out = []
    exps = bk.monthly if cycle == 'monthly' else bk.weekly
    for e in exps:
        e = pd.Timestamp(e); ie = bk.pos.get(e)
        if ie is None: continue
        i0 = ie - p['dte']
        if i0 < 60: continue
        d0 = bk.cal[i0]
        if (lo and d0 < pd.Timestamp(lo)) or (hi and d0 > pd.Timestamp(hi)): continue
        if cycle == 'weekly':
            prev = [x for x in bk.all_exp if pd.Timestamp(x) < e]
            if prev and bk.pos.get(pd.Timestamp(prev[-1]), -1) > i0: continue      # entry must be after the previous expiry
        L = legs_for(bk, e, d0, kind, p)
        if not L: continue
        r = run_trade(bk, e, i0, L, p.get('sl'), p.get('pt'), p.get('hold'))
        if r: out.append(r)
    return out

def breakout(sym, kind, p, lo=None, hi=None):
    """Signal-driven buying: when the future closes above its 20-day high (or below its 20-day low), buy; one trade at a time."""
    bk = B[sym]; out = []; i = 60; n = len(bk.cal)
    while i < n - 2:
        d = bk.cal[i]
        if (lo and d < pd.Timestamp(lo)) or (hi and d > pd.Timestamp(hi)): i += 1; continue
        U = bk.fut.iloc[i]; up = U > bk.hi20.iloc[i]; dn = U < bk.lo20.iloc[i]
        if not (up or dn): i += 1; continue
        cands = [pd.Timestamp(e) for e in bk.monthly if bk.pos.get(pd.Timestamp(e), -1) - i >= p.get('min_dte', 10)]
        if not cands: i += 1; continue
        e = cands[0]
        mk = lambda typ, m: bk.strike(e, d, typ, U * m)
        if kind == 'breakout_long_option':
            typ = 'CE' if up else 'PE'; k = mk(typ, (1 + p['otm']) if up else (1 - p['otm'])); L = [(typ, k, 1)] if k else None
        else:  # breakout_debit_spread
            if up: a, b = mk('CE', 1.0), mk('CE', 1 + p['w']); L = [('CE', a, 1), ('CE', b, -1)] if a and b and b > a else None
            else: a, b = mk('PE', 1.0), mk('PE', 1 - p['w']); L = [('PE', a, 1), ('PE', b, -1)] if a and b and b < a else None
        if not L: i += 1; continue
        r = run_trade(bk, e, i, L, p.get('sl'), p.get('pt'), p.get('hold'))
        if r: out.append(r); i = bk.pos[pd.Timestamp(r['exit'])] + 1
        else: i += 1
    return out

def summary(tr):
    if not tr: return None
    df = pd.DataFrame(tr); df['ret'] = df.pnl / (0.2 * df.und) * 100           # % of the fixed capital
    df['y'] = pd.to_datetime(df.entry).dt.year; df['m'] = pd.to_datetime(df.entry).dt.to_period('M')
    yrs = max(1.0, (pd.Timestamp(df.entry.iloc[-1]) - pd.Timestamp(df.entry.iloc[0])).days / 365.25)
    eq = df.ret.cumsum(); dd = (eq - eq.cummax()).min()
    mon = df.groupby('m').ret.sum(); sh = mon.mean() / mon.std() * np.sqrt(12) if len(mon) > 3 and mon.std() > 0 else 0
    return dict(trades=len(df), per_year=round(df.ret.sum() / yrs, 1), win=round((df.pnl > 0).mean() * 100, 1), avg=round(df.ret.mean(), 2),
                worst=round(df.ret.min(), 1), best=round(df.ret.max(), 1), dd=round(dd, 1), sharpe=round(float(sh), 2),
                years={int(y): round(v, 1) for y, v in df.groupby('y').ret.sum().items()},
                exits=df.why.value_counts(normalize=True).mul(100).round(0).to_dict())

G = lambda **kw: [dict(zip(kw, v)) for v in itertools.product(*kw.values())]
FAMILIES = {
  'Sell an ATM straddle (monthly)': ('short_straddle', 'monthly', G(dte=[5, 10, 15, 20], sl=[None, .5, 1.0], pt=[None, .5])),
  'Sell an OTM strangle (monthly)': ('short_strangle', 'monthly', G(dte=[5, 10, 20], otm=[.02, .04, .06], sl=[None, 1.0, 2.0], pt=[None, .5])),
  'Iron condor (monthly, defined risk)': ('iron_condor', 'monthly', G(dte=[5, 10, 20], otm=[.02, .04], w=[.02, .04], pt=[None, .5])),
  'Credit spread in the trend direction (monthly, defined risk)': ('trend_credit_spread', 'monthly', G(dte=[5, 10, 20], otm=[0, .02, .04], w=[.02, .04], pt=[None, .5])),
  'Buy an ATM straddle (monthly)': ('long_straddle', 'monthly', G(dte=[5, 10, 20], pt=[.3, .5, 1.0], sl=[None, .3, .5])),
  'Buy a call above the 50-day average, a put below (monthly)': ('trend_long_call', 'monthly', G(dte=[10, 20], otm=[0, .02, .04], pt=[None, .5, 1.0], sl=[None, .5])),
  'Debit spread in the trend direction (monthly, defined risk)': ('trend_debit_spread', 'monthly', G(dte=[10, 20], w=[.02, .04], pt=[None, .5], sl=[None, .5])),
  'Buy an option on a 20-day breakout': ('breakout_long_option', 'signal', G(otm=[0, .02], pt=[.5, 1.0], sl=[.3, .5], hold=[5, 10, 20])),
  'Debit spread on a 20-day breakout': ('breakout_debit_spread', 'signal', G(w=[.02, .04], pt=[.5, None], sl=[.5, None], hold=[5, 10, 20])),
  'Sell an ATM straddle (weekly expiry)': ('short_straddle', 'weekly', G(dte=[1, 2, 3, 4], sl=[None, .5, 1.0], pt=[None, .5])),
  'Sell an OTM strangle (weekly expiry)': ('short_strangle', 'weekly', G(dte=[1, 2, 4], otm=[.01, .02, .03], sl=[None, 1.0, 2.0], pt=[None, .5])),
  'Iron condor (weekly expiry, defined risk)': ('iron_condor', 'weekly', G(dte=[1, 2, 4], otm=[.01, .02], w=[.01, .02], pt=[None, .5])),
}
def runf(sym, kind, cyc, p, lo=None, hi=None):
    if cyc == 'signal': return breakout(sym, kind, p, lo, hi)
    return cycle(sym, kind, p, cyc, lo, hi)

if __name__ == '__main__':
    res = {}
    for sym in SYMS:
        bk = B[sym]; print(f"\n===== {sym}: {len(bk.monthly)} monthly and {len(bk.weekly)} weekly expiries; future {bk.fut.iloc[60]:.0f} -> {bk.fut.iloc[-1]:.0f}", flush=True)
        for name, (kind, cyc, grid) in FAMILIES.items():
            if cyc == 'weekly':
                wk = [e for e in bk.weekly]
                if len(wk) < 100: print(f'{name}: not enough weekly expiries'); continue
                split = '2023-01-01'; tr_lo, tr_hi, te_lo = '2019-01-01', '2022-12-31', '2023-01-01'
            else:
                split = '2019-01-01'; tr_lo, tr_hi, te_lo = None, '2018-12-31', '2019-01-01'
            rows = []
            for p in grid:
                s = summary(runf(sym, kind, cyc, p, tr_lo, tr_hi))
                if s and s['trades'] >= (30 if cyc != 'weekly' else 60): rows.append((s['sharpe'], s['per_year'], p, s))
            if not rows: print(f'{name}: no valid settings'); continue
            rows.sort(key=lambda r: (-r[0], -r[1]))
            p = rows[0][2]; tr = rows[0][3]
            te = summary(runf(sym, kind, cyc, p, te_lo, None)) or {}
            t5 = [(summary(runf(sym, kind, cyc, r[2], te_lo, None)) or {}).get('per_year', 0) for r in rows[:5]]
            allp = summary(runf(sym, kind, cyc, p, None, None)) or {}
            res[f'{sym} | {name}'] = dict(kind=kind, cycle=cyc, settings=p, train=tr, test=te, test_top5_median=float(np.median(t5)), full=allp)
            print(f"{name:62s} pick {p} | train {tr['per_year']:6.1f}%/yr sh {tr['sharpe']} worst trade {tr['worst']}% | "
                  f"TEST {te.get('per_year','-')}%/yr sh {te.get('sharpe','-')} win {te.get('win','-')}% worst trade {te.get('worst','-')}% dd {te.get('dd','-')}% | top-5 median {np.median(t5):.1f} | years {allp.get('years')}", flush=True)
    # buy-and-hold reference on the same capital basis: the future's move / (20% of notional) = 5x leverage
    for sym in SYMS:
        f = B[sym].fut; y = f.groupby(f.index.year).agg(['first', 'last'])
        print(sym, 'index yearly change %:', {int(k): round((v['last'] / v['first'] - 1) * 100, 1) for k, v in y.iterrows()})
    json.dump(dict(built=pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%MZ'), results=res), open(f'{WD}/options_bt.json', 'w'), default=str, indent=1)
    print('\nwrote options_bt.json')
