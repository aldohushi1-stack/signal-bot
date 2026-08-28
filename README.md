# signal-bot — paper-trading stock scanner

A small, honest paper-trading bot. Every US trading day, GitHub's servers
run `pipeline.py`, which downloads ~2 years of daily prices for ~100 US
large caps, ranks them on three academic price factors, and updates a
**simulated** $100,000 portfolio. Results are committed to the `data/`
folder, where Claude reads them each morning to update a live dashboard
and write a short brief.

**No real money is involved. Nothing here is investment advice.** The
whole point of running it on paper first is to find out — with real
out-of-sample data — whether these signals have any edge at all. They may
not, and the ledger will say so honestly.

## Setup (about 3 minutes)

1. Create a **new GitHub repository** (github.com/new). Name: `signal-bot`.
   Public or private both work. Don't add a README — leave it empty.
2. On the empty-repo page, click **"uploading an existing file"**, drag in
   the contents of this zip (all files and folders), and commit.
   - If the `.github` folder doesn't survive a drag-and-drop, use
     **Add file → Create new file**, type
     `.github/workflows/daily.yml` as the name, and paste that file's
     contents.
3. Go to the **Actions** tab → enable workflows if prompted → open
   **daily-signals** → **Run workflow** to do the first run manually.
   After ~2 minutes, a `data/` folder appears with the first signals.

From then on it runs automatically every trading day at 22:00 UTC
(after the US close). If the repo has no pushes for 60 days, GitHub
pauses scheduled workflows and shows a button to resume them.

## What the numbers mean

- **momentum (12-1)** — return from 12 months ago to 1 month ago.
  Persistent winners tend to keep winning (Jegadeesh & Titman 1993).
- **low vol** — 6-month daily volatility, inverted. Calmer stocks have
  historically had better risk-adjusted returns (Ang et al. 2006).
- **reversal** — last month's return, faded. Short-term extremes tend to
  snap back (Jegadeesh 1990).

Composite score = 0.5·z(momentum) + 0.3·z(low vol) + 0.2·z(reversal).

Portfolio: top 10 equal weight, rebalanced weekly with a top-15 buffer to
limit churn, 0.05% simulated cost per trade, benchmarked against
buy-and-hold SPY from the same start date.

## Known limitations (read this bit)

- Fills are assumed at the closing price; real execution would differ.
- The universe is a fixed list of today's large caps — mild selection
  bias. Edit `tickers.py` to change it.
- Three price factors is deliberately simple. The original inspiration
  document claimed institutional-grade alpha from this kind of setup;
  treat that claim as unproven until this ledger demonstrates otherwise.
- A few months of paper results is still a small sample. Don't read much
  into the first weeks either way.
