# Architecture

```
src/jtl/
  config.py          frozen, fail-closed config (extra keys rejected, no URLs, limits only tighter)
  domain.py          typed OrderIntent / Order / Fill / Position (long-only, cash, US equity, DAY)
  errors.py          SafetyError hierarchy (every SafetyError = stop new orders)
  safety/            endpoints.py (hardcoded allowlist), http.py (GuardedClient), secrets.py, gate.py
  storage/           SQLite: migrations, single-writer lock, WAL, backups, hash-chained journal
  market_data/       models (provenance), NYSE calendar, validation, Alpaca daily bars, synthetic samples, CSV
  strategy/          SmaTrend (50/200, configurable): signals only
  risk/              RiskEngine (deterministic pre-trade gate), BreakerBook (persistent breakers)
  simulator/         CostModel, LocalSimBroker (persistent ledger), engine.run_replay
  reconciliation/    rebuild cash/positions from fills and compare with broker report
  supervisor/        per-session cycle and fail-safe halts
  analytics/         metrics, buy-and-hold (price-only / total-return) and cash benchmarks
  research/          data sufficiency, InSample / SealedHoldout split, in-sample-only selection
  reports/           Markdown + JSON reports (HYPOTHETICAL banner, data provenance)
  dashboard/         read-only FastAPI app, localhost only, no write endpoints
  scheduler/         next confirmed-bar run time (no daemon in Phase 2)
  alpaca_paper/      guarded STUB; constructing it raises PaperTradingNotEnabled
  cli.py             `python -m jtl ...`
```

## Session cycle (Supervisor.process_session)

All times are America/New_York, taken from the NYSE calendar (`exchange_calendars` XNYS), never the
wall clock, so a replay is deterministic.

1. **Guards**: incremental journal verification (a full re-hash every 20 sessions and before every
   order). The session must not already be processed, its bar must exist, the view must contain no future
   bars, and the session must not be flagged by data validation.
2. **Open**: pending orders from the previous close fill at this session's **open**, with adverse spread,
   slippage and latency drift, plus fees. Protective stops run next. A stop that the open gaps through
   fills at the open (`stop_gap`), so the loss can exceed the risk budget.
3. **Close**: mark to market, then reconcile the ledger against the fills (this also checks buying
   power against cash). Then the daily, weekly and drawdown breakers update.
4. **Decide** (only if not halted): the SMA signal on the confirmed close is sized by the RiskEngine,
   evaluated by `RiskEngine.evaluate`, and submitted as PENDING with a deterministic idempotent ID.

Any `SafetyError` in steps 1-3 trips the latched `system_halt` breaker. Journal corruption also aborts the run.

## Storage

One SQLite file per ledger (`var/jtl.db`, or `var/runs/<name>.db` for replays). It runs in WAL mode with
`synchronous=FULL`. An OS-level lock file (`*.db.lock`, `msvcrt.locking`) ensures a single writer. The OS
releases the lock if the process dies.

* `events` is the immutable journal. SQL triggers block UPDATE and DELETE. Each row stores
  `sha256(prev_hash, seq, ts, kind, payload)`, and verification recomputes the chain. Payloads are scanned
  for secrets before they are written.
* `orders`: a partial UNIQUE index allows one pending order per symbol.
* `fills`, `positions`, `account`, `breakers`, `equity` and `kv` hold the rest of the state. Breakers
  and peak equity live here, which is why they survive restarts.
* Migrations are append-only (`storage/migrations.py`).
* `Storage.backup()` verifies the journal, then copies the database with SQLite's online backup API.

## Data

* `Bar` covers one NYSE session. `BarSeries` carries `Provenance` (SYNTHETIC / TEST / ALPACA / CSV, plus
  the adjustment).
* Price-only uses `adjustment=split`. Total-return uses `adjustment=all` (dividends). The simulator trades
  the **price-only** series and does not credit dividends, which is conservative. Benchmarks report
  buy-and-hold on both series separately, plus cash.
* Validation flags duplicates, unordered bars, non-sessions, missing sessions, inconsistent OHLC, and
  moves or gaps above 15%. Freshness requires the newest bar to equal the latest *confirmed* session
  (close + 60 min).
* Alpaca bars are stamped at 00:00 New York time. A timestamp that is naive or not at New York midnight
  is rejected as a timezone error.

## Future phases (not implemented)

* Phase 3: research tooling (walk-forward, more strategies). The LLM may explain results but has no
  write path to strategy or risk.
* Phase 4 (needs explicit permission): `alpaca_paper` against the hardcoded paper endpoint, behind
  `gate.paper_trading_allowed()`.
* Phase 5: a limited local interface for JARVIS (read-only status and explanations; no order or reset
  tools).
