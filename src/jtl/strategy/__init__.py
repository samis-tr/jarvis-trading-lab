"""Strategies produce *signals* only. They cannot size, submit or bypass risk."""

from jtl.strategy.base import Signal, Strategy, Target
from jtl.strategy.simple import AlwaysLong, Momentum, default_lineup
from jtl.strategy.sma_trend import SmaTrend

__all__ = ["AlwaysLong", "Momentum", "Signal", "SmaTrend", "Strategy", "Target", "default_lineup"]
