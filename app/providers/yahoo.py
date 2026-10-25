"""Free fallback provider (Yahoo Finance via yfinance). Use DATA_PROVIDER=yahoo.
Good for testing without a Dhan token. Intraday history is limited to ~730 days."""
import pandas as pd

COLUMNS = ["open", "high", "low", "close", "volume"]


class YahooProvider:
    name = "yahoo"

    @staticmethod
    def _clean(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=COLUMNS)
        df = df.rename(columns=str.lower)[COLUMNS].astype(float)
        if df.index.tz is not None:
            df.index = df.index.tz_convert("Asia/Kolkata").tz_localize(None)
        return df[~df.index.duplicated(keep="last")]

    def daily(self, symbol: str, days: int) -> pd.DataFrame:
        import yfinance as yf
        df = yf.Ticker(f"{symbol}.NS").history(period=f"{days}d", interval="1d", auto_adjust=False)
        df = self._clean(df)
        if not df.empty:
            df.index = df.index.normalize()
        return df

    def intraday(self, symbol: str, interval: int, days: int) -> pd.DataFrame:
        import yfinance as yf
        df = yf.Ticker(f"{symbol}.NS").history(period=f"{min(days, 729)}d",
                                              interval=f"{interval}m", auto_adjust=False)
        return self._clean(df)
