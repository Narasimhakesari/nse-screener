#!/usr/bin/env python3
"""Nightly: this week's NIFTY trade for the page (options_live.json) and its live record.

Usage: python3 build/options_daily.py WD        (run on GitHub Actions after the NSE F&O file is out, ~7 pm IST)

The rule (tested in build/options_15y.py on NSE daily files and on Stockmock's minute data):
  * on the 2nd trading day before each NIFTY weekly expiry, at about 3:15 pm, sell the ATM call and the ATM put and
    buy a call 4% above and a put 4% below (strikes nearest to those levels), 1 lot each;
  * hold until 3:15 pm on expiry day, then close all four legs (or let them expire).
The live record uses NSE's closing prices on the entry day and on expiry day, which are close to, but not the same as,
3:15 pm prices. Holidays: the entry day is counted in weekdays; if an NSE holiday falls in between, the page says so
only once the exchange's file shows it, so check the exchange holiday list.
"""
import os, sys, io, json, zipfile, subprocess, time, datetime as dt
import numpy as np, pandas as pd

WD = sys.argv[1]; FO = f'{WD}/fo_live'; os.makedirs(FO, exist_ok=True)
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
OUT = os.path.join(ROOT, 'options_live.json')
RULE = dict(entry_days_before=2, wing=0.04, time='3:15 pm', symbol='NIFTY')
LIVE_SINCE = '2026-11-20'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'

def fetch(d):
    out = f'{FO}/{d:%Y%m%d}.pkl'
    if os.path.exists(out): return True
    tmp = f'{FO}/{d:%Y%m%d}.zip'
    for host in ('https://nsearchives.nseindia.com/', 'https://archives.nseindia.com/'):
        u = f'{host}content/fo/BhavCopy_NSE_FO_0_0_0_{d:%Y%m%d}_F_0000.csv.zip'
        r = subprocess.run(['curl', '-s', '-m', '60', '-A', UA, '-w', '%{http_code}', '-o', tmp, u], capture_output=True, text=True)
        if r.stdout.strip() == '200':
            try:
                with zipfile.ZipFile(tmp) as z: raw = z.read(z.namelist()[0])
                x = pd.read_csv(io.BytesIO(raw), skipinitialspace=True, low_memory=False)
                x = x[(x.TckrSymb.astype(str).str.strip() == 'NIFTY') & x.FinInstrmTp.astype(str).str.strip().isin(['IDO', 'IDF'])]
                y = pd.DataFrame(dict(date=pd.Timestamp(d), typ=np.where(x.FinInstrmTp.str.strip() == 'IDF', 'FUT', x.OptnTp.astype(str).str.strip()),
                                      exp=pd.to_datetime(x.XpryDt.astype(str).str.strip(), errors='coerce'), k=pd.to_numeric(x.StrkPric, errors='coerce'),
                                      close=pd.to_numeric(x.ClsPric, errors='coerce'), settle=pd.to_numeric(x.SttlmPric, errors='coerce'),
                                      vol=pd.to_numeric(x.TtlTradgVol, errors='coerce'), und=pd.to_numeric(x.UndrlygPric, errors='coerce'),
                                      lot=pd.to_numeric(x.get('NewBrdLotQty'), errors='coerce')))
                y['px'] = np.where((y.vol > 0) & (y.close > 0), y.close, y.settle)
                y.to_pickle(out); os.remove(tmp); return True
            except Exception as e:
                print('parse failed', d, e)
    if os.path.exists(tmp): os.remove(tmp)
    return False

def weekdays_after(d, k):
    x = pd.Timestamp(d)
    while k > 0:
        x += pd.Timedelta(days=1)
        if x.weekday() < 5: k -= 1
    return x

def weekdays_before(d, k):
    x = pd.Timestamp(d)
    while k > 0:
        x -= pd.Timedelta(days=1)
        if x.weekday() < 5: k -= 1
    return x

def main():
    today = dt.date.today()
    got = [d for d in (today - dt.timedelta(k) for k in range(0, 40)) if d.weekday() < 5 and fetch(d)]
    files = sorted(f for f in os.listdir(FO) if f.endswith('.pkl'))
    if not files: print('no F&O files'); return
    A = pd.concat([pd.read_pickle(f'{FO}/{f}') for f in files], ignore_index=True)
    cal = sorted(A.date.unique()); last = pd.Timestamp(cal[-1])
    day = A[A.date == last]
    spot = float(day.und.dropna().median())
    lot = int(day.lot.dropna().mode().iloc[0]) if day.lot.notna().any() else 65
    opt = day[day.typ.isin(['CE', 'PE'])]
    exps = sorted(e for e in opt.exp.dropna().unique() if pd.Timestamp(e) >= last)
    def strikes_for(U, chain):
        ks = np.array(sorted(chain.k.dropna().unique()))
        near = lambda t: float(ks[np.argmin(np.abs(ks - t))])
        return dict(atm=near(U), call_wing=near(U * (1 + RULE['wing'])), put_wing=near(U * (1 - RULE['wing'])))
    def price(chain, typ, k):
        r = chain[(chain.typ == typ) & (chain.k == k)].px
        return float(r.iloc[0]) if len(r) and np.isfinite(r.iloc[0]) else None
    def legs_and_credit(chain, s):
        legs = [dict(action='Sell', typ='CE', k=s['atm']), dict(action='Sell', typ='PE', k=s['atm']),
                dict(action='Buy', typ='CE', k=s['call_wing']), dict(action='Buy', typ='PE', k=s['put_wing'])]
        for l in legs: l['price'] = price(chain, l['typ'], l['k'])
        ok = all(l['price'] is not None for l in legs)
        credit = sum((l['price'] if l['action'] == 'Sell' else -l['price']) for l in legs) if ok else None
        width = max(s['call_wing'] - s['atm'], s['atm'] - s['put_wing'])
        return legs, credit, width

    # ---- this week's trade ----
    nxt = pd.Timestamp(exps[0]) if exps else None
    week = None
    if nxt is not None:
        e = nxt if nxt > last else (pd.Timestamp(exps[1]) if len(exps) > 1 else nxt)
        entry = weekdays_before(e, RULE['entry_days_before'])
        chain = opt[opt.exp == e]
        s = strikes_for(spot, chain); legs, credit, width = legs_and_credit(chain, s)
        if last < entry:
            state = 'tomorrow' if weekdays_after(last, 1) == entry else 'waiting'
        elif last == entry: state = 'entered_today'
        else: state = 'open'
        entry_info = None
        if last >= entry:
            ed = A[(A.date == entry) & (A.exp == e) & A.typ.isin(['CE', 'PE'])]
            if len(ed):
                Ue = float(A[A.date == entry].und.dropna().median()); se = strikes_for(Ue, ed)
                el, ec, ew = legs_and_credit(ed, se)
                now = [dict(l, now=price(chain, l['typ'], l['k'])) for l in el]
                pnl = None
                if ec is not None and all(x['now'] is not None for x in now):
                    pnl = ec - sum((x['now'] if x['action'] == 'Sell' else -x['now']) for x in now)
                entry_info = dict(spot=round(Ue, 2), legs=now, credit=round(ec, 2) if ec else None, width=ew,
                                  pnl_points=round(pnl, 2) if pnl is not None else None)
        week = dict(expiry=str(e.date()), entry=str(entry.date()), state=state, spot=round(spot, 2), lot=lot,
                    strikes=s, legs=legs, credit=round(credit, 2) if credit else None, width=width,
                    max_profit=round(credit * lot) if credit else None, max_loss=round((width - credit) * lot) if credit else None,
                    entered=entry_info)

    # ---- live record: every expiry from LIVE_SINCE with both an entry-day and an expiry-day file ----
    rec = []
    try: rec = json.load(open(OUT)).get('record', [])
    except Exception: rec = []
    have = {r['expiry'] for r in rec}
    for e in sorted(A.exp.dropna().unique()):
        e = pd.Timestamp(e)
        if str(e.date()) in have or e > last or str(e.date()) < LIVE_SINCE: continue
        entry = weekdays_before(e, RULE['entry_days_before'])
        ed = A[(A.date == entry) & (A.exp == e) & A.typ.isin(['CE', 'PE'])]
        xd = A[(A.date == e) & (A.exp == e) & A.typ.isin(['CE', 'PE'])]
        if not len(ed) or not len(xd): continue
        Ue = float(A[A.date == entry].und.dropna().median()); se = strikes_for(Ue, ed)
        el, ec, ew = legs_and_credit(ed, se)
        xp = [price(xd, l['typ'], l['k']) for l in el]
        if ec is None or any(v is None for v in xp): continue
        cost = sum(max(0.5, 0.01 * p) for p in [l['price'] for l in el] + xp)
        pnl = ec - sum((v if l['action'] == 'Sell' else -v) for l, v in zip(el, xp)) - cost
        lt = int(A[A.date == entry].lot.dropna().mode().iloc[0]) if A[A.date == entry].lot.notna().any() else lot
        rec.append(dict(expiry=str(e.date()), entry=str(entry.date()), spot_entry=round(Ue, 2), spot_expiry=round(float(A[A.date == e].und.dropna().median()), 2),
                        atm=se['atm'], wings=[se['put_wing'], se['call_wing']], credit=round(ec, 2), pnl_points=round(pnl, 2), pnl_rupees=round(pnl * lt), lot=lt))
    rec.sort(key=lambda r: r['expiry'])
    tested = dict(
        stockmock=[dict(period='Mar 2019 – Dec 2022 (includes the 2020 crash)', profit=99791, worst_week=-22373, worst_fall=-94168, win=56, margin=156000),
                   dict(period='Jan 2023 – Nov 2026', profit=107782, worst_week=-36881, worst_fall=-82846, win=60, margin=156000)],
        unhedged=[dict(period='Mar 2019 – Dec 2022', profit=193009, worst_week=-42860, worst_fall=-79088),
                  dict(period='Jan 2023 – Nov 2026', profit=187734, worst_week=-36009, worst_fall=-75990)])
    out = dict(built=pd.Timestamp.now('UTC').strftime('%Y-%m-%dT%H:%MZ'), asof=str(last.date()), rule=RULE, week=week, record=rec,
               live_since=LIVE_SINCE, tested=tested)
    json.dump(out, open(OUT, 'w'), indent=1, default=str)
    print(json.dumps(dict(asof=out['asof'], week=week), default=str)[:1500])

if __name__ == '__main__':
    main()
