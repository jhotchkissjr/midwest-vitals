"""Synthetic data so the site can be previewed with no API keys or network.

Values are random walks around plausible levels. They are NOT real data;
the site shows a banner whenever dashboard.json was built with --sample.
"""
from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

from .transforms import to_points

CENTERS = {
    "%": 3.0, "count": 300, "2019 = 100": 100, "$ billions": -1700,
    "index": 0.0, "percentage points": 1.0, "thousands": 180,
}


def _center(chart: dict) -> float:
    cid, units = chart["id"], chart["units"]
    specific = {
        "unemployment_rate": 4.3, "participation": 63.5, "bank_count": 250, "cu_count": 180,
        "bank_ltd": 78, "cu_lts": 70, "bank_liquid_assets": 24, "bank_capital": 10.5,
        "cu_net_worth": 11, "bank_nim": 3.4, "bank_roa": 1.0, "cu_roa": 0.6,
        "bank_noncurrent": 0.5, "cu_delinquency": 0.9, "bank_fhlb_advances": 3.5,
        "bank_brokered": 4.0, "job_openings_rate": 5.0, "debt_gdp": 95, "deficit_gdp": -6,
        "rates": 3.5, "mortgage_rate": 5.5, "breakevens": 2.3, "curve": 0.3, "hy_spread": 3.8,
        "cfnai": 0.0, "nfci": -0.4,
    }
    if cid in specific:
        return specific[cid]
    for k, v in CENTERS.items():
        if k in units:
            return v
    return 1.0


def _freq(chart: dict, spec: dict) -> str:
    if chart["source"] in ("fdic", "ncua"):
        return "QS"
    sid = spec.get("id", "")
    if any(t in sid for t in ("GSP", "OTOT", "STHPI", "GDPC1", "FYGFGDQ")):
        return "QS"
    if sid.startswith("FY"):
        return "YS"
    if spec.get("transform") and "ann_rate" in spec["transform"]:
        return "QS"
    if sid in ("ICSA", "ILICLAIMS", "WIICLAIMS", "NFCI"):
        return "W-SAT"
    return "MS"


def fake_chart(cfg: dict, chart: dict, start: str) -> list[dict]:
    out = []
    center = _center(chart)
    scale = max(abs(center) * 0.04, 0.25)
    for i, spec in enumerate(chart["series"]):
        seed = zlib.crc32(f"{chart['id']}-{spec['geo']}-{i}".encode())
        rng = np.random.default_rng(seed)
        idx = pd.date_range(start, pd.Timestamp.today().normalize() - pd.Timedelta(days=45), freq=_freq(chart, spec))
        level = center * (1 + 0.06 * (i - 1)) if center else 0.15 * (i - 1)
        vals, x = [], level
        for _ in idx:
            x += rng.normal(0, scale * 0.35) - 0.08 * (x - level)
            vals.append(x)
        s = pd.Series(vals, index=idx)
        geo = spec["geo"]
        out.append({
            "geo": geo,
            "label": spec.get("label") or cfg["geos"][geo]["label"],
            "slot": cfg["geos"][geo]["slot"],
            "points": to_points(s, start),
            "source_id": spec.get("id") or chart["source"].upper(),
            "freq": "sample",
        })
    return out
