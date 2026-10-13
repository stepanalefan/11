"""Signal generation. Every feature at bar i uses data up to and including bar i's
close; the backtester enters on bar i+1's open, so there's no look-ahead."""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .orderflow import bar_delta, rolling_value_area


def atr(bars: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = bars["close"].shift()
    tr = pd.concat([bars["high"] - bars["low"], (bars["high"] - prev).abs(), (bars["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


@dataclass
class Params:
    """Value-area rejection confirmed by order flow.

    Long:  price dips below the prior value-area low, closes back inside it,
           and aggressive buyers dominated the bar (delta ratio >= min_delta_ratio).
    Short: mirror image at the value-area high.
    Target is the prior POC; stop sits beyond the rejection wick plus an ATR buffer.
    """
    lookback: int = 96             # bars used for the rolling volume profile
    bins: int = 40
    value_pct: float = 0.70
    min_delta_ratio: float = 0.10  # delta / volume on the signal bar
    min_rr: float = 1.0            # skip trades whose reward:risk to POC is below this
    stop_atr: float = 0.5          # stop buffer beyond the wick, in ATRs
    atr_len: int = 14
    max_hold: int = 48             # bars before a time exit
    trend_filter: int = 0          # EMA length; >0 = only trade with the trend

    def to_dict(self):
        return asdict(self)


def compute_features(bars: pd.DataFrame, p: Params) -> pd.DataFrame:
    f = bars.copy()
    f["delta"] = bar_delta(bars)
    f["delta_ratio"] = f["delta"] / f["volume"].replace(0, np.nan)
    f["cvd"] = f["delta"].cumsum()
    f["atr"] = atr(bars, p.atr_len)
    f = f.join(rolling_value_area(bars, p.lookback, p.bins, p.value_pct))
    if p.trend_filter:
        f["ema"] = bars["close"].ewm(span=p.trend_filter, adjust=False).mean()
    return f


def generate_signals(bars: pd.DataFrame, p: Params) -> pd.DataFrame:
    """Adds columns: signal (+1 long / -1 short / 0), stop, target."""
    if bars["buy_volume"].isna().all():
        raise ValueError("these bars have no taker-buy volume (e.g. Bybit klines); "
                         "use Binance bars or build bars from trades")
    f = compute_features(bars, p)
    long_ = (f["low"] < f["val"]) & (f["close"] > f["val"]) & (f["delta_ratio"] >= p.min_delta_ratio)
    short = (f["high"] > f["vah"]) & (f["close"] < f["vah"]) & (f["delta_ratio"] <= -p.min_delta_ratio)
    if p.trend_filter:
        long_ &= f["close"] > f["ema"]
        short &= f["close"] < f["ema"]

    f["signal"] = 0
    f["stop"] = np.nan
    f["target"] = np.nan
    f.loc[long_, "signal"] = 1
    f.loc[long_, "stop"] = f["low"] - p.stop_atr * f["atr"]
    f.loc[long_, "target"] = f["poc"]
    f.loc[short, "signal"] = -1
    f.loc[short, "stop"] = f["high"] + p.stop_atr * f["atr"]
    f.loc[short, "target"] = f["poc"]

    # Reward:risk measured from the signal close (the real fill is next open).
    risk = (f["close"] - f["stop"]).abs()
    reward = (f["target"] - f["close"]) * f["signal"]
    bad = (f["signal"] != 0) & ((reward <= 0) | (reward < p.min_rr * risk))
    f.loc[bad, ["signal"]] = 0
    f.loc[bad, ["stop", "target"]] = np.nan
    return f
