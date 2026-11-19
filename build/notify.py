#!/usr/bin/env python3
"""Nightly: keep the live record of the 20% target / 10% stop trades (history.json) and send alerts.

Run from the repository root after data.json, exits_bt.json and auto.json are rebuilt:  python3 build/notify.py
Messages: each evening with something to do (what to buy at the next open with its GTT prices, what to sell because its
21 days are up, which trades hit the target or stop today), a change in market mood, and a Friday summary of open
trades. Sent only if these repository secrets exist (Settings > Secrets and variables > Actions):
  TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID   (a bot made with @BotFather; your chat id)
  NTFY_TOPIC                                (a private topic name you subscribe to in the free ntfy app)
Optional: SITE_URL (defaults to https://<owner>.github.io/<repo>/).
"""
import json, os, sys, datetime as dt, urllib.request, urllib.parse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
J = lambda n, d=None: (json.load(open(os.path.join(ROOT, n))) if os.path.exists(os.path.join(ROOT, n)) else d)
D, AUTO, X = J('data.json'), J('auto.json', {}), J('exits_bt.json', {})
HP = os.path.join(ROOT, 'history.json')
H = J('history.json', {})
H.setdefault('days', []); H.setdefault('reviews', [])
H.setdefault('trades', [])
for k in ('months', 'sent'): H.pop(k, None)
BY = {s['sym']: s for s in D['stocks']}
nice = lambda d: dt.datetime.strptime(d, '%Y-%m-%d').strftime('%d %b %Y').lstrip('0')

def close_on(sym, day):
    s = BY.get(sym)
    if not s or day not in D['dates']: return None
    v = s['px'][D['dates'].index(day)]
    return v if v else None

def send(msg, title):
    print(msg); print('---')
    tok, chat, topic = (os.environ.get(k, '').strip() for k in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'NTFY_TOPIC'))
    if tok and chat:
        try:
            body = urllib.parse.urlencode(dict(chat_id=chat, text=msg[:4000], disable_web_page_preview='true')).encode()
            urllib.request.urlopen(urllib.request.Request(f'https://api.telegram.org/bot{tok}/sendMessage', data=body), timeout=30).read()
            print('sent to Telegram')
        except Exception as e: print('Telegram failed:', e)
    if topic:
        try:
            urllib.request.urlopen(urllib.request.Request(f'https://ntfy.sh/{urllib.parse.quote(topic)}', data=msg.encode(), method='POST',
                                                          headers={'Title': title}), timeout=30).read(); print('sent to ntfy')
        except Exception as e: print('ntfy failed:', e)
    if not (tok and chat) and not topic: print('No alert secrets set; message not sent.')

def record(since):
    """Add every trade the rule signals from `since` on; close them as the rule closes them."""
    L = X.get('live', {}); have = {(x['sym'], x['buy']): x for x in H['trades']}
    for o in L.get('open', []):
        if o['buyDate'] >= since and (o['sym'], o['buyDate']) not in have:
            x = dict(sym=o['sym'], buy=o['buyDate'], price=o['buy'], target=o['target'], stop=o['stop'], sellBy=o['sellBy'], sell=None, why=None, ret=None)
            H['trades'].append(x); have[(x['sym'], x['buy'])] = x
    for c in X.get('trades', []):
        if c['buy'] < since: continue
        x = have.get((c['sym'], c['buy']))
        if x is None:
            x = dict(sym=c['sym'], buy=c['buy'], price=None); H['trades'].append(x)
        x.update(sell=c['sell'], why=c['why'], ret=c['ret'])

def main():
    today = D['dates'][-1]; L = X.get('live') or {}; R = X.get('rule') or dict(target=.2, stop=.1, days=21, maxpos=5)
    if L.get('asof') != today: print('exits_bt.json is not from today; skipping alerts'); L = {}
    rising = bool(D['bt']['rising'])
    prevday = H['days'][-1] if H['days'] else None
    if prevday and prevday['date'] == today and prevday.get('v') == 5:
        print('already processed', today); return
    if prevday and prevday['date'] == today: H['days'].pop(); prevday = H['days'][-1] if H['days'] else None
    H['days'].append(dict(v=5, date=today, rising=rising, breadth=D['bt']['bnow']))
    H['days'] = H['days'][-500:]
    if not H.get('trades'): H['since'] = X.get('liveSince') or today
    H.setdefault('since', X.get('liveSince') or today)
    H.pop('reviews', None)
    if L: record(H['since'])
    json.dump(H, open(HP, 'w'), separators=(',', ':'))

    repo = os.environ.get('GITHUB_REPOSITORY', '')
    site = os.environ.get('SITE_URL') or (f"https://{repo.split('/')[0].lower()}.github.io/{repo.split('/')[1]}/" if '/' in repo else '')
    mood = f"Market mood: {'healthy' if rising else 'cautious'} ({D['bt']['bnow']}% of stocks above their 200-day average)."
    foot = ['', mood] + ([site] if site else []) + ['Rules-based, for education; not investment advice.']
    tp, sp = int(round(R['target'] * 100)), int(round(R['stop'] * 100))
    r05 = lambda v: round(round(v * 20) / 20, 2)
    msgs = []
    buys, opens, closed = L.get('buys', []), L.get('open', []), L.get('closedToday', [])
    sells = [o for o in opens if o.get('sellTomorrow')]
    if buys or sells or closed:
        T = [f'NSE trades for tomorrow, from the close on {nice(today)}', '']
        if buys:
            T.append(f"BUY at tomorrow's open (one fifth of your trading money each):")
            for b in buys:
                T.append(f"- {b['sym']} (closed Rs {b['close']:,.2f}). Then a GTT OCO: stop -{sp}%, target +{tp}% of your buy price. "
                         f"At Rs {b['close']:,.2f} that is stop Rs {r05(b['close']*(1-R['stop'])):,.2f}, target Rs {r05(b['close']*(1+R['target'])):,.2f}.")
            T.append('')
        if sells:
            T.append(f"SELL at tomorrow's open ({R['days']} trading days are up), then delete its GTT:")
            T += [f"- {o['sym']}: bought Rs {o['buy']:,.2f}, now Rs {o['close']:,.2f} ({(o['close']/o['buy']-1)*100:+.1f}%)" for o in sells]
            T.append('')
        if closed:
            T.append('Closed today:')
            T += [f"- {c['sym']} {'hit the target' if c['why']=='target' else 'hit the stop' if c['why']=='stop' else 'sold on day ' + str(R['days'])}: {c['ret']:+.1f}% after {c['days']} days" for c in closed]
            T.append('')
        T.append(f"Open trades: {len(opens)} of {R['maxpos']}.")
        msgs.append(('\n'.join(T + foot), f'NSE trades {nice(today)}'))
    if prevday and prevday.get('rising') != rising:
        msgs.append(('\n'.join([f"NSE trades: market mood changed to {'HEALTHY' if rising else 'CAUTIOUS'}, {nice(today)}",
                                'The rule keeps taking signals either way; in the test, skipping them in cautious markets did worse.'] + foot), 'Market mood changed'))
    if dt.datetime.strptime(today, '%Y-%m-%d').weekday() == 4 and opens:
        T = [f'NSE trades: weekly summary, {nice(today)}', '']
        for o in opens:
            T.append(f"- {o['sym']}: {(o['close']/o['buy']-1)*100:+.1f}% since {nice(o['buyDate'])}, stop Rs {o['stop']:,.2f}, target Rs {o['target']:,.2f}, sell by {nice(o['sellBy'])}")
        neg = [f"{o['sym']}: {AUTO['news'][o['sym']]['watch']}" for o in opens if (AUTO.get('news') or {}).get(o['sym'], {}).get('tone') == 'Negative' and AUTO['news'][o['sym']].get('watch')]
        if neg: T += ['', 'Negative news:'] + neg
        done = [x for x in H['trades'] if x.get('ret') is not None]
        if done: T += ['', f"Live record since {nice(H['since'])}: {len(done)} closed, average {sum(x['ret'] for x in done)/len(done):+.1f}% a trade."]
        msgs.append(('\n'.join(T + foot), f'Weekly summary {nice(today)}'))
    if not msgs: print('Nothing to report today.')
    for m, t_ in msgs: send(m, t_)

if __name__ == '__main__':
    try: main()
    except Exception as e: print('notify failed:', e); sys.exit(0)
