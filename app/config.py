"""Settings loaded from the .env file in the project root."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Data source: "dhan" (default) or "yahoo" (free fallback, no login needed)
DATA_PROVIDER = os.getenv("DATA_PROVIDER", "dhan").strip().lower()

DHAN_CLIENT_ID = os.getenv("DHAN_CLIENT_ID", "").strip()
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "").strip()

# Risk settings (Blueprint: 10,000 capital, 0.5% risk per trade, 1:5 reward)
CAPITAL = float(os.getenv("CAPITAL", "10000"))
RISK_PCT = float(os.getenv("RISK_PCT", "0.5"))
REWARD_RATIO = float(os.getenv("REWARD_RATIO", "5"))

# Zone rules
MAX_BASE_CANDLES = int(os.getenv("MAX_BASE_CANDLES", "4"))   # max UOC candles in a zone base
# Stop loss margin beyond the UOC low/high, as a fraction of ATR (0.2 x ATR ~ Rs 1 on ONGC)
ZONE_SL_MARGIN_ATR = float(os.getenv("ZONE_SL_MARGIN_ATR", "0.2"))
# Entry margin beyond the UOC high/low (demand: entry above the UOC high), as a fraction of ATR
ZONE_ENTRY_MARGIN_ATR = float(os.getenv("ZONE_ENTRY_MARGIN_ATR", "0.2"))
# 1-2-4 rule: 1st candle >= 2x and 3rd candle >= 4x the tallest UOC candle (high - low)
ZONE_LEGIN_RATIO = float(os.getenv("ZONE_LEGIN_RATIO", "2"))
ZONE_LEGOUT_RATIO = float(os.getenv("ZONE_LEGOUT_RATIO", "4"))
ATR_PERIOD = int(os.getenv("ATR_PERIOD", "14"))
TREND_LOOKBACK = int(os.getenv("TREND_LOOKBACK", "7"))       # 7th candle clock rule
TREND_SIDEWAYS_DEG = float(os.getenv("TREND_SIDEWAYS_DEG", "15"))

# History to download
DAILY_HISTORY_DAYS = int(os.getenv("DAILY_HISTORY_DAYS", "1100"))   # ~3 years
INTRADAY_HISTORY_DAYS = int(os.getenv("INTRADAY_HISTORY_DAYS", "180"))
# Backtest uses a longer hourly history (Yahoo allows ~729 days of 60m candles)
BACKTEST_INTRADAY_DAYS = int(os.getenv("BACKTEST_INTRADAY_DAYS", "729"))

# Cache freshness (minutes)
DAILY_CACHE_MINUTES = int(os.getenv("DAILY_CACHE_MINUTES", "240"))
INTRADAY_CACHE_MINUTES = int(os.getenv("INTRADAY_CACHE_MINUTES", "30"))

# Weekly journal (forward test)
JOURNAL_FILE = BASE_DIR / "journal.db"
JOURNAL_EXPIRY_WEEKS = int(os.getenv("JOURNAL_EXPIRY_WEEKS", "8"))    # stop following an untouched zone
JOURNAL_COST_PCT = float(os.getenv("JOURNAL_COST_PCT", "0.2"))        # round-trip costs in % of entry value

CACHE_DIR = BASE_DIR / "cache"
CACHE_DIR.mkdir(exist_ok=True)
WATCHLIST_FILE = BASE_DIR / "watchlist.txt"
STATIC_DIR = BASE_DIR / "static"
