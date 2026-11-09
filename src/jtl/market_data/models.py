"""Market-data types. Every series carries provenance so synthetic data can never pass as real."""

from __future__ import annotations

import datetime as dt
import math
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Source(StrEnum):
    SYNTHETIC = "SYNTHETIC"  # generated sample data - NOT real prices
    ALPACA = "ALPACA"  # fetched from data.alpaca.markets
    CSV = "CSV"  # user-supplied file (provenance as declared in the file)
    TEST = "TEST"  # unit-test fixtures


class Adjustment(StrEnum):
    SPLIT = "split"  # split-adjusted, dividends NOT included  -> "price-only"
    ALL = "all"  # split + dividend adjusted               -> "total-return"


class Bar(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    session: dt.date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    volume: float = Field(ge=0)

    @field_validator("open", "high", "low", "close", "volume")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("non-finite price")
        return v


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: Source
    adjustment: Adjustment
    note: str = ""
    feed: str | None = None

    @property
    def is_real(self) -> bool:
        return self.source in (Source.ALPACA, Source.CSV)

    @property
    def label(self) -> str:
        if self.source is Source.SYNTHETIC:
            return "SYNTHETIC SAMPLE DATA - not real market prices"
        if self.source is Source.TEST:
            return "TEST FIXTURE DATA - not real market prices"
        return f"{self.source.value} data ({self.adjustment.value}-adjusted)"


class BarSeries(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str
    provenance: Provenance
    bars: tuple[Bar, ...]

    def sessions(self) -> list[dt.date]:
        return [b.session for b in self.bars]

    def upto(self, session: dt.date) -> BarSeries:
        """Point-in-time view: only bars with session <= `session` (no look-ahead)."""
        return BarSeries(
            symbol=self.symbol, provenance=self.provenance, bars=tuple(b for b in self.bars if b.session <= session)
        )

    def between(self, start: dt.date, end: dt.date) -> BarSeries:
        return BarSeries(
            symbol=self.symbol,
            provenance=self.provenance,
            bars=tuple(b for b in self.bars if start <= b.session <= end),
        )

    def __len__(self) -> int:
        return len(self.bars)
