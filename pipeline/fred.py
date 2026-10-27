"""Minimal FRED API client with retries and an in-run cache.

Docs: https://fred.stlouisfed.org/docs/api/fred/
Free API key: https://fredaccount.stlouisfed.org/apikeys
"""
from __future__ import annotations

import os
import time
from functools import lru_cache

import pandas as pd
import requests

BASE = "https://api.stlouisfed.org/fred"
SESSION = requests.Session()


class FredError(RuntimeError):
    pass


def _key() -> str:
    key = os.environ.get("FRED_API_KEY")
    if not key:
        raise FredError("FRED_API_KEY is not set (see .env.example)")
    return key


def _get(path: str, **params) -> dict:
    params.update(api_key=_key(), file_type="json")
    last_err = None
    for attempt in range(4):
        try:
            r = SESSION.get(f"{BASE}/{path}", params=params, timeout=30)
            if r.status_code == 429:  # rate limited: 120 requests/minute
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 400:
                msg = r.json().get("error_message", r.text)
                raise FredError(f"{path} {params.get('series_id', '')}: {msg}")
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout) as e:
            last_err = e
            time.sleep(2 * (attempt + 1))
    raise FredError(f"{path} failed after retries: {last_err}")


@lru_cache(maxsize=None)
def series_info(series_id: str) -> dict:
    """Metadata: title, frequency_short, units, last_updated, etc."""
    data = _get("series", series_id=series_id)
    return data["seriess"][0]


@lru_cache(maxsize=None)
def observations(series_id: str, start: str = "2010-01-01") -> pd.Series:
    data = _get("series/observations", series_id=series_id, observation_start=start)
    obs = [(o["date"], o["value"]) for o in data["observations"] if o["value"] != "."]
    if not obs:
        raise FredError(f"{series_id}: no observations since {start}")
    dates, values = zip(*obs)
    return pd.Series(pd.to_numeric(values), index=pd.to_datetime(dates), name=series_id)


def search(text: str, limit: int = 5) -> list[dict]:
    data = _get("series/search", search_text=text, limit=limit, order_by="popularity")
    return [
        {"id": s["id"], "title": s["title"], "freq": s["frequency_short"], "updated": s["last_updated"]}
        for s in data.get("seriess", [])
    ]
