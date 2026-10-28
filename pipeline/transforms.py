"""Series transforms used by the config (see config/series.yaml)."""
from __future__ import annotations

import re

import pandas as pd

PERIODS_PER_YEAR = {"D": 252, "W": 52, "BW": 26, "M": 12, "Q": 4, "SA": 2, "A": 1}
RESAMPLE_RULE = {"M": "MS", "Q": "QS", "W": "W-SAT"}


def resample(s: pd.Series, rule: str | None) -> pd.Series:
    """Average a higher-frequency series down to M, Q or W."""
    if not rule:
        return s
    if rule not in RESAMPLE_RULE:
        raise ValueError(f"Unknown resample rule: {rule}")
    return s.resample(RESAMPLE_RULE[rule]).mean().dropna()


def _year_ago(s: pd.Series) -> pd.Series:
    """Value one year earlier, matched to the nearest date within 10 days.

    Works for daily, weekly, monthly, quarterly and annual data without
    needing to know the frequency.
    """
    target = s.index - pd.DateOffset(years=1)
    prev = s.sort_index().reindex(target, method="nearest", tolerance=pd.Timedelta(days=10))
    prev.index = s.index
    return prev


def _same_period_2019(s: pd.Series, freq: str) -> pd.Series:
    """For each date, the 2019 value in the same week, month or quarter of the year.

    Used to index series that are not seasonally adjusted, where a full-year
    2019 average would make seasonal lows look like record lows.
    """
    keys = {
        "W": lambda idx: idx.isocalendar().week.clip(upper=52).to_numpy(),
        "M": lambda idx: idx.month,
        "Q": lambda idx: idx.quarter,
    }
    if freq not in keys:
        raise ValueError(f"index_2019_seasonal needs W, M or Q data, got {freq!r}")
    key = keys[freq]
    y2019 = s.loc["2019-01-01":"2019-12-31"]
    if y2019.empty:
        raise ValueError("index_2019_seasonal needs data covering 2019")
    base = y2019.groupby(key(y2019.index)).mean()
    return pd.Series(base.reindex(key(s.index)).to_numpy(), index=s.index)


def apply(s: pd.Series, steps: list[str] | None, freq: str) -> pd.Series:
    """Apply transform steps in order. `freq` is a FRED frequency code."""
    s = s.sort_index().astype(float)
    for step in steps or ["level"]:
        if step == "level":
            continue
        elif step == "yoy":
            s = (s / _year_ago(s) - 1.0) * 100.0
        elif step == "ann_rate":
            ppy = PERIODS_PER_YEAR.get(freq)
            if ppy is None:
                raise ValueError(f"ann_rate needs a known frequency, got {freq!r}")
            s = ((s / s.shift(1)) ** ppy - 1.0) * 100.0
        elif step == "diff":
            s = s.diff()
        elif m := re.fullmatch(r"ma(\d+)", step):
            s = s.rolling(int(m.group(1))).mean()
        elif step == "roll12_sum":
            s = s.rolling(12).sum()
        elif step == "index_2019":
            base = s.loc["2019-01-01":"2019-12-31"].mean()
            if pd.isna(base) or base == 0:
                raise ValueError("index_2019 needs data covering 2019")
            s = s / base * 100.0
        elif step == "index_2019_seasonal":
            s = s / _same_period_2019(s, freq) * 100.0
        elif step.startswith("scale:"):
            s = s * float(step.split(":", 1)[1])
        else:
            raise ValueError(f"Unknown transform step: {step}")
    return s.dropna()


def to_points(s: pd.Series, start: str, digits: int = 3) -> list[list]:
    """Trim to the display window and convert to [[date, value], ...]."""
    s = s.loc[pd.Timestamp(start):]
    return [[d.strftime("%Y-%m-%d"), round(float(v), digits)] for d, v in s.items()]
