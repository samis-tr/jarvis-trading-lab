# Progress

## 2026-11-09: Phase 1 + Phase 2 complete

### Done
* **Phase 1**
  * Repo scaffold: typed modules `market_data`, `research`, `strategy`, `risk`, `simulator`,
    `alpaca_paper` (guarded stub), `reconciliation`, `analytics`, `dashboard`, `supervisor`, `reports`,
    `storage`, `scheduler`.
  * Storage: SQLite with migrations, a single-writer lock, WAL, verified backups, and a hash-chained
    immutable journal.
  * Tooling: pytest and ruff, with pinned free dependencies.
  * Docs: README, ARCHITECTURE, SECURITY, RISK_POLICY, config.example.yaml, .env.example.
  * Scripts: `scripts/setup.ps1`, `scripts/start-sim.ps1`, `scripts/run-gate.ps1`.
* **Phase 2**
  * Alpaca daily-bar connector: data host only, paging, schema checks, NY-midnight timezone check, mocked in tests.
  * Validation: schema, NYSE calendar (holidays and early closes), missing sessions, anomalies,
    freshness, and confirmed-close rules.
  * SMA 50/200 trend strategy (configurable). It signals on the confirmed close and executes at the
    next open.
  * Deterministic risk engine and persistent breakers.
  * Local paper ledger starting at $1,000, with:
    * spread, slippage and latency, plus fees
    * gap-through stops
    * idempotent order IDs
    * reconciliation
    * deterministic replay
  * Research rules: at least 5 years of data required, a sealed out-of-sample holdout, and
    parameter selection on in-sample data only.
  * Benchmarks: buy-and-hold price-only, buy-and-hold total-return, and cash.
  * Read-only localhost dashboard.

### Test results (offline, no API keys, non-loopback sockets blocked)
* `pytest`: **113 passed** in ~27 s.
* `ruff check src tests`: all checks passed.
* `jtl gate`: tests_passed=True, sim_passed=True (deterministic=True). Recorded in `var/gate.json`.

| Acceptance | Covered by |
|---|---|
| A live destinations rejected | `test_a_destinations.py` (43 cases: lookalikes, env, config, redirects, injection) |
| B risk violations blocked | `test_b_risk.py` (budget, 20% cap, combined exposure, concurrent duplicates, idempotency) |
| C breakers survive restart | `test_c_breakers.py` |
| D bad/stale/missing data stops orders | `test_d_data_guard.py` |
| E no look-ahead | `test_e_no_lookahead.py` |
| F deterministic + auditable replay | `test_f_replay.py` (identical journals, ledger rebuilt from journal, tamper detection) |
| G gap + slippage modelled | `test_g_costs_gaps.py` (a gap-through stop loses more than the 0.5% budget) |
| H failed networking never sends an order | `test_h_network_failure.py` |
| I outputs marked hypothetical | `test_i_j_reports_gate.py` |
| J paper blocked until gate passes | `test_i_j_reports_gate.py` |

### Actual vs hypothetical
* **Actual**: the code, the tests and their results, and the journal hashes.
* **Hypothetical**: every equity and return figure. The only data used so far is **SYNTHETIC**
  (seeded random walk) or test fixtures. No real market data has been fetched. No conclusion about
  real-market profitability can be drawn.

### Limitations
* No real data yet, so the >= 5-year verified-history requirement has not been exercised on real bars.
* Dividends are not credited to the simulated ledger (it uses price-only data, which is conservative).
  Total return appears only as a benchmark.
* Fills happen at the daily open, with simple bps cost assumptions. There are no partial fills, no
  intraday path beyond the high/low stop check, and no market-impact model.
* Fee rates (SEC, FINRA TAF) are configurable assumptions and should be verified.
* There is no scheduler daemon and no forward "daily step" against live-updating data yet. The
  scheduler only computes the next run time.
* The single strategy and symbol (SPY) are a baseline only. No walk-forward analysis yet.

### Permissions still needed (ask the user before any of these)
* Alpaca account + **paper** API keys (user-created, env vars only) to fetch real historical data.
* Phase 4: enabling the Alpaca **paper** trading adapter.
* Phase 5: integration with JARVIS (`D:\jarvis-ai`) through a limited, read-only local interface.

### Next
* With permission, fetch real SPY bars (2016 onwards), validate them, and run the in-sample study.
  Open the holdout only once.
* Phase 3 research tooling.
