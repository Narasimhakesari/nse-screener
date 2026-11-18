#!/usr/bin/env python3
"""Nightly news headlines and company numbers for the top-ranked stocks.

Usage: python3 build/news_fund.py            (run from the repository root, after data.json is rebuilt)
Reads data.json and static.json, writes auto.json:
  news: latest Google News headlines per stock, with a tone judged from headline wording
  sc:   latest quarterly profit and sales vs a year earlier, P/E, ROE, debt and market cap from Yahoo Finance
Anything that fails to download keeps its previous value (up to 60 days old). Never fails the build.
Needs network access to news.google.com and Yahoo Finance; yfinance is optional.
"""
import json, os, re, sys, time, datetime as dt, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
NOW = dt.datetime.now(dt.timezone.utc)
LOG = dict(started=NOW.strftime('%Y-%m-%dT%H:%MZ'), news_ok=0, news_fail=0, fund_ok=0, fund_fail=0, errors=[])

def note(e):
    if len(LOG['errors']) < 40: LOG['errors'].append(str(e)[:200])

# ---------- which stocks ----------
def pick_list(D, n_top=50):
    W = dict(fMom=35, tscore=20, fSeas=15, fSwing=5)
    rows = []
    for s in D['stocks']:
        if not (s.get('liq300') and s['close'] > s['s200']): continue
        rows.append((sum(W[k] * (s.get(k) if s.get(k) is not None else 50) for k in W) / sum(W.values()), s))
    rows.sort(key=lambda r: -r[0])
    out = {s['sym']: s for _, s in rows[:n_top]}
    for s in D['stocks']:
        if s.get('mrank') and s['mrank'] <= 30: out.setdefault(s['sym'], s)
    return list(out.values())

def short_name(name):
    n = re.sub(r'\b(Limited|Ltd\.?|India|Industries|Corporation|Company|Co\.?|The)\b', ' ', name, flags=re.I)
    n = re.sub(r'\s+', ' ', n).strip(' .,&')
    n = re.sub(r'\s+(of|and|&)$', '', n, flags=re.I)
    return n or name

# ---------- news ----------
POS = r"\b(rise[sn]?|rising|jumps?|jumped|surges?|surged|soars?|soared|gains?|gained|rall(y|ies|ied)|record|beats?|upgrades?d?|raises?d?|hikes?|strong|robust|bags?|wins?|won|order[s]? worth|expansion|approval|approves|profit (up|rises|jumps|surges|grows)|turns profitable|all-time high|52-week high|outperform|buy rating|target raised)\b"
NEG = r"\b(falls?|fell|drops?|dropped|slumps?|slumped|plunges?|plunged|declines?|declined|slips?|slipped|tumbles?|tumbled|crash(es|ed)?|sinks?|sank|loss(es)?|misses|missed|downgrades?d?|cuts?|weak|probe|raid|penalty|fine[ds]?|resigns?|resignation|fraud|default|lower circuit|52-week low|sell rating|target cut|block deal|stake sale|pledge|tax demand|show cause|warning)\b"

def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (screener-bot)'})
    with urllib.request.urlopen(req, timeout=timeout) as r: return r.read()

def parse_rss(xml_bytes, must):
    items = []
    root = ET.fromstring(xml_bytes)
    for it in root.iter('item'):
        title = (it.findtext('title') or '').strip(); link = (it.findtext('link') or '').strip()
        src_el = it.find('source'); src = (src_el.text or '').strip() if src_el is not None else ''
        try: when = parsedate_to_datetime(it.findtext('pubDate'))
        except Exception: continue
        if src and title.endswith(' - ' + src): title = title[:-(len(src) + 3)]
        if (NOW - when).days > 30: continue
        if must and not re.search(must, title, re.I): continue
        items.append(dict(t=title, src=src, url=link, when=when))
    items.sort(key=lambda x: x['when'], reverse=True)
    seen, out = set(), []
    for x in items:
        k = re.sub(r'\W+', '', x['t'].lower())[:60]
        if k in seen: continue
        seen.add(k); out.append(x)
    return out[:5]

def tone(items):
    p = sum(1 for x in items if re.search(POS, x['t'], re.I))
    n = sum(1 for x in items if re.search(NEG, x['t'], re.I))
    if not items: return 'Nothing found'
    if p and n and abs(p - n) <= 1: return 'Mixed'
    if p > n: return 'Positive'
    if n > p: return 'Negative'
    return 'Neutral'

def news_for(s):
    nm = short_name(s['name'])
    first = re.escape(nm.split()[0]) if nm.split() else re.escape(s['sym'])
    q = f'("{nm}" OR "{s["sym"]}") (share OR stock OR shares OR results OR profit) when:30d'
    url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode(dict(q=q, hl='en-IN', gl='IN', ceid='IN:en'))
    items = parse_rss(fetch(url), rf'{first}|\b{re.escape(s["sym"])}\b')
    d = lambda w: w.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime('%d %b %Y').lstrip('0')
    if not items:
        return dict(tone='Nothing found', date=d(NOW), text='No company-specific headlines in the last 30 days.', src='', url='', items=[], auto=True)
    top = items[0]
    return dict(tone=tone(items), date=d(top['when']), text=top['t'], src=top['src'], url=top['url'], auto=True,
                items=[dict(t=x['t'], src=x['src'], url=x['url'], date=d(x['when'])) for x in items])

# ---------- company numbers ----------
def fund_for(sym):
    import yfinance as yf
    t = yf.Ticker(sym + '.NS')
    info = t.info or {}
    cr = lambda v: None if v is None else round(float(v) / 1e7, 1)
    out = dict(mcap=cr(info.get('marketCap')), pe=info.get('trailingPE'),
               roe=None if info.get('returnOnEquity') is None else round(info['returnOnEquity'] * 100, 1),
               de=None if info.get('debtToEquity') is None else round(info['debtToEquity'] / 100, 2), src='Yahoo Finance')
    if out['pe'] is not None: out['pe'] = round(float(out['pe']), 1)
    q = t.quarterly_income_stmt
    if q is not None and not q.empty:
        cols = sorted(q.columns, reverse=True)
        def row(*names):
            for n in names:
                if n in q.index: return q.loc[n]
        ni = row('Net Income', 'Net Income Common Stockholders', 'Net Income From Continuing Operation Net Minority Interest')
        rv = row('Total Revenue', 'Operating Revenue')
        c0 = cols[0]
        yago = [c for c in cols[1:] if 330 <= (c0 - c).days <= 400]
        if ni is not None and rv is not None and yago:
            c1 = yago[0]
            vals = [ni.get(c0), ni.get(c1), rv.get(c0), rv.get(c1)]
            if all(v is not None and v == v for v in vals):
                out.update(q=c0.strftime('%b %Y'), np=cr(vals[0]), npYoY=cr(vals[1]), sales=cr(vals[2]), salesYoY=cr(vals[3]))
    return {k: v for k, v in out.items() if v is not None}

def main():
    D = json.load(open(os.path.join(ROOT, 'data.json')))
    ap = os.path.join(ROOT, 'auto.json')
    try: OLD = json.load(open(ap))
    except Exception: OLD = {}
    news, sc = {}, {}
    def fresh(e):
        try: return (NOW.date() - dt.datetime.strptime(e.get('fetched', ''), '%Y-%m-%d').date()).days <= 60
        except Exception: return False
    for k, v in (OLD.get('news') or {}).items():
        if fresh(v): news[k] = v
    for k, v in (OLD.get('sc') or {}).items():
        if fresh(v): sc[k] = v
    picks = pick_list(D)
    LOG['stocks'] = len(picks)
    for s in picks:
        try:
            n = news_for(s); n['fetched'] = NOW.strftime('%Y-%m-%d'); news[s['sym']] = n; LOG['news_ok'] += 1
        except Exception as e:
            LOG['news_fail'] += 1; note(f"news {s['sym']}: {e}")
        time.sleep(1.2)
    try:
        import yfinance  # noqa: F401
        have_yf = True
    except Exception as e:
        have_yf = False; note(f'yfinance not installed: {e}')
    if have_yf:
        for s in picks:
            try:
                f = fund_for(s['sym'])
                if len(f) > 1:
                    f['fetched'] = NOW.strftime('%Y-%m-%d'); sc[s['sym']] = f; LOG['fund_ok'] += 1
                else:
                    LOG['fund_fail'] += 1
            except Exception as e:
                LOG['fund_fail'] += 1; note(f"fund {s['sym']}: {e}")
            time.sleep(1.0)
    LOG['finished'] = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    out = dict(asof=NOW.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime('%d %b %Y').lstrip('0'), news=news, sc=sc, log=LOG)
    json.dump(out, open(ap, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(json.dumps({k: v for k, v in LOG.items() if k != 'errors'}), 'errors:', LOG['errors'][:5])

if __name__ == '__main__':
    try: main()
    except Exception as e:
        print('news_fund failed:', e); sys.exit(0)
