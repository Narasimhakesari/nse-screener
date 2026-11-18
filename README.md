# NSE Stock Agent: momentum trades

A static website that runs one tested rule on NSE stocks and updates itself every weekday night.

**The rule.** Every evening, rank the 300 most-traded NSE stocks (price Rs 10 or more, a year of history) by their 12-month return skipping the last month, divided by volatility. When a stock enters the top 30 and was not in it during the previous 20 trading days, buy it at the next day's open, with a stop-loss 10% below the buy price. Sell at the open 21 trading days later.

**The test** (`build/backtest_daily_momentum.py`, re-run nightly into `daily_bt.json`): from Sep 2022 to Nov 2026, after 0.3% costs, about +1.7% a trade, 48% won, about 14 trades a month, worst trade about −21% (gaps through the stop are filled at the open). Random stocks from the same 300 with the same exits made about +0.7%. Without the 20-day freshness rule: +1.1% and 45 trades a month. Selling when a stock leaves the top 30: about +0.2%. The 500 most-traded instead of 300: about the same per trade. Stocks entering straight into the top 10 made about +4% a trade but were too few (33) to rely on. The rule made about +2.5% a trade when market breadth was rising and +0.9% when falling, so the page shows market mood as a position-size warning. A once-a-month version (`build/backtest_momentum.py`) made about +2.1% a trade.

**Tested and dropped:** blends with trend, seasonality and chart setups (`build/backtest_styles.py`); a 200-day-average filter; target/stop swing exits and short holds (`build/backtest_trades.py`); trailing stops; a valuation penalty. Company results and news cannot be backtested here; they appear on each stock's page as information.

## Alerts (optional)
`build/notify.py` records every trade from launch in `history.json` (the page's live track record) and sends one evening message only when there is something to do: new buys for tomorrow's open, trades to sell at tomorrow's open, stop-losses hit, a change in market mood, and a Friday list of open trades. Add repository secrets (Settings → Secrets and variables → Actions):
- Telegram: `TELEGRAM_BOT_TOKEN` (create a bot with @BotFather) and `TELEGRAM_CHAT_ID` (send your bot a message, then open `https://api.telegram.org/bot<token>/getUpdates` and copy `chat.id`).
- Or the free ntfy app: `NTFY_TOPIC`, any long private name you also subscribe to in the app.

## Files
- `index.html`: the page.
- `data.json`: prices, indicators, factor scores, seasonality and evidence tests. Rebuilt every weekday.
- `static.json`: backtest report, news notes and fundamentals.
- `build/build.py`: rebuilds `data.json` from NSE's daily files (keeps about 5 years in `wd/bhav`).
- `auto.json`: nightly news headlines and company numbers for the top-ranked stocks (`build/news_fund.py`).
- `.github/workflows/refresh.yml`: runs everything every weekday at 8:37 pm IST and commits `data.json` and `auto.json`. The daily files are cached between runs, so only new days are downloaded.

## Setup
1. Push this folder to a public GitHub repository, including the hidden `.github` folder.
2. Settings → Pages → Source: "Deploy from a branch", branch `main`, folder `/ (root)`.
3. Actions tab → "Refresh screener data" → "Run workflow" once. The first run downloads about 5 years of files and takes longer; later runs take a minute or two.

## Updating fundamentals (monthly or after results season)
1. In Screener.in, open your saved screen and click **Export**.
2. Rename the file to `fundamentals.csv`.
3. On the repository page: **Add file → Upload files**, drop it in, **Commit changes**.
4. The refresh runs automatically and the site shows the new numbers.

The file needs an `NSE Code` column. Recognised columns: Market Capitalization, Price to Earning, Return on equity, Return on capital employed, Debt to equity, Sales growth 3Years, Profit growth 3Years, YOY Quarterly profit growth, YOY Quarterly sales growth, Promoter holding, Change in promoter holding, Pledged percentage, FII holding, Change in FII holding, DII holding, Change in DII holding.

## News and company numbers (automatic)
Every weekday night, after prices are rebuilt, `build/news_fund.py` takes the top-ranked stocks (about 70) and:
- collects their last 30 days of Google News headlines;
- reads each company's public Screener.in page: latest quarterly profit and sales against a year earlier, P/E, ROE, ROCE, market cap, promoter, FII and DII holdings, and the latest stock-exchange announcements. Yahoo Finance fills anything missing (such as debt to equity). About 60 pages a night, a few seconds apart.

Then it reads each stock's news from the facts: the reported quarterly results, the company's own stock-exchange announcements (routine notices skipped), and promoter and FII holding changes; headlines count only when there is nothing firmer. It writes a 2–3 sentence summary, a tone (Positive, Mixed, Negative or Neutral) and the main risk.

Optional: add a repository secret named `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions) and Claude will write the summaries from the same facts instead. Only stocks whose facts changed are re-read.

It writes `auto.json`, which the page merges with `static.json`: the newer news wins, and the nightly company numbers replace the uploaded `fundamentals.csv` figures when they are for the same or a newer quarter. Uploading `fundamentals.csv` is now optional. If a source fails, the previous values are kept for up to 60 days and the price refresh still publishes.

`build/agent_tasks.py` is optional: it lets someone add hand-written news notes (`todo` lists the stocks, `apply notes.json` merges them into `static.json`).

Not investment advice.
