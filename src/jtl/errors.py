"""Exception hierarchy. Every SafetyError means: stop new orders (fail closed)."""


class JTLError(Exception):
    """Base error."""


class SafetyError(JTLError):
    """A safety invariant was violated. Callers must fail closed."""


class DestinationRejected(SafetyError):
    """Network destination not on the hardcoded allowlist (live endpoint, redirect, lookalike...)."""


class ConfigRejected(SafetyError):
    """Configuration is suspicious or invalid."""


class SecretLeak(SafetyError):
    """A secret was about to be written to a log/journal/report."""


class PaperTradingNotEnabled(SafetyError):
    """Alpaca paper trading is not available in this phase."""


class DataError(SafetyError):
    """Market data is missing, stale, malformed or anomalous."""


class InsufficientData(DataError):
    """Not enough verified history for research."""


class JournalCorrupt(SafetyError):
    """The immutable event journal failed verification."""


class StorageLocked(SafetyError):
    """Another process holds the single-writer lock."""


class ReconciliationMismatch(SafetyError):
    """Broker state differs from internal ledger."""


class OrderRejected(JTLError):
    """Order rejected by validation or the risk engine (expected, not a crash)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason
