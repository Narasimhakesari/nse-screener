# NSE Stock Screener

A static site: `index.html` (the page), `data.json` (prices and signals, rebuilt daily), `static.json` (backtest report, news notes, Nifty 50 fundamentals).

`.github/workflows/refresh.yml` runs `build/build.py` every weekday at 8:37 pm IST and commits a fresh `data.json`.

## Setup
1. Create a public GitHub repository and upload everything in this folder, including the hidden `.github` folder.
2. Settings → Pages → Source: "Deploy from a branch", branch `main`, folder `/ (root)`.
3. Settings → Pages → Custom domain: enter your domain, then add the DNS records GitHub shows at your domain seller.
4. Actions tab → "Refresh screener data" → "Run workflow" once to test the daily refresh.

Not investment advice. Rules and limits are described at the bottom of the page.
