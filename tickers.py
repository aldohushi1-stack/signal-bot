# Universe: ~100 liquid US large caps (approximately the S&P 100).
# Hardcoded on purpose: the pipeline fails soft if a ticker stops trading
# (it is dropped when data is missing). Review this list a couple of times
# a year - index composition drifts.

UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "BRK-B",
    "JPM", "LLY", "V", "UNH", "XOM", "MA", "COST", "HD", "PG", "JNJ", "NFLX",
    "BAC", "ABBV", "CRM", "CVX", "KO", "WMT", "MRK", "AMD", "PEP", "TMO",
    "ADBE", "CSCO", "ORCL", "ACN", "MCD", "LIN", "ABT", "WFC", "IBM", "GE",
    "QCOM", "CAT", "DHR", "INTU", "TXN", "AMGN", "VZ", "PFE", "PM", "NEE",
    "DIS", "RTX", "SPGI", "HON", "UNP", "GS", "AXP", "BKNG", "LOW", "T",
    "ISRG", "MS", "BLK", "ELV", "SYK", "BMY", "C", "PLD", "MDT", "SCHW",
    "ADP", "VRTX", "SBUX", "CI", "LMT", "MMC", "GILD", "DE", "FI", "SO",
    "MO", "REGN", "ZTS", "BSX", "DUK", "CL", "EOG", "BX", "PANW", "CB",
    "TJX", "NOC", "ITW", "MU", "APH", "KLAC", "EMR", "PGR", "ETN", "CMCSA",
]

BENCHMARK = "SPY"
