"""Load Kalshi events, markets and trades into one normalised shape.

Two sources are understood:
  * a folder written by kalshi_pull.py: events.csv, markets.csv, trades.csv;
  * the public prediction-market-analysis dataset (Becker, 2026), whose
    data/kalshi/markets/*.parquet and data/kalshi/trades/*.parquet hold the
    same API fields (reading parquet needs pyarrow).

Normalised frames
  markets  ticker, event_ticker, series, title, event_title, close_ts, y,
           family, subfamily, script, mutually_exclusive, me_source, reveal_ts
  trades   ticker, ts, price (YES price in (0, 1)), count, side (+1 when the
           taker bought YES, -1 when the taker bought NO), trade_id

Only settled markets (result yes/no) and their trades are kept. reveal_ts is
the earliest close time among an event's markets: mention markets close one by
one as words are said, so the first close is the latest safe "before the
event" anchor; award and announcement markets all close at the reveal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import families as fam

EPOCH = pd.Timestamp("1970-01-01", tz="UTC")
ME_INFER_SUBFAMILIES = {"award", "announcement"}


def to_epoch(values) -> np.ndarray:
    """ISO strings, datetimes or epoch numbers -> int64 epoch seconds."""
    s = pd.Series(values)
    if pd.api.types.is_numeric_dtype(s):
        return s.astype("int64").to_numpy()
    t = pd.to_datetime(s, utc=True, format="ISO8601")
    return ((t - EPOCH) // pd.Timedelta(seconds=1)).astype("int64").to_numpy()


def to_prob(values) -> np.ndarray:
    """Cents (1-99) or dollars/probabilities (0-1) -> float probabilities."""
    p = pd.to_numeric(pd.Series(values), errors="coerce").to_numpy(dtype=float)
    if len(p) and np.nanmax(p) > 1.0:
        p = p / 100.0
    return p


@dataclass
class Dataset:
    markets: pd.DataFrame
    trades: pd.DataFrame
    source: str = ""
    _paths: dict = field(default_factory=dict, repr=False)

    def paths(self) -> dict:
        """ticker -> (ts, price, count, side) numpy arrays sorted by time."""
        if not self._paths:
            for ticker, g in self.trades.groupby("ticker", sort=False):
                g = g.sort_values("ts", kind="stable")
                self._paths[ticker] = (g["ts"].to_numpy(), g["price"].to_numpy(),
                                       g["count"].to_numpy(), g["side"].to_numpy())
        return self._paths


def _read_parquet_dir(path: Path) -> pd.DataFrame:
    files = sorted(path.glob("*.parquet"))
    if not files:
        raise FileNotFoundError(f"no parquet files in {path}")
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def normalise(markets: pd.DataFrame, trades: pd.DataFrame,
              events: pd.DataFrame | None = None, overrides: dict | None = None,
              source: str = "") -> Dataset:
    m = markets.copy()
    m["result"] = m["result"].fillna("").astype(str).str.lower()
    m = m[m["result"].isin(["yes", "no"])].drop_duplicates("ticker", keep="last")
    m["y"] = (m["result"] == "yes").astype(int)
    m["close_ts"] = to_epoch(m["close_time"])
    derived = m["event_ticker"].map(fam.series_of)
    if "series_ticker" in m:
        m["series"] = m["series_ticker"].fillna(derived)
    elif "series" in m:
        m["series"] = m["series"].fillna(derived)
    else:
        m["series"] = derived
    for col in ("title", "yes_sub_title"):
        m[col] = m[col].fillna("").astype(str) if col in m else ""
    m["event_title"] = m["title"]
    m["mutually_exclusive"] = pd.Series(pd.NA, index=m.index, dtype="boolean")
    m["me_source"] = "none"
    if events is not None and len(events):
        ev = events.drop_duplicates("event_ticker", keep="last").set_index("event_ticker")
        if "title" in ev:
            m["event_title"] = m["event_ticker"].map(ev["title"]).fillna(m["title"]).astype(str)
        if "mutually_exclusive" in ev:
            me = ev["mutually_exclusive"].map(
                lambda v: str(v).strip().lower() in ("true", "1"))
            m["mutually_exclusive"] = m["event_ticker"].map(me).astype("boolean")
            m.loc[m["mutually_exclusive"].notna(), "me_source"] = "api"
    fs = [fam.classify(s, t, overrides) for s, t in zip(m["series"], m["event_title"])]
    m["family"] = [f for f, _ in fs]
    m["subfamily"] = [s for _, s in fs]
    m["script"] = np.where(m["subfamily"] == "mention",
                           m["event_title"].map(fam.script_type), "")
    # Infer mutually exclusive events where the API flag is missing: several
    # markets in an award/announcement event, exactly one of which settled YES.
    grp = m.groupby("event_ticker")["y"].agg(["size", "sum"])
    one_winner = grp[(grp["size"] >= 3) & (grp["sum"] == 1)].index
    infer = m["mutually_exclusive"].isna() & m["event_ticker"].isin(one_winner) \
        & m["subfamily"].isin(ME_INFER_SUBFAMILIES)
    m.loc[infer, "mutually_exclusive"] = True
    m.loc[infer, "me_source"] = "inferred"
    m["mutually_exclusive"] = m["mutually_exclusive"].fillna(False).astype(bool)
    if "reveal_time" in m and m["reveal_time"].notna().any():
        m["reveal_ts"] = to_epoch(m["reveal_time"].fillna(m["close_time"]))
    else:
        m["reveal_ts"] = m.groupby("event_ticker")["close_ts"].transform("min")
    keep = ["ticker", "event_ticker", "series", "title", "yes_sub_title",
            "event_title", "close_ts", "reveal_ts", "y", "family", "subfamily",
            "script", "mutually_exclusive", "me_source"]
    m = m[keep].reset_index(drop=True)

    if "ticker" not in trades:
        trades = pd.DataFrame(columns=["ticker", "created_time", "yes_price", "count",
                                       "taker_side", "trade_id"])
    t = trades[trades["ticker"].isin(set(m["ticker"]))].copy()
    if "trade_id" in t:
        t = t.drop_duplicates("trade_id")
    else:
        t["trade_id"] = np.arange(len(t)).astype(str)
    t["ts"] = to_epoch(t["created_time"])
    price_col = "yes_price_dollars" if "yes_price_dollars" in t else "yes_price"
    t["price"] = to_prob(t[price_col])
    count_col = "count_fp" if "count_fp" in t else "count"
    t["count"] = pd.to_numeric(t[count_col], errors="coerce").astype(float)
    side = t["taker_side"].astype(str).str.lower()
    t["side"] = np.where(side == "yes", 1, np.where(side == "no", -1, 0))
    t = t[(t["side"] != 0) & t["price"].between(0, 1, inclusive="neither")
          & (t["count"] > 0)]
    t = t[["ticker", "ts", "price", "count", "side", "trade_id"]].reset_index(drop=True)
    return Dataset(markets=m, trades=t, source=source)


def load(path: str | Path, overrides_csv: str | Path | None = None) -> Dataset:
    """Load a kalshi_pull folder or a Becker-style data/kalshi folder."""
    path = Path(path)
    overrides = fam.load_overrides(overrides_csv)
    if (path / "markets.csv").exists():
        events = pd.read_csv(path / "events.csv") if (path / "events.csv").exists() else None
        return normalise(pd.read_csv(path / "markets.csv"),
                         pd.read_csv(path / "trades.csv"), events, overrides,
                         source=f"kalshi_pull:{path}")
    for base in (path, path / "kalshi", path / "data" / "kalshi"):
        if (base / "markets").is_dir() and (base / "trades").is_dir():
            try:
                markets = _read_parquet_dir(base / "markets")
                trades = _read_parquet_dir(base / "trades")
            except ImportError as err:  # pragma: no cover - environment
                raise SystemExit("reading parquet needs pyarrow: pip install pyarrow") from err
            return normalise(markets, trades, None, overrides, source=f"parquet:{base}")
    raise FileNotFoundError(f"{path}: expected markets.csv/trades.csv or markets/ and trades/ parquet folders")
