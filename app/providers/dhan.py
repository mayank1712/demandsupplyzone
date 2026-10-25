"""Dhan HQ API v2 historical data.

Docs: https://dhanhq.co/docs/v2/historical-data/
  POST /v2/charts/historical  -> daily candles
  POST /v2/charts/intraday    -> 1/5/15/25/60 minute candles (max 90 days per call)
"""
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from .. import config

BASE_URL = "https://api.dhan.co/v2"
SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
COLUMNS = ["open", "high", "low", "close", "volume"]


class DhanError(RuntimeError):
    pass


class DhanProvider:
    name = "dhan"

    def __init__(self, client_id: str, access_token: str):
        if not client_id or not access_token:
            raise DhanError(
                "Dhan credentials missing. Put DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN in the .env file "
                "(or set DATA_PROVIDER=yahoo to test without a broker)."
            )
        self.session = requests.Session()
        self.session.headers.update({
            "access-token": access_token,
            "client-id": client_id,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        self._security_ids: dict[str, str] | None = None
        self._last_call = 0.0

    # ---------- security id lookup ----------
    def _load_security_ids(self) -> dict[str, str]:
        path = config.CACHE_DIR / "dhan_scrip_master.csv"
        stale = not path.exists() or (time.time() - path.stat().st_mtime) > 24 * 3600
        if stale:
            r = requests.get(SCRIP_MASTER_URL, timeout=120)
            r.raise_for_status()
            path.write_bytes(r.content)
        df = pd.read_csv(path, low_memory=False)
        df = df[(df["SEM_EXM_EXCH_ID"] == "NSE") & (df["SEM_INSTRUMENT_NAME"] == "EQUITY")]
        if "SEM_SERIES" in df.columns:
            df = df[df["SEM_SERIES"] == "EQ"]
        return dict(zip(df["SEM_TRADING_SYMBOL"].astype(str).str.upper(),
                        df["SEM_SMST_SECURITY_ID"].astype(str)))

    def security_id(self, symbol: str) -> str:
        if self._security_ids is None:
            self._security_ids = self._load_security_ids()
        sid = self._security_ids.get(symbol.upper())
        if not sid:
            raise DhanError(f"Symbol {symbol} not found in Dhan scrip master (NSE EQ)")
        return sid

    # ---------- http ----------
    def _post(self, path: str, body: dict) -> dict:
        for attempt in range(4):
            wait = 0.25 - (time.time() - self._last_call)   # stay under the rate limit
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.time()
            r = self.session.post(BASE_URL + path, json=body, timeout=30)
            if r.status_code == 429:
                time.sleep(1 + attempt)
                continue
            if r.status_code == 401:
                if "subscription" in r.text.lower():
                    raise DhanError(f"Dhan data API not enabled on your plan: {r.text[:300]}. "
                                    "Subscribe to Data APIs on web.dhan.co, or set DATA_PROVIDER=yahoo.")
                raise DhanError("Dhan access token rejected (401). Tokens expire every 24h - generate a new one on web.dhan.co.")
            if r.status_code != 200:
                raise DhanError(f"Dhan {path} failed ({r.status_code}): {r.text[:300]}")
            return r.json()
        raise DhanError(f"Dhan {path}: rate limited, try again in a minute")

    @staticmethod
    def _to_df(data: dict) -> pd.DataFrame:
        if not data or not data.get("timestamp"):
            return pd.DataFrame(columns=COLUMNS)
        idx = (pd.to_datetime(data["timestamp"], unit="s", utc=True)
               .tz_convert("Asia/Kolkata").tz_localize(None))
        df = pd.DataFrame({c: data.get(c, [0] * len(idx)) for c in COLUMNS}, index=idx)
        return df.astype(float)

    # ---------- public ----------
    def daily(self, symbol: str, days: int) -> pd.DataFrame:
        today = date.today()
        body = {
            "securityId": self.security_id(symbol),
            "exchangeSegment": "NSE_EQ",
            "instrument": "EQUITY",
            "expiryCode": 0,
            "oi": False,
            "fromDate": (today - timedelta(days=days)).isoformat(),
            "toDate": (today + timedelta(days=1)).isoformat(),   # toDate is exclusive
        }
        df = self._to_df(self._post("/charts/historical", body))
        df.index = df.index.normalize()
        return df[~df.index.duplicated(keep="last")]

    def intraday(self, symbol: str, interval: int, days: int) -> pd.DataFrame:
        sid = self.security_id(symbol)
        end = datetime.now()
        start = end - timedelta(days=days)
        parts = []
        chunk_start = start
        while chunk_start < end:
            chunk_end = min(chunk_start + timedelta(days=89), end)
            body = {
                "securityId": sid,
                "exchangeSegment": "NSE_EQ",
                "instrument": "EQUITY",
                "interval": str(interval),
                "oi": False,
                "fromDate": chunk_start.strftime("%Y-%m-%d 09:15:00"),
                "toDate": chunk_end.strftime("%Y-%m-%d 15:30:00"),
            }
            parts.append(self._to_df(self._post("/charts/intraday", body)))
            chunk_start = chunk_end + timedelta(days=1)
        parts = [p for p in parts if not p.empty]
        if not parts:
            return pd.DataFrame(columns=COLUMNS)
        df = pd.concat(parts).sort_index()
        return df[~df.index.duplicated(keep="last")]
