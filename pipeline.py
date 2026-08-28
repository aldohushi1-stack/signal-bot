#!/usr/bin/env python3
"""
Paper-trading signal pipeline.

Runs once per trading day (via GitHub Actions). Fetches ~2 years of daily
prices, scores the universe on three well-documented price factors, and
maintains a simulated (paper) portfolio ledger. No real money is involved
anywhere in this code, and nothing it produces is investment advice.

Factors (all price-based, from the academic literature):
  momentum   12-1 month return  (Jegadeesh & Titman 1993 / Carhart 1997)
  low_vol    inverse 6-month daily volatility (Ang et al. 2006)
  reversal   negative 1-month return (Jegadeesh 1990)

Composite = 0.5*z(momentum) + 0.3*z(low_vol) + 0.2*z(reversal)

Portfolio rules:
  - $100,000 simulated starting cash, long-only, top 10 equal weight
  - Rebalance on the first run of each ISO week (usually Monday's close)
  - Buffer rule: an existing holding is kept if it is still ranked in the
    top 15, to limit churn
  - 5 bps (0.05%) simulated cost on every buy and sell - optimistic but
    not free; real trading would likely cost more
  - Benchmark: buy-and-hold SPY from the same start date

Honest limitations, stated up front:
  - Fills are assumed at the daily close price; no intraday slippage model
  - The universe is a hardcoded list of current large caps, so long-run
    results carry a mild survivorship/selection bias
  - Three price factors is a deliberately simple model; a live run of a
    few months tells you whether it has any edge, and it may well not
"""

import json
import math
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from tickers import UNIVERSE, BENCHMARK

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LEDGER_PATH = DATA / "ledger.json"
LATEST_PATH = DATA / "latest.json"
EQUITY_PATH = DATA / "equity.csv"

START_CASH = 100_000.0
N_HOLD = 10          # target number of positions
BUFFER_RANK = 15     # keep an existing holding while ranked <= this
COST_RATE = 0.0005   # 5 bps per trade side
MIN_ROWS = 300       # minimum valid price rows to keep a ticker

WEIGHTS = {"momentum": 0.5, "low_vol": 0.3, "reversal": 0.2}


# ---------------------------------------------------------------- data --

def fetch_prices() -> pd.DataFrame:
    """Adjusted daily closes, columns = tickers (incl. benchmark)."""
    if os.environ.get("MOCK_DATA"):
        return _mock_prices()
    import yfinance as yf

    tickers = UNIVERSE + [BENCHMARK]
    raw = yf.download(
        tickers, period="2y", interval="1d",
        auto_adjust=True, progress=False, group_by="column", threads=True,
    )
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    close = close.dropna(how="all")
    return close


def _mock_prices() -> pd.DataFrame:
    """Synthetic geometric random walks for offline testing."""
    rng = np.random.default_rng(int(os.environ.get("MOCK_SEED", "7")))
    idx = pd.bdate_range(end=os.environ.get("MOCK_END", date.today().isoformat()),
                         periods=520)
    cols = {}
    for t in UNIVERSE + [BENCHMARK]:
        drift = rng.normal(0.0003, 0.0004)
        vol = abs(rng.normal(0.015, 0.006)) + 0.004
        rets = rng.normal(drift, vol, len(idx))
        cols[t] = 100 * np.exp(np.cumsum(rets))
    return pd.DataFrame(cols, index=idx)


# ------------------------------------------------------------- scoring --

def zscore(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=0)
    if not sd or math.isnan(sd):
        return s * 0.0
    return (s - s.mean()) / sd


def score_universe(close: pd.DataFrame) -> pd.DataFrame:
    px = close[[c for c in close.columns if c != BENCHMARK]]
    px = px.dropna(axis=1, thresh=MIN_ROWS)
    dropped = sorted(set(UNIVERSE) - set(px.columns))

    latest = px.ffill().iloc[-1]
    p21 = px.ffill().iloc[-22]
    p252 = px.ffill().iloc[-253] if len(px) >= 253 else px.ffill().iloc[0]

    momentum = p21 / p252 - 1.0            # 12-1 month return
    rets = px.pct_change().iloc[-126:]
    vol = rets.std()
    low_vol = -vol                          # lower vol -> higher score
    reversal = -(latest / p21 - 1.0)        # fade last month's move

    df = pd.DataFrame({
        "price": latest,
        "momentum": momentum,
        "vol_6m_daily": vol,
        "ret_1m": latest / p21 - 1.0,
    })
    df["z_momentum"] = zscore(momentum)
    df["z_low_vol"] = zscore(low_vol)
    df["z_reversal"] = zscore(reversal)
    df["score"] = (WEIGHTS["momentum"] * df["z_momentum"]
                   + WEIGHTS["low_vol"] * df["z_low_vol"]
                   + WEIGHTS["reversal"] * df["z_reversal"])
    df = df.sort_values("score", ascending=False)
    df["rank"] = range(1, len(df) + 1)
    df.attrs["dropped"] = dropped
    return df


# -------------------------------------------------------------- ledger --

def load_ledger() -> dict:
    if LEDGER_PATH.exists():
        return json.loads(LEDGER_PATH.read_text())
    return {}


def init_ledger(as_of: str, spy_price: float) -> dict:
    return {
        "created": as_of,
        "cash": START_CASH,
        "positions": {},            # ticker -> {shares, cost_basis}
        "spy_units": START_CASH / spy_price,
        "last_rebalance": None,
        "last_rebalance_week": None,
        "total_costs": 0.0,
        "trades": [],               # recent trade log (capped)
    }


def iso_week(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def rebalance(ledger: dict, ranks: pd.DataFrame, prices: pd.Series,
              as_of: str) -> list:
    """Sell holdings outside the buffer, buy up to N_HOLD from the top."""
    trades = []
    rank_of = {t: int(r) for t, r in ranks["rank"].items()}

    # sells
    for t in list(ledger["positions"].keys()):
        r = rank_of.get(t)
        if r is None or r > BUFFER_RANK:
            pos = ledger["positions"].pop(t)
            px = float(prices.get(t, 0.0))
            if px > 0:
                gross = pos["shares"] * px
                cost = gross * COST_RATE
                ledger["cash"] += gross - cost
                ledger["total_costs"] += cost
                trades.append({"date": as_of, "side": "SELL", "ticker": t,
                               "shares": round(pos["shares"], 4),
                               "price": round(px, 2),
                               "reason": f"rank {r if r else 'n/a'} > {BUFFER_RANK}"})

    # buys
    slots = N_HOLD - len(ledger["positions"])
    if slots > 0:
        candidates = [t for t in ranks.index
                      if t not in ledger["positions"]][: 2 * N_HOLD]
        equity = portfolio_value(ledger, prices)
        target = equity / N_HOLD
        for t in candidates[:slots]:
            px = float(prices[t])
            spend = min(target, ledger["cash"] / max(slots, 1) * 0.999)
            spend = min(spend, ledger["cash"])
            if spend <= 0 or px <= 0:
                continue
            cost = spend * COST_RATE
            shares = (spend - cost) / px
            ledger["cash"] -= spend
            ledger["total_costs"] += cost
            ledger["positions"][t] = {"shares": shares, "cost_basis": px}
            trades.append({"date": as_of, "side": "BUY", "ticker": t,
                           "shares": round(shares, 4), "price": round(px, 2),
                           "reason": f"rank {rank_of[t]}"})
            slots -= 1

    ledger["last_rebalance"] = as_of
    ledger["last_rebalance_week"] = iso_week(date.fromisoformat(as_of))
    ledger["trades"] = (ledger["trades"] + trades)[-200:]
    return trades


def portfolio_value(ledger: dict, prices: pd.Series) -> float:
    v = ledger["cash"]
    for t, pos in ledger["positions"].items():
        v += pos["shares"] * float(prices.get(t, 0.0))
    return v


# ---------------------------------------------------------------- main --

def main() -> int:
    DATA.mkdir(exist_ok=True)
    close = fetch_prices()
    if close.empty or BENCHMARK not in close.columns:
        print("ERROR: no price data returned", file=sys.stderr)
        return 1

    as_of = close.index[-1].date().isoformat()
    ranks = score_universe(close)
    prices = ranks["price"]
    spy_price = float(close[BENCHMARK].ffill().iloc[-1])

    ledger = load_ledger()
    first_run = not ledger
    if first_run:
        ledger = init_ledger(as_of, spy_price)

    # skip weekends/holidays double-runs: if we already booked this date, exit
    if not first_run and ledger.get("last_mark") == as_of:
        print(f"Already processed {as_of}; nothing to do.")
        return 0

    week = iso_week(date.fromisoformat(as_of))
    trades = []
    if first_run or ledger.get("last_rebalance_week") != week:
        trades = rebalance(ledger, ranks, prices, as_of)

    equity = portfolio_value(ledger, prices)
    spy_equity = ledger["spy_units"] * spy_price
    ledger["last_mark"] = as_of
    LEDGER_PATH.write_text(json.dumps(ledger, indent=1))

    # append equity history
    header = not EQUITY_PATH.exists()
    with EQUITY_PATH.open("a") as f:
        if header:
            f.write("date,portfolio,spy\n")
        f.write(f"{as_of},{equity:.2f},{spy_equity:.2f}\n")

    top = ranks.head(25)
    latest = {
        "as_of": as_of,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "universe_size": int(len(ranks)),
        "dropped_tickers": ranks.attrs.get("dropped", []),
        "portfolio": {
            "equity": round(equity, 2),
            "cash": round(ledger["cash"], 2),
            "spy_equity": round(spy_equity, 2),
            "start_cash": START_CASH,
            "created": ledger["created"],
            "total_costs": round(ledger["total_costs"], 2),
            "positions": [
                {"ticker": t,
                 "shares": round(p["shares"], 4),
                 "cost_basis": round(p["cost_basis"], 2),
                 "price": round(float(prices.get(t, 0.0)), 2),
                 "value": round(p["shares"] * float(prices.get(t, 0.0)), 2),
                 "rank": int(ranks["rank"].get(t, -1))}
                for t, p in sorted(ledger["positions"].items())
            ],
        },
        "trades_today": trades,
        "rankings": [
            {"ticker": t,
             "rank": int(r["rank"]),
             "score": round(float(r["score"]), 3),
             "momentum_12_1": round(float(r["momentum"]), 4),
             "ret_1m": round(float(r["ret_1m"]), 4),
             "vol_6m_daily": round(float(r["vol_6m_daily"]), 4),
             "price": round(float(r["price"]), 2)}
            for t, r in top.iterrows()
        ],
        "method": "0.5*z(mom 12-1) + 0.3*z(low 6m vol) + 0.2*z(1m reversal); "
                  "top 10 equal weight, weekly rebalance, 5 bps/side, paper only",
    }
    LATEST_PATH.write_text(json.dumps(latest, indent=1))

    print(f"{as_of}: universe={len(ranks)} equity=${equity:,.2f} "
          f"spy=${spy_equity:,.2f} trades={len(trades)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
