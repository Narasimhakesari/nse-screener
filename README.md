# NSE Stock Agent: momentum trades with a 20% target and a 10% stop

A static website that runs one tested trading rule on NSE stocks and updates itself every weekday night.

**The rule.** Each evening, find stocks that have just entered the top 30 of the 300 most-traded NSE stocks (price Rs 10 or more, a year of history) by momentum: 12-month return skipping the last month, divided by volatility. "Just entered" means not in the top 30 in the 20 trading days before. Buy the strongest at the next open, at most 5 trades at a time, one fifth of your money each. Right after buying, place a Zerodha GTT OCO order: stop-loss trigger at the buy price −10%, target at +20%. Your broker sells automatically when either is hit. If neither is hit in 21 trading days, sell at the open on day 21 and delete the GTT.

**Why this rule** (`build/backtest_exits.py`, re-run nightly into `exits_bt.json`; `--grid` runs the full search). About 540 combinations were run as real portfolios from Sep 2022 to Nov 2026. They covered two entries (newly entered the top 30, or in the top 10), 5 or 10 trades at a time, targets from 8% to 40% or none, stops from 5% to 15% or trailing, and time limits of 21, 40 or 60 days. Buys were at the next open; the stop filled at the stop price or at the open if the stock gapped below it, and the target likewise; if both were touched in one day the stop was assumed to hit first; costs were 0.3% per round trip.

| Result (before tax) | Value |
|---|---|
| Yearly return | about 29% (26–36% with time limits of 18–25 days) |
| 300 most-traded stocks, equal weight | 18% |
| Worst fall | about −36% |
| Trades hitting the target / the stop / sold on day 21 | 17% / 24% / 59% |
| 2022–24 / 2025–26 | 29% vs the market's 30% / 33% vs 5.5% |

What the search showed:
- Close targets (8–15%) cut winners short and earned under 20% a year.
- Targets of 20% or more, or no target, did about equally well.
- The stop size (7–15%) mattered little.
- Five trades at a time beat ten.
- Skipping buys while market breadth is falling cut the return to about 11% a year.

For comparison, holding the monthly top 5 with no stop made 39% a year in the same period (`build/backtest_algos.py`, the strategy contest in `algos_bt.json`), but it holds stocks for months. Short-term capital gains on listed shares are taxed at 20%, which these figures do not include. The test covers about four years, and the exact figure depends on the settings, so expect a range. Not investment advice.

## Alerts (optional)
`build/notify.py` records every trade the rule signals in `history.json` (the page's live track record). It sends a message on evenings with something to do: what to buy at the next open, with its GTT stop and target prices; what to sell because its 21 days are up; and which trades hit the target or stop that day. It also sends a message when the market mood changes, and a summary every Friday. Add repository secrets (Settings → Secrets and variables → Actions):
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
