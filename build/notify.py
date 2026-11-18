#!/usr/bin/env python3
"""Nightly: record every daily momentum trade (history.json) and send an alert when there is something to do.

Run from the repository root after data.json and auto.json are rebuilt:  python3 build/notify.py
A message goes out only when there is something to act on: new buy signals for tomorrow's open, trades to sell at
tomorrow's open, stop-losses hit today, a change in market mood, and a Friday summary of open trades. Sent only if these
repository secrets exist (Settings > Secrets and variables > Actions):
  TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID   (a bot made with @BotFather; your chat id)
  NTFY_TOPIC                                (a private topic name you subscribe to in the free ntfy app)
Optional: SITE_URL (defaults to https://<owner>.github.io/<repo>/).
"""
import json, os, sys, datetime as dt, urllib.request, urllib.parse

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
J = lambda n, d=None: (json.load(open(os.path.join(ROOT, n))) if os.path.exists(os.path.join(ROOT, n)) else d)
D, AUTO = J('data.json'), J('auto.json', {})
HP = os.path.join(ROOT, 'history.json')
H = J('history.json', {})
H.setdefault('days', []); H.setdefault('trades', {})
BY = {s['sym']: s for s in D['stocks']}
nice = lambda d: dt.datetime.strptime(d, '%Y-%m-%d').strftime('%d %b').lstrip('0')

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

def main():
    today = D['dates'][-1]; M = D.get('mom') or {}; T = M.get('trades', [])
    rising = bool(D['bt']['rising'])
    prevday = H['days'][-1] if H['days'] else None
    if prevday and prevday['date'] == today and prevday.get('v') == 3:
        print('already processed', today); return
    if prevday and prevday['date'] == today: H['days'].pop(); prevday = H['days'][-1] if H['days'] else None
    H['days'].append(dict(v=3, date=today, rising=rising, breadth=D['bt']['bnow'], top30=M.get('top30Now', [])))
    H['days'] = H['days'][-500:]
    H.setdefault('since', today)
    for t in T:   # live record: trades signalled from launch on
        if t['signal'] >= H['since']:
            H['trades'][f"{t['sym']}|{t['signal']}"] = {k: t.get(k) for k in ('sym', 'signal', 'rank', 'buyDate', 'buy', 'stop', 'status', 'exitDate', 'exit', 'sellBy')}
    H.pop('months', None); H.pop('sent', None)
    json.dump(H, open(HP, 'w'), separators=(',', ':'))

    repo = os.environ.get('GITHUB_REPOSITORY', '')
    site = os.environ.get('SITE_URL') or (f"https://{repo.split('/')[0].lower()}.github.io/{repo.split('/')[1]}/" if '/' in repo else '')
    mood = f"Market mood: {'healthy' if rising else 'cautious'} ({D['bt']['bnow']}% of stocks above their 200-day average)."
    L = [f'NSE momentum, {nice(today)} close']
    act = False
    if prevday and prevday.get('rising') != rising:
        L += ['', f">> Market mood changed to {'HEALTHY: normal position sizes' if rising else 'CAUTIOUS: consider half-size positions; keep existing stops'}."]; act = True
    new = [t for t in T if t['status'] == 'new']
    if new:
        L += ['', f"BUY at tomorrow's open (stop 10% below your price, sell by the date shown):"]
        L += [f"- {t['sym']}: closed Rs {BY[t['sym']]['close']:,.2f}, stop about Rs {BY[t['sym']]['close']*0.9:,.2f}, sell by {nice(t['sellBy'])}{'  (strongest: rank ' + str(t['rank']) + ')' if t['rank'] <= 10 else ''}" for t in new if t['sym'] in BY]
        if not rising: L.append('Market is cautious: in the test these made about a third as much. Consider half size.')
        act = True
    sell = [t for t in T if t.get('sellTomorrow')]
    if sell:
        L += ['', "SELL at tomorrow's open (month is up):"]
        L += [f"- {t['sym']}: bought Rs {t['buy']:,.2f}, now Rs {BY[t['sym']]['close']:,.2f} ({(BY[t['sym']]['close']/t['buy']-1)*100:+.1f}%)" for t in sell if t['sym'] in BY]
        act = True
    hits = [t for t in T if t['status'] == 'stopped' and t.get('exitDate') == today]
    if hits:
        L += ['', 'STOP-LOSS hit today:'] + [f"- {t['sym']}: bought Rs {t['buy']:,.2f}, sold near Rs {t['exit']:,.2f} ({(t['exit']/t['buy']-1)*100:+.1f}%)" for t in hits]
        L.append('If your stop order did not fill, sell at the next open.'); act = True
    if dt.datetime.strptime(today, '%Y-%m-%d').weekday() == 4:
        op = [t for t in T if t['status'] == 'open' and t['sym'] in BY]
        if op:
            L += ['', f'Open trades ({len(op)}):'] + [f"- {t['sym']}: {(BY[t['sym']]['close']/t['buy']-1)*100:+.1f}%, stop Rs {t['stop']:,.2f}, sell by {nice(t['sellBy'])}" for t in op]
            neg = [f"{t['sym']}: {AUTO['news'][t['sym']]['watch']}" for t in op if (AUTO.get('news') or {}).get(t['sym'], {}).get('tone') == 'Negative' and AUTO['news'][t['sym']].get('watch')]
            if neg: L += ['', 'Negative news:'] + neg
            act = True
    if not act: print('Nothing to report today.'); return
    L += ['', mood] + ([site] if site else []) + ['Rules-based, for education; not investment advice.']
    send('\n'.join(L), f"NSE momentum {nice(today)}")

if __name__ == '__main__':
    try: main()
    except Exception as e: print('notify failed:', e); sys.exit(0)
