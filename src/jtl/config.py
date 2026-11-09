"""Typed, frozen, fail-closed configuration.

* Unknown keys are rejected (no `base_url`, `live`, `leverage`, ... can sneak in).
* No URL of any kind may appear anywhere in config.
* Only LOCAL_SIM mode is accepted in Phase 1-2.
* Risk limits can only be made STRICTER than the policy ceilings, never looser.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from jtl.errors import ConfigRejected
from jtl.safety.endpoints import check_environment

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Policy ceilings from RISK_POLICY.md - config may tighten, never loosen.
CEIL_RISK_PER_TRADE = 0.005
CEIL_POSITION = 0.20
CEIL_DAILY_LOSS = 0.01
CEIL_WEEKLY_LOSS = 0.02
CEIL_DRAWDOWN = 0.05
LOCALHOST_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


class Mode(StrEnum):
    LOCAL_SIM = "LOCAL_SIM"
    ALPACA_PAPER = "ALPACA_PAPER"  # reserved for Phase 4; rejected now


class _M(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StrategyConfig(_M):
    name: Literal["sma_trend"] = "sma_trend"
    symbol: str = "SPY"
    fast_window: int = Field(50, ge=2, le=400)
    slow_window: int = Field(200, ge=3, le=600)

    @model_validator(mode="after")
    def _order(self) -> StrategyConfig:
        if self.fast_window >= self.slow_window:
            raise ValueError("fast_window must be < slow_window")
        return self


class RiskConfig(_M):
    max_risk_per_trade_pct: float = Field(0.005, gt=0, le=CEIL_RISK_PER_TRADE)
    max_position_pct: float = Field(0.20, gt=0, le=CEIL_POSITION)
    stop_loss_pct: float = Field(0.05, ge=0.005, le=0.5)
    daily_loss_pause_pct: float = Field(0.01, gt=0, le=CEIL_DAILY_LOSS)
    weekly_loss_pause_pct: float = Field(0.02, gt=0, le=CEIL_WEEKLY_LOSS)
    max_drawdown_pct: float = Field(0.05, gt=0, le=CEIL_DRAWDOWN)
    max_orders_per_day: int = Field(2, ge=1, le=10)
    allow_fractional: bool = True


class SimulatorConfig(_M):
    starting_cash: float = Field(1000.0, gt=0, le=1_000_000)
    half_spread_bps: float = Field(2.0, ge=0, le=500)
    slippage_bps: float = Field(3.0, ge=0, le=500)
    latency_seconds: float = Field(2.0, ge=0, le=3600)
    latency_drift_bps: float = Field(1.0, ge=0, le=500)
    commission_per_order: float = Field(0.0, ge=0, le=100)
    sec_fee_rate: float = Field(0.0000278, ge=0, le=0.01)
    finra_taf_per_share: float = Field(0.000166, ge=0, le=0.1)
    finra_taf_max: float = Field(8.30, ge=0, le=100)
    entry_price_buffer_pct: float = Field(0.03, ge=0, le=0.5)


class DataConfig(_M):
    provider: Literal["sample", "csv", "alpaca"] = "sample"
    csv_path: str = "data/sample/SPY_synthetic.csv"
    alpaca_feed: Literal["sip", "iex"] = "sip"
    min_history_years: float = Field(5, ge=1, le=50)
    max_abs_daily_return: float = Field(0.15, gt=0, le=1)
    bar_confirmation_delay_minutes: int = Field(60, ge=15, le=24 * 60)
    holdout_fraction: float = Field(0.2, ge=0.1, le=0.5)


class StorageConfig(_M):
    db_path: str = "var/jtl.db"
    backup_dir: str = "var/backups"


class DashboardConfig(_M):
    host: str = "127.0.0.1"
    port: int = Field(8765, ge=1024, le=65535)

    @field_validator("host")
    @classmethod
    def _localhost(cls, v: str) -> str:
        if v not in LOCALHOST_HOSTS:
            raise ValueError("dashboard must bind to localhost only")
        return v


class AppConfig(_M):
    mode: Mode = Mode.LOCAL_SIM
    symbols: tuple[str, ...] = ("SPY",)
    strategy: StrategyConfig = StrategyConfig()
    risk: RiskConfig = RiskConfig()
    simulator: SimulatorConfig = SimulatorConfig()
    data: DataConfig = DataConfig()
    storage: StorageConfig = StorageConfig()
    dashboard: DashboardConfig = DashboardConfig()

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v or len(set(v)) != len(v):
            raise ValueError("symbols allowlist must be non-empty and unique")
        for s in v:
            if not s.isascii() or not s.replace(".", "").isalpha() or s.upper() != s or len(s) > 10:
                raise ValueError(f"invalid symbol {s!r}")
        return v

    @model_validator(mode="after")
    def _phase_guards(self) -> AppConfig:
        if self.mode is not Mode.LOCAL_SIM:
            raise ValueError("only LOCAL_SIM mode is available in Phase 1-2")
        if self.strategy.symbol not in self.symbols:
            raise ValueError("strategy symbol must be in the allowlist")
        return self

    def resolve(self, rel: str) -> Path:
        p = Path(rel)
        return p if p.is_absolute() else PROJECT_ROOT / p


def _reject_urls(obj: Any, path: str = "") -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _reject_urls(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _reject_urls(v, f"{path}[{i}]")
    elif isinstance(obj, str) and ("://" in obj or obj.lower().startswith(("www.", "http"))):
        raise ConfigRejected(f"URLs are not allowed in config ({path})")


def load_config(
    path: str | Path | None = None, *, environ: dict[str, str] | None = None, data: dict[str, Any] | None = None
) -> AppConfig:
    """Load and validate config. Any problem raises ConfigRejected (fail closed)."""
    check_environment(environ)
    raw: Any
    if data is not None:
        raw = data
    elif path is None:
        raw = {}
    else:
        p = Path(path)
        if not p.exists():
            raise ConfigRejected(f"config file not found: {p}")
        try:
            raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as e:
            raise ConfigRejected(f"config YAML invalid: {e}") from e
    if not isinstance(raw, dict):
        raise ConfigRejected("config root must be a mapping")
    _reject_urls(raw)
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as e:
        raise ConfigRejected(f"config rejected: {e.errors(include_url=False)}") from e
