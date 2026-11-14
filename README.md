# NSE Stock Screener

A static site: `index.html` (the page), `data.json` (prices and signals, rebuilt daily), `static.json` (backtest report, news notes, Nifty 50 fundamentals).

`.github/workflows/refresh.yml` runs `build/build.py` every weekday at 8:37 pm IST and commits a fresh `data.json`.

## Setup
1. Create a public GitHub repository and upload everything in this folder, including the hidden `.github` folder.
2. Settings → Pages → Source: "Deploy from a branch", branch `main`, folder `/ (root)`.
3. Settings → Pages → Custom domain: enter your domain, then add the DNS records GitHub shows at your domain seller.
4. Actions tab → "Refresh screener data" → "Run workflow" once to test the daily refresh.

Not investment advice. Rules and limits are described at the bottom of the page.

## Updating fundamentals (monthly or after results season)
1. In Screener.in, open your saved screen and click **Export**.
2. Rename the downloaded file to `fundamentals.csv`.
3. On this repository's page: **Add file → Upload files**, drop it in, **Commit changes** (replace the old one).
4. The refresh runs automatically within a few minutes and the site shows the new numbers.

The file needs an `NSE Code` column. Recognised columns: Market Capitalization, Price to Earning, Return on equity, Return on capital employed, Debt to equity, Sales growth 3Years, Profit growth 3Years, YOY Quarterly profit growth, YOY Quarterly sales growth, Promoter holding, Change in promoter holding, Pledged percentage, FII holding, Change in FII holding, DII holding, Change in DII holding. Missing columns are simply left blank.
