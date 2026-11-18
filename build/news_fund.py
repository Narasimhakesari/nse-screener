#!/usr/bin/env python3
"""Nightly news headlines and company numbers for the top-ranked stocks.

Usage: python3 build/news_fund.py            (run from the repository root, after data.json is rebuilt)
Reads data.json and static.json, writes auto.json:
  news: latest Google News headlines per stock, with a tone judged from headline wording
  sc:   company numbers from Screener.in public pages (quarterly profit and sales vs a year earlier, P/E, ROE,
        ROCE, market cap, promoter/FII/DII holdings, latest exchange announcements); Yahoo Finance fills gaps
Anything that fails to download keeps its previous value (up to 60 days old). Never fails the build.
With GITHUB_TOKEN set (GitHub Actions, permission models: read), an AI model on GitHub Models reads the collected
results, exchange announcements and headlines for each stock and writes a short summary, tone and main risk.
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
    return out[:8]

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

# ---------- company numbers: Screener.in (public company pages, no login) ----------
def _txt(h):
    h = re.sub(r'<[^>]+>', ' ', h).replace('&nbsp;', ' ').replace('&amp;', '&')
    return re.sub(r'\s+', ' ', h).strip(' +')

def _num(t):
    t = t.replace(',', '').replace('%', '').replace('₹', '').replace('Cr.', '').strip()
    try: return float(t)
    except Exception: return None

def _section(html, sid):
    m = re.search(r'<section[^>]*id="%s"[^>]*>(.*?)</section>' % sid, html, re.S)
    return m.group(1) if m else ''

def _table(sec):
    m = re.search(r'<table[^>]*>(.*?)</table>', sec, re.S)
    if not m: return [], {}
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', m.group(1), re.S)
    head, body = [], {}
    for r in rows:
        cells = [_txt(c) for c in re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', r, re.S)]
        if not cells: continue
        if not head and re.search(r'<th', r): head = cells[1:]; continue
        body[cells[0]] = cells[1:]
    return head, body

def _ratio(html, name):
    m = re.search(r'<span class="name">\s*%s\s*</span>(.*?)</li>' % re.escape(name), html, re.S)
    if not m: return None
    nums = re.findall(r'<span class="number">([^<]*)</span>', m.group(1))
    return _num(nums[0]) if nums else None

def screener_for(sym):
    out = {}
    for path in ('consolidated/', ''):
        if path == '': time.sleep(5)
        html = fetch(f'https://www.screener.in/company/{urllib.parse.quote(sym)}/{path}', timeout=25).decode('utf-8', 'replace')
        head, body = _table(_section(html, 'quarters'))
        npr = next((body[k] for k in body if k.lower().startswith('net profit')), None)
        rev = next((body[k] for k in body if k.lower().split()[0] in ('sales', 'revenue')), None) if body else None
        if head and npr:
            break
    out.update(mcap=_ratio(html, 'Market Cap'), pe=_ratio(html, 'Stock P/E'), roce=_ratio(html, 'ROCE'), roe=_ratio(html, 'ROE'))
    if head and npr:
        last = head[-1]
        try:
            mon, yr = last.split()[0], int(last.split()[1])
            prev = f'{mon} {yr - 1}'
            if prev in head:
                i0, i1 = len(head) - 1, head.index(prev)
                v = dict(np=_num(npr[i0]), npYoY=_num(npr[i1]))
                if rev: v.update(sales=_num(rev[i0]), salesYoY=_num(rev[i1]))
                if v['np'] is not None and v['npYoY'] is not None:
                    out.update(v); out['q'] = last
        except Exception as e:
            note(f'screener quarters {sym}: {e}')
    sh_head, sh = _table(_section(html, 'shareholding'))
    for lab, key in (('Promoters', 'prom'), ('FIIs', 'fii'), ('DIIs', 'dii')):
        row = next((sh[k] for k in sh if k.startswith(lab)), None)
        if row and len(row) >= 2 and _num(row[-1]) is not None and _num(row[-2]) is not None:
            out[key] = [_num(row[-2]), _num(row[-1])]
    fil = []
    docs = _section(html, 'documents')
    m = re.search(r'Announcements.*?<ul[^>]*>(.*?)</ul>', docs, re.S)
    if m:
        for a in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', m.group(1), re.S)[:4]:
            inner = a[1]
            sub = re.search(r'<div[^>]*>(.*?)</div>', inner, re.S)
            title = _txt(re.sub(r'<div[^>]*>.*?</div>', '', inner, flags=re.S))
            detail = _txt(sub.group(1)) if sub else ''
            if title: fil.append(dict(t=title[:160], d=detail[:220], url=a[0] if a[0].startswith('http') else 'https://www.screener.in' + a[0]))
    if fil: out['filings'] = fil
    out = {k: v for k, v in out.items() if v is not None}
    if out: out['src'] = 'Screener.in'
    return out

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

# ---------- AI reading (GitHub Models, free with the workflow's GITHUB_TOKEN) ----------
MODELS = ['openai/gpt-4.1-mini', 'openai/gpt-4o-mini', 'openai/gpt-4.1', 'openai/gpt-4o']
SYSTEM = (
 "You are a careful equity research assistant for Indian (NSE) stocks. You are given facts collected today: "
 "the latest quarterly results, the company's own stock-exchange announcements (with one-line summaries), shareholding changes, "
 "and recent news headlines with dates and sources. Using ONLY these facts, judge what the recent news means for a shareholder. "
 "Rules: never invent numbers, events or dates; prefer exchange announcements and reported results over headlines; ignore "
 "generic market-wrap or 'stocks to watch' headlines that say nothing specific about the company; ignore routine filings "
 "(newspaper publications, trading-window closures, investor-meet intimations) unless they contain news. "
 "Reply with JSON only: {\"tone\": \"Positive\"|\"Mixed\"|\"Negative\"|\"Neutral\", "
 "\"summary\": \"2-3 plain-English sentences with the key facts and numbers\", "
 "\"watch\": \"one short risk a shareholder should know, or empty string\"}. "
 "Use Neutral when there is no meaningful company-specific news.")

def facts_for(stock, n, f):
    lines = [f"Company: {stock['name']} (NSE: {stock['sym']}), sector {stock['sector']}. Today: {NOW.strftime('%d %b %Y')}."]
    if f.get('np') is not None and f.get('npYoY') is not None:
        r = f"Results for quarter ending {f.get('q','?')} ({f.get('src','')}): net profit Rs {f['np']} cr vs Rs {f['npYoY']} cr a year earlier"
        if f.get('sales') is not None and f.get('salesYoY') is not None: r += f"; sales Rs {f['sales']} cr vs Rs {f['salesYoY']} cr"
        lines.append(r + '.')
    for k, lab in (('prom', 'Promoter'), ('fii', 'FII'), ('dii', 'DII')):
        if isinstance(f.get(k), list): lines.append(f"{lab} holding: {f[k][0]}% previous quarter -> {f[k][1]}% latest.")
    if f.get('pe') is not None: lines.append(f"P/E {f['pe']}, ROE {f.get('roe','?')}%.")
    for x in (f.get('filings') or [])[:5]: lines.append(f"Exchange announcement: {x['t']}. {x.get('d','')}")
    for x in (n.get('items') or [])[:8]: lines.append(f"Headline ({x.get('src','')}, {x.get('date','')}): {x['t']}")
    return '\n'.join(lines)

def ai_read(text, token):
    last = None
    for m in list(MODELS):
        body = json.dumps(dict(model=m, temperature=0.1, max_tokens=350, response_format={'type': 'json_object'},
                               messages=[dict(role='system', content=SYSTEM), dict(role='user', content=text)])).encode()
        req = urllib.request.Request('https://models.github.ai/inference/chat/completions', data=body, method='POST',
                                     headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json', 'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=60) as r: res = json.loads(r.read())
            out = json.loads(res['choices'][0]['message']['content'])
            if out.get('tone') not in ('Positive', 'Mixed', 'Negative', 'Neutral') or not out.get('summary'): raise ValueError(f'bad reply {out}')
            if m != MODELS[0]: MODELS.remove(m); MODELS.insert(0, m)
            return out, m
        except urllib.error.HTTPError as e:
            last = f'{m}: HTTP {e.code} {e.read()[:150]!r}'
            if e.code == 429: raise RuntimeError(last)
        except Exception as e:
            last = f'{m}: {e}'
    raise RuntimeError(last)

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
    LOG['screener_ok'] = LOG['screener_fail'] = LOG['screener_kept'] = 0
    def age_days(e):
        try: return (NOW.date() - dt.datetime.strptime(e.get('fetched', ''), '%Y-%m-%d').date()).days
        except Exception: return 999
    # Oldest (or missing) Screener numbers first; at most SCREENER_MAX pages a night, a few seconds apart.
    SCREENER_MAX, budget, blocked = 30, 30, False
    order = sorted(picks, key=lambda s: -(age_days(sc[s['sym']]) if sc.get(s['sym'], {}).get('src') == 'Screener.in' else 999))
    for s in order:
        prev = sc.get(s['sym'])
        have_recent = prev is not None and prev.get('src') == 'Screener.in' and age_days(prev) <= 6
        f = {}
        if (budget <= 0 or blocked) and prev is not None and prev.get('src') == 'Screener.in':
            LOG['screener_kept'] += 1; continue
        if have_recent:
            LOG['screener_kept'] += 1; continue
        if budget > 0 and not blocked:
            budget -= 1
            for attempt in (1, 2):
                try:
                    f = screener_for(s['sym'])
                    if f.get('np') is not None or f.get('pe') is not None: LOG['screener_ok'] += 1
                    else: LOG['screener_fail'] += 1; note(f"screener {s['sym']}: no numbers parsed")
                    break
                except Exception as e:
                    if '429' in str(e) and attempt == 1:
                        time.sleep(90); continue
                    LOG['screener_fail'] += 1; note(f"screener {s['sym']}: {e}")
                    if '429' in str(e): blocked = True
                    break
            time.sleep(5)
        if not f and prev is not None and prev.get('src') == 'Screener.in':
            LOG['screener_kept'] += 1; continue
        if have_yf:
            try:
                y = fund_for(s['sym'])
                for k, v in y.items():
                    if k == 'src': continue
                    if k in ('q', 'np', 'npYoY', 'sales', 'salesYoY'):
                        if f.get('np') is None and y.get('np') is not None: f[k] = v
                    elif f.get(k) is None: f[k] = v
                if not f.get('src') and len(y) > 1: f['src'] = 'Yahoo Finance'
            except Exception as e:
                note(f"yahoo {s['sym']}: {e}")
            time.sleep(0.8)
        if len(f) > 1:
            f['fetched'] = NOW.strftime('%Y-%m-%d'); sc[s['sym']] = f; LOG['fund_ok'] += 1
        else:
            LOG['fund_fail'] += 1
    token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_MODELS_TOKEN')
    LOG['ai_ok'] = LOG['ai_kept'] = LOG['ai_fail'] = 0
    if token:
        import hashlib
        for s in picks:
            sym = s['sym']; n = news.get(sym)
            if not n: continue
            text = facts_for(s, n, sc.get(sym, {}))
            h = hashlib.sha1(text.split('\n', 1)[-1].encode()).hexdigest()[:12]
            old = (OLD.get('news') or {}).get(sym, {})
            if old.get('ai') and old.get('ihash') == h:
                for k in ('tone', 'text', 'watch', 'ai', 'ihash', 'model'): n[k] = old.get(k, n.get(k))
                LOG['ai_kept'] += 1; continue
            try:
                out, model = ai_read(text, token)
                n.update(tone=out['tone'], text=out['summary'].strip(), watch=(out.get('watch') or '').strip(), ai=True, ihash=h, model=model)
                LOG['ai_ok'] += 1
            except Exception as e:
                LOG['ai_fail'] += 1; note(f'ai {sym}: {e}')
                if 'HTTP 429' in str(e): break
            time.sleep(4.5)
    else:
        note('no GITHUB_TOKEN: AI reading skipped')
    LOG['finished'] = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
    out = dict(asof=NOW.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30))).strftime('%d %b %Y').lstrip('0'), news=news, sc=sc, log=LOG)
    json.dump(out, open(ap, 'w'), ensure_ascii=False, separators=(',', ':'))
    print(json.dumps({k: v for k, v in LOG.items() if k != 'errors'}), 'errors:', LOG['errors'][:5])

if __name__ == '__main__':
    try: main()
    except Exception as e:
        print('news_fund failed:', e); sys.exit(0)
