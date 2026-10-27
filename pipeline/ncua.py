"""State-level credit union metrics from NCUA quarterly call report files.

Source page: https://ncua.gov/analysis/credit-union-corporate-call-report-data/quarterly-data
Each quarter is a zip of comma-delimited text files:
  FOICU.txt      one row per credit union, including STATE
  FS220*.txt     balance sheet and income accounts (ACCT_xxx columns)
  AcctDesc.txt   account code descriptions

Zips are large, so processed quarterly summaries are stored in
data_cache/ncua_summary.csv (commit this file) and only missing quarters are
downloaded on each run.

Verify account codes with:
  python -m pipeline.ncua describe 2025-06 "net worth"
"""
from __future__ import annotations

import io
import logging
import sys
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from .transforms import _year_ago

log = logging.getLogger(__name__)

URL = "https://ncua.gov/files/publications/analysis/call-report-data-{y}-{m:02d}.zip"
SUMMARY = Path("data_cache/ncua_summary.csv")
GEOS = ("US", "IL", "WI")

# NCUA 5300 account codes. Confirm with `describe` if NCUA changes the form.
ACCTS = {
    "assets": "ACCT_010",        # total assets
    "shares": "ACCT_018",        # total shares and deposits
    "loans": "ACCT_025B",        # total loans and leases (amount)
    "net_worth": "ACCT_997",     # total net worth
    "net_income": "ACCT_661A",   # net income, year to date
    "delinquent": "ACCT_041B",   # total delinquent loans and leases (amount)
}


def _quarters(start: str) -> list[tuple[int, int]]:
    s = pd.Timestamp(start)
    today = date.today()
    out, y, m = [], s.year, ((s.month - 1) // 3 + 1) * 3
    while (y, m) <= (today.year, today.month):
        out.append((y, m))
        m += 3
        if m > 12:
            y, m = y + 1, 3
    return out


def _download(y: int, m: int) -> zipfile.ZipFile | None:
    url = URL.format(y=y, m=m)
    r = requests.get(url, timeout=300)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return zipfile.ZipFile(io.BytesIO(r.content))


def _read(z: zipfile.ZipFile, name: str) -> pd.DataFrame:
    df = pd.read_csv(z.open(name), encoding="latin-1", low_memory=False)
    df.columns = [c.strip().upper() for c in df.columns]
    return df


def _find(z: zipfile.ZipFile, prefix: str) -> list[str]:
    return [n for n in z.namelist() if Path(n).name.upper().startswith(prefix.upper())]


def summarize_quarter(z: zipfile.ZipFile, y: int, m: int) -> pd.DataFrame:
    foicu = _read(z, _find(z, "FOICU")[0])[["CU_NUMBER", "STATE"]]
    needed = set(ACCTS.values())
    accts = foicu[["CU_NUMBER"]].copy()
    for name in sorted(_find(z, "FS220")):
        fs = _read(z, name)
        cols = [c for c in fs.columns if c in needed and c not in accts.columns]
        if cols:
            accts = accts.merge(fs[["CU_NUMBER", *cols]], on="CU_NUMBER", how="left")
    missing = needed - set(accts.columns)
    if missing:
        raise KeyError(f"NCUA {y}-{m:02d}: account codes not found: {sorted(missing)}")

    df = foicu.merge(accts, on="CU_NUMBER")
    df = df.rename(columns={v: k for k, v in ACCTS.items()})
    df = df[df["assets"] > 0]
    ann = 12 / m  # net income is year to date

    rows = []
    for geo in GEOS:
        g = df if geo == "US" else df[df["STATE"].str.strip() == geo]
        shares = g["shares"].where(g["shares"] > 0)
        rows.append({
            "date": f"{y}-{m:02d}-01",
            "geo": geo,
            "count": len(g),
            "shares": g["shares"].sum(),
            "loans": g["loans"].sum(),
            "median_lts": (100 * g["loans"] / shares).median(),
            "median_net_worth": (100 * g["net_worth"] / g["assets"]).median(),
            "median_roa": (100 * g["net_income"] * ann / g["assets"]).median(),
            "delinquency_rate": 100 * g["delinquent"].sum() / g["loans"].sum(),
        })
    return pd.DataFrame(rows)


def update_summary(start: str = "2014-01-01") -> pd.DataFrame:
    have = pd.read_csv(SUMMARY) if SUMMARY.exists() else pd.DataFrame(columns=["date"])
    done = set(have["date"])
    new = []
    for y, m in _quarters(start):
        key = f"{y}-{m:02d}-01"
        if key in done:
            continue
        log.info("NCUA: fetching %s", key)
        z = _download(y, m)
        if z is None:
            log.info("NCUA: %s not published yet", key)
            continue
        new.append(summarize_quarter(z, y, m))
    if new:
        have = pd.concat([have, *new], ignore_index=True).sort_values(["date", "geo"])
        SUMMARY.parent.mkdir(parents=True, exist_ok=True)
        have.to_csv(SUMMARY, index=False)
    return have


def compute_metrics(summary: pd.DataFrame) -> pd.DataFrame:
    """Long frame: geo, date, metric, value."""
    df = summary.copy()
    df["date"] = pd.to_datetime(df["date"])
    out = []
    for geo, g in df.groupby("geo"):
        g = g.set_index("date").sort_index()
        g["shares_yoy"] = (g["shares"] / _year_ago(g["shares"]) - 1) * 100
        g["loans_yoy"] = (g["loans"] / _year_ago(g["loans"]) - 1) * 100
        long = g.drop(columns="geo").reset_index().melt(id_vars="date", var_name="metric", value_name="value")
        long["geo"] = geo
        out.append(long.dropna())
    return pd.concat(out, ignore_index=True)


def describe(period: str, keyword: str) -> None:
    """Print account descriptions matching a keyword, e.g. describe('2025-06', 'net worth')."""
    y, m = map(int, period.split("-"))
    z = _download(y, m)
    if z is None:
        sys.exit(f"No NCUA file for {period}")
    desc = _read(z, _find(z, "ACCTDESC")[0])
    mask = desc.astype(str).apply(lambda col: col.str.contains(keyword, case=False)).any(axis=1)
    with pd.option_context("display.max_colwidth", 120, "display.width", 200):
        print(desc[mask].to_string(index=False))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "describe":
        describe(sys.argv[2], sys.argv[3])
    else:
        sys.exit('usage: python -m pipeline.ncua describe YYYY-MM "keyword"')
