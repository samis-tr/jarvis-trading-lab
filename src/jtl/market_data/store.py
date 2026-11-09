"""CSV persistence for bar series, with provenance in a header line so labels survive round-trips."""

from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

from pydantic import ValidationError

from jtl.errors import DataError
from jtl.market_data.models import Bar, BarSeries, Provenance

FIELDS = ("session", "open", "high", "low", "close", "volume")


def save_csv(series: BarSeries, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    meta = {"symbol": series.symbol, "provenance": series.provenance.model_dump(mode="json")}
    with p.open("w", newline="", encoding="utf-8") as fh:
        fh.write("# " + json.dumps(meta, sort_keys=True) + "\n")
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for b in series.bars:
            w.writerow([b.session.isoformat(), b.open, b.high, b.low, b.close, b.volume])
    return p


def load_csv(path: str | Path) -> BarSeries:
    p = Path(path)
    if not p.exists():
        raise DataError(f"data file not found: {p}")
    with p.open(encoding="utf-8") as fh:
        first = fh.readline()
        if not first.startswith("# "):
            raise DataError("CSV missing provenance header line")
        try:
            meta = json.loads(first[2:])
            prov = Provenance.model_validate(meta["provenance"])
            symbol = str(meta["symbol"])
        except (ValueError, KeyError, ValidationError) as e:
            raise DataError("CSV provenance header invalid") from e
        r = csv.DictReader(fh)
        if tuple(r.fieldnames or ()) != FIELDS:
            raise DataError(f"CSV columns must be {FIELDS}")
        bars = []
        for row in r:
            try:
                bars.append(
                    Bar(
                        session=dt.date.fromisoformat(row["session"]),
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=float(row["volume"]),
                    )
                )
            except (ValueError, ValidationError) as e:
                raise DataError(f"bad CSV row {row}") from e
    return BarSeries(symbol=symbol, provenance=prov, bars=tuple(bars))
