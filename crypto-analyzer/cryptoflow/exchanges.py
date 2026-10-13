"""Public market-data clients for Binance and Bybit (no API keys needed).

Every client returns the same normalized shapes:

Bars (DataFrame, index = bar open time, UTC):
    open, high, low, close, volume, buy_volume
    `buy_volume` is taker (aggressive) buy volume. Bybit klines don't provide
    it, so it is NaN there and delta-based features need trade data.

Trades (DataFrame, index = trade time, UTC):
    price, qty, buyer_aggressor (True when the taker bought, i.e. hit the ask)
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import requests

INTERVAL_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
    "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "6h": 21_600_000,
    "12h": 43_200_000, "1d": 86_400_000,
}

_BYBIT_INTERVAL = {
    "1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60",
    "2h": "120", "4h": "240", "6h": "360", "12h": "720", "1d": "D",
}


class ExchangeError(RuntimeError):
    pass


class _Http:
    def __init__(self, base_url: str, timeout: float = 15.0, retries: int = 4):
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()

    def get(self, path: str, params: dict):
        delay = 1.0
        for attempt in range(self.retries + 1):
            try:
                r = self.session.get(self.base_url + path, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == self.retries:
                    raise ExchangeError(f"network error: {e}") from e
            else:
                # 429/418 = rate limited, 5xx = exchange trouble: back off and retry.
                if r.status_code in (418, 429) or r.status_code >= 500:
                    if attempt == self.retries:
                        raise ExchangeError(f"HTTP {r.status_code}: {r.text[:200]}")
                    wait = float(r.headers.get("Retry-After", delay))
                    time.sleep(wait)
                    delay *= 2
                    continue
                if r.status_code != 200:
                    raise ExchangeError(f"HTTP {r.status_code}: {r.text[:200]}")
                return r.json()
            time.sleep(delay)
            delay *= 2
        raise ExchangeError("unreachable")


def _check_interval(interval: str) -> int:
    if interval not in INTERVAL_MS:
        raise ValueError(f"unsupported interval {interval!r}; use one of {', '.join(INTERVAL_MS)}")
    return INTERVAL_MS[interval]


def _now_ms() -> int:
    return int(time.time() * 1000)


class Binance:
    """Binance spot (`market='spot'`) or USD-M perpetual futures (`market='futures'`)."""

    def __init__(self, market: str = "spot"):
        if market == "spot":
            self.http = _Http("https://api.binance.com")
            self.kline_path, self.trades_path = "/api/v3/klines", "/api/v3/aggTrades"
            self.kline_limit = 1000
        elif market == "futures":
            self.http = _Http("https://fapi.binance.com")
            self.kline_path, self.trades_path = "/fapi/v1/klines", "/fapi/v1/aggTrades"
            self.kline_limit = 1500
        else:
            raise ValueError("market must be 'spot' or 'futures'")
        self.name = f"binance-{market}"

    def bars(self, symbol: str, interval: str, start_ms: int, end_ms: int | None = None) -> pd.DataFrame:
        step = _check_interval(interval)
        end_ms = end_ms or _now_ms()
        rows, cursor = [], start_ms
        while cursor < end_ms:
            batch = self.http.get(self.kline_path, {
                "symbol": symbol.upper(), "interval": interval,
                "startTime": cursor, "endTime": end_ms, "limit": self.kline_limit,
            })
            if not batch:
                break
            rows.extend(batch)
            cursor = batch[-1][0] + step
            if len(batch) < self.kline_limit:
                break
        if not rows:
            raise ExchangeError(f"no bars returned for {symbol} {interval}")
        df = pd.DataFrame(rows).iloc[:, [0, 1, 2, 3, 4, 5, 9]]
        df.columns = ["time", "open", "high", "low", "close", "volume", "buy_volume"]
        df = df.astype({c: float for c in df.columns[1:]})
        df.index = pd.to_datetime(df.pop("time"), unit="ms", utc=True)
        df = df[~df.index.duplicated()]
        # Drop the still-forming bar: its values change and would leak into signals.
        return df[df.index + pd.Timedelta(milliseconds=step) <= pd.Timestamp(_now_ms(), unit="ms", tz="UTC")]

    def trades(self, symbol: str, start_ms: int, end_ms: int | None = None, max_trades: int = 500_000) -> pd.DataFrame:
        end_ms = end_ms or _now_ms()
        rows: list = []
        # Find the first trade (time windows are capped at 1h), then page by trade id.
        cursor = start_ms
        while not rows and cursor < end_ms:
            rows = self.http.get(self.trades_path, {
                "symbol": symbol.upper(), "startTime": cursor,
                "endTime": min(end_ms, cursor + 3_600_000 - 1), "limit": 1000,
            })
            cursor += 3_600_000
        while rows and rows[-1]["T"] < end_ms and len(rows) < max_trades:
            batch = self.http.get(self.trades_path, {
                "symbol": symbol.upper(), "fromId": rows[-1]["a"] + 1, "limit": 1000,
            })
            if not batch:
                break
            rows.extend(batch)
        if not rows:
            raise ExchangeError(f"no trades returned for {symbol}")
        df = pd.DataFrame(rows)
        df = df[df["T"] <= end_ms]
        out = pd.DataFrame({
            "price": df["p"].astype(float).values,
            "qty": df["q"].astype(float).values,
            # m = buyer is the maker -> the seller was aggressive.
            "buyer_aggressor": ~df["m"].astype(bool).values,
        }, index=pd.to_datetime(df["T"].values, unit="ms", utc=True))
        return out.sort_index()


class Bybit:
    """Bybit v5 (`category` = 'spot', 'linear' or 'inverse')."""

    def __init__(self, category: str = "linear"):
        self.http = _Http("https://api.bybit.com")
        self.category = category
        self.name = f"bybit-{category}"

    def bars(self, symbol: str, interval: str, start_ms: int, end_ms: int | None = None) -> pd.DataFrame:
        step = _check_interval(interval)
        end_ms = end_ms or _now_ms()
        rows, cursor_end = [], end_ms
        # Bybit returns newest first, so page backwards.
        while cursor_end > start_ms:
            res = self.http.get("/v5/market/kline", {
                "category": self.category, "symbol": symbol.upper(),
                "interval": _BYBIT_INTERVAL[interval],
                "start": start_ms, "end": cursor_end, "limit": 1000,
            })
            if res.get("retCode") != 0:
                raise ExchangeError(f"bybit: {res.get('retMsg')}")
            batch = res["result"]["list"]
            if not batch:
                break
            rows.extend(batch)
            oldest = int(batch[-1][0])
            if len(batch) < 1000 or oldest <= start_ms:
                break
            cursor_end = oldest - 1
        if not rows:
            raise ExchangeError(f"no bars returned for {symbol} {interval}")
        df = pd.DataFrame(rows).iloc[:, :6]
        df.columns = ["time", "open", "high", "low", "close", "volume"]
        df = df.astype({"time": "int64", **{c: float for c in df.columns[1:]}})
        df["buy_volume"] = np.nan
        df.index = pd.to_datetime(df.pop("time"), unit="ms", utc=True)
        df = df[~df.index.duplicated()].sort_index()
        return df[df.index + pd.Timedelta(milliseconds=step) <= pd.Timestamp(_now_ms(), unit="ms", tz="UTC")]

    def trades(self, symbol: str, start_ms: int | None = None, end_ms: int | None = None, max_trades: int = 1000) -> pd.DataFrame:
        # Bybit's public REST only exposes the most recent trades (max 1000 for spot,
        # more for derivatives); deep history lives in public.bybit.com CSV dumps.
        res = self.http.get("/v5/market/recent-trade", {
            "category": self.category, "symbol": symbol.upper(), "limit": min(max_trades, 1000),
        })
        if res.get("retCode") != 0:
            raise ExchangeError(f"bybit: {res.get('retMsg')}")
        df = pd.DataFrame(res["result"]["list"])
        if df.empty:
            raise ExchangeError(f"no trades returned for {symbol}")
        out = pd.DataFrame({
            "price": df["price"].astype(float).values,
            "qty": df["size"].astype(float).values,
            "buyer_aggressor": (df["side"] == "Buy").values,
        }, index=pd.to_datetime(df["time"].astype("int64").values, unit="ms", utc=True))
        return out.sort_index()


def get_exchange(name: str):
    """'binance', 'binance-futures', 'bybit' (linear perps) or 'bybit-spot'."""
    return {
        "binance": lambda: Binance("spot"),
        "binance-futures": lambda: Binance("futures"),
        "bybit": lambda: Bybit("linear"),
        "bybit-spot": lambda: Bybit("spot"),
    }[name]()
