"""Strategies produce *signals* only. They cannot size, submit or bypass risk."""

from jtl.strategy.sma_trend import Signal, SmaTrend, Target

__all__ = ["Signal", "SmaTrend", "Target"]
