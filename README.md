# NSE Stock Agent: hold the 5 strongest NSE stocks

A static website that runs one tested rule on NSE stocks and updates itself every weekday night.

**The rule.** On the last trading day of each month, after the close, rank the 300 most-traded NSE stocks (price Rs 10 or more, a year of history) by their 12-month return skipping the last month, divided by volatility. Hold the top 5 in equal amounts. At the next open, sell any holding that left the top 5 and buy the new ones. No stop-loss.

**Why this rule** (`build/backtest_algos.py`, re-run nightly into `algos_bt.json`): 11 strategy types were run as real portfolios with the same rules (at most 10 positions unless stated, next-open trades, gaps through stops filled at the open, 0.3% costs, textbook settings). From Sep 2022 to Nov 2026, before tax:

| Strategy | Yearly return | Worst fall |
|---|---|---|
| Momentum, monthly top 5 (this rule) | 38.9% | −33% |
| Momentum, monthly top 10 | 31.1% | −39% |
| Momentum, monthly top 20 | 28.3% | −30% |
| Momentum, daily fresh top-30 entries, 21 days, 10% stop | 21.4% | −36% |
| Momentum, monthly top 10 with a 10% stop | 20.5% | −35% |
| Benchmark: 300 most-traded, equal weight | 18.1% | −24% |
| Trend crossover, low volatility, 52-week breakout, RSI(2) mean reversion, 5-day reversal, delivery surge, volume-spike drift, 50-day breakout with target/stop, buying dips in leaders | −1% to 30%, none beat the market in both halves | |

Only momentum strategies beat the market in both halves of the period (before and after 1 Jan 2025). Stop-losses lowered momentum returns. Holding cash at month-ends when market breadth is falling cut the top-5 rule's worst fall to about −19% but its return to about 24% a year; the page shows this as a choice. Short-term capital gains on listed shares are taxed at 20%, which these figures do not include. The test covers about four years, including the strong 2023; past results do not predict future ones.

Earlier tests kept in the repo: `build/backtest_styles.py` (blended scores), `build/backtest_trades.py` (swing setups with target/stop), `build/backtest_momentum.py` and `build/backtest_daily_momentum.py` (momentum trades with stops).

Not investment advice.

## Alerts (optional)
`build/notify.py` keeps the live record of each review in `history.json` (the page's live track record) and sends a message on review evenings (what to sell and buy at the next open), when the market mood changes, and every Friday (the five holdings, flagging any that would be swapped if the review were that day). Add repository secrets (Settings → Secrets and variables → Actions):
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
