#!/usr/bin/env python3
"""Alerts for the NIFTY weekly trade, from options_live.json. Run from the repository root after options_daily.py.

Sends: the evening before the entry day (what to place at 3:15 pm tomorrow), on the entry evening (what was placed,
at closing prices), and on expiry evening (the week's result). Uses the same secrets as the stock alerts:
TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, or NTFY_TOPIC; optional SITE_URL.
"""
import os, json, urllib.request, urllib.parse, datetime as dt

L = json.load(open('options_live.json'))
STATE = 'options_alerts.json'
try: S = json.load(open(STATE))
except Exception: S = {}

def send(msg, title):
    print(msg); print('---')
    tok, chat, topic = (os.environ.get(k, '').strip() for k in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'NTFY_TOPIC'))
    if tok and chat:
        try:
            body = urllib.parse.urlencode(dict(chat_id=chat, text=msg[:4000], disable_web_page_preview='true')).encode()
            urllib.request.urlopen(urllib.request.Request(f'https://api.telegram.org/bot{tok}/sendMessage', data=body), timeout=30).read()
        except Exception as e: print('Telegram failed:', e)
    if topic:
        try:
            urllib.request.urlopen(urllib.request.Request(f'https://ntfy.sh/{urllib.parse.quote(topic)}', data=msg.encode(), method='POST',
                                                          headers={'Title': title}), timeout=30).read()
        except Exception as e: print('ntfy failed:', e)
    if not (tok and chat) and not topic: print('No alert secrets set; message not sent.')

nice = lambda s: dt.datetime.strptime(s, '%Y-%m-%d').strftime('%a %d %b')
repo = os.environ.get('GITHUB_REPOSITORY', '')
site = os.environ.get('SITE_URL') or (f"https://{repo.split('/')[0].lower()}.github.io/{repo.split('/')[1]}/" if '/' in repo else '')
foot = ['', 'Rules-based, for education; not investment advice. Options can lose more than you expect.'] + ([site] if site else [])
W, asof = L.get('week') or {}, L['asof']
key = lambda k: f"{k}:{asof}"

if W and W.get('state') == 'tomorrow' and not S.get(key('tomorrow')):
    st = W['strikes']
    T = [f"NIFTY weekly trade TOMORROW ({nice(W['entry'])}) at about 3:15 pm, for the {nice(W['expiry'])} expiry", '',
         'Pick strikes from NIFTY at 3:15 pm tomorrow. At today\'s close (NIFTY ' + f"{W['spot']:,.0f}" + ') they would be:',
         f"  BUY  {st['call_wing']:.0f} CE  (about 4% above)",
         f"  BUY  {st['put_wing']:.0f} PE  (about 4% below)",
         f"  SELL {st['atm']:.0f} CE  (at the money)",
         f"  SELL {st['atm']:.0f} PE  (at the money)",
         f"1 lot = {W['lot']} units each. Place the two buys first, then the two sells.",
         f"Hold until 3:15 pm on {nice(W['expiry'])}, then close all four legs."]
    if W.get('credit'):
        T.append(f"At today's prices: credit about Rs {W['credit']*W['lot']:,.0f} per lot; the most you can lose is about Rs {W['max_loss']:,.0f} per lot.")
    send('\n'.join(T + foot), 'NIFTY trade tomorrow'); S[key('tomorrow')] = 1

if W and W.get('state') == 'entered_today' and W.get('entered') and not S.get(key('entered')):
    E = W['entered']
    T = [f"NIFTY weekly trade placed today ({nice(W['entry'])}) for the {nice(W['expiry'])} expiry, at closing prices:"]
    T += [f"  {l['action'].upper():4s} {l['k']:.0f} {l['typ']} at {l['price']:.2f}" for l in E['legs']]
    if E.get('credit'): T.append(f"Credit {E['credit']:.1f} points = Rs {E['credit']*W['lot']:,.0f} per lot. Close all legs at 3:15 pm on {nice(W['expiry'])}.")
    send('\n'.join(T + foot), 'NIFTY trade placed'); S[key('entered')] = 1

for r in L.get('record', []):
    if r['expiry'] == asof and not S.get(key('result')):
        send('\n'.join([f"NIFTY weekly trade closed ({nice(r['expiry'])}): {r['pnl_points']:+.1f} points = Rs {r['pnl_rupees']:+,.0f} per lot after costs",
                        f"Sold {r['atm']:.0f} straddle with {r['wings'][0]:.0f}/{r['wings'][1]:.0f} wings on {nice(r['entry'])}; NIFTY {r['spot_entry']:,.0f} -> {r['spot_expiry']:,.0f}."] + foot),
             'NIFTY trade result')
        S[key('result')] = 1

json.dump(dict(list(S.items())[-200:]), open(STATE, 'w'))
