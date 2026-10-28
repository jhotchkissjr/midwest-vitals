"""State-level bank metrics from the FDIC BankFind Suite API.

API docs: https://banks.data.fdic.gov/docs/
Field definitions: https://banks.data.fdic.gov/docs/risview_properties.yaml

Pulls quarterly call report financials for every FDIC-insured institution,
then computes per-state and national metrics. Dollar fields from the FDIC are
in thousands. No API key is required.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)

URL = "https://banks.data.fdic.gov/api/financials"
CACHE = Path("data_cache/fdic_raw.csv.gz")
CACHE_MAX_AGE_HOURS = 20
COMMUNITY_MAX_ASSETS = 10_000_000  # $10B, in thousands
ACQUISITION_GROWTH = 1.30  # asset growth above 30% y/y is treated as an acquisition

# FDIC field -> meaning. pipeline.validate checks every one of these.
FIELDS = {
    "CERT": "FDIC certificate number",
    "REPDTE": "report date (YYYYMMDD)",
    "STALP": "state of headquarters (postal code)",
    "ASSET": "total assets",
    "DEP": "total deposits",
    "LNLSNET": "net loans and leases",
    "EQ": "total equity capital",
    "CHBAL": "cash and balances due from depository institutions",
    "SC": "total securities",
    "OTHBFHLB": "Federal Home Loan Bank advances",
    "BRO": "brokered deposits",
    "NIMY": "net interest margin, annualized YTD (%)",
    "ROA": "return on assets, annualized YTD (%)",
    "NCLNLSR": "noncurrent loans and leases to total loans (%)",
}


def fetch(start: str = "2014-01-01", states: list[str] | None = None, use_cache: bool = True) -> pd.DataFrame:
    """One row per institution per quarter since `start`."""
    if use_cache and CACHE.exists() and states is None:
        age_h = (time.time() - CACHE.stat().st_mtime) / 3600
        if age_h < CACHE_MAX_AGE_HOURS:
            log.info("FDIC: using cache (%.1f h old)", age_h)
            return pd.read_csv(CACHE, dtype={"REPDTE": str, "STALP": str})

    start_key = start.replace("-", "")
    filt = f"REPDTE:[{start_key} TO 99991231]"
    if states:
        filt += " AND STALP:(" + " OR ".join(f'"{s}"' for s in states) + ")"

    rows, offset, limit = [], 0, 10_000
    while True:
        params = {
            "filters": filt,
            "fields": ",".join(FIELDS),
            "limit": limit,
            "offset": offset,
            "sort_by": "REPDTE",
            "sort_order": "ASC",
            "format": "json",
        }
        r = requests.get(URL, params=params, timeout=120)
        r.raise_for_status()
        payload = r.json()
        batch = [d["data"] for d in payload.get("data", [])]
        rows.extend(batch)
        total = payload.get("meta", {}).get("total", 0)
        offset += limit
        log.info("FDIC: %s / %s rows", min(offset, total), total)
        if offset >= total or not batch:
            break
        time.sleep(0.5)

    df = pd.DataFrame(rows)
    if states is None:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(CACHE, index=False, compression="gzip")
    return df


def _metrics_for(group: pd.DataFrame) -> dict:
    g = group[group["ASSET"] > 0]
    comm = g[g["ASSET"] < COMMUNITY_MAX_ASSETS]
    dep = g["DEP"].where(g["DEP"] > 0)
    return {
        "count": len(g),
        "community_deposits": comm["DEP"].sum(),
        "community_loans": comm["LNLSNET"].sum(),
        "community_fhlb_share": 100 * comm["OTHBFHLB"].sum() / comm["ASSET"].sum(),
        "community_brokered_share": 100 * comm["BRO"].sum() / comm["DEP"].sum(),
        "median_ltd": (100 * g["LNLSNET"] / dep).median(),
        "median_liquid_assets": (100 * (g["CHBAL"] + g["SC"]) / g["ASSET"]).median(),
        "median_equity_assets": (100 * g["EQ"] / g["ASSET"]).median(),
        "median_nim": g["NIMY"].median(),
        "median_roa": g["ROA"].median(),
        "median_noncurrent": g["NCLNLSR"].median(),
    }


def _matched_growth(df: pd.DataFrame, col: str) -> pd.Series:
    """Y/y % growth in `col` for the same banks at both dates.

    The cohort is fixed a year earlier (banks under $10B then that still report
    now), so banks that grow past $10B, merge away or close do not drop out of
    one side of the comparison and drag growth down. Banks whose assets jumped
    more than ACQUISITION_GROWTH are left out, because an acquired bank's
    balances would otherwise count as growth.
    """
    by_date = {d: g.set_index("CERT") for d, g in df.groupby("date")}
    out = {}
    for d, now in by_date.items():
        then = by_date.get(d - pd.DateOffset(years=1))
        if then is None:
            continue
        small = then[(then["ASSET"] > 0) & (then["ASSET"] < COMMUNITY_MAX_ASSETS)]
        cohort = small.index.intersection(now.index)
        cohort = cohort[now.loc[cohort, "ASSET"] <= small.loc[cohort, "ASSET"] * ACQUISITION_GROWTH]
        base = small.loc[cohort, col].sum()
        if base > 0:
            out[d] = (now.loc[cohort, col].sum() / base - 1) * 100
    return pd.Series(out, dtype=float)


def compute_metrics(raw: pd.DataFrame, geos=("US", "IL", "WI")) -> pd.DataFrame:
    """Long frame: geo, date, metric, value."""
    df = raw.copy()
    df["date"] = pd.to_datetime(df["REPDTE"].astype(str), format="%Y%m%d")
    num = [c for c in FIELDS if c not in ("CERT", "REPDTE", "STALP")]
    df[num] = df[num].apply(pd.to_numeric, errors="coerce").fillna(0.0)

    out = []
    for geo in geos:
        sub = df if geo == "US" else df[df["STALP"] == geo]
        wide = pd.DataFrame({d: _metrics_for(g) for d, g in sub.groupby("date")}).T.sort_index()
        for col, yoy_col in [("DEP", "community_deposits_yoy"), ("LNLSNET", "community_loans_yoy")]:
            wide[yoy_col] = _matched_growth(sub, col).reindex(wide.index)
        long = wide.reset_index(names="date").melt(id_vars="date", var_name="metric", value_name="value")
        long["geo"] = geo
        out.append(long.dropna())
    return pd.concat(out, ignore_index=True)
