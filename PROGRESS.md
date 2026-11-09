# Progress

## 2026-11-09 (evening): daily forward mode

* `jtl forward-step` / `scripts\forward-step.ps1` run the forward paper test. Each bot has a persistent
  $100 virtual account in `var/forward/<bot>.db`, and the leaderboard is `var/forward/leaderboard.json`.
* Each step:
  * fetches fresh Alpaca bars, stopping 20 minutes before now
  * drops intraday (unconfirmed) bars
  * refuses stale data
  * halts a bot if an already-used close was revised (split or correction)
  * catches up missed days in order; repeating a step is harmless
* The keys are loaded from the User env into the process only, and never printed.
* First real step: started on **2026-11-06**. Three bots (sma50-200, sma20-100, hold) placed buys that
  fill at the 2026-11-09 open.
* Tests: **125 passed**. Ruff is clean.
* Automatic scheduling (created with the user's OK): the Windows Task Scheduler task
  **JarvisTradingLab-ForwardStep** runs `scripts\forward-step.ps1`.
  * Runs daily at 23:30 local time, as the current user only when logged on, with limited rights.
  * If the PC was off at 23:30, it starts at the next opportunity.
  * The test run through Task Scheduler on 2026-11-09 exited with code 0.


## 2026-11-09 (later): real data + bot comparison

* The user set their own Alpaca **paper** keys (User env vars; the prefix was checked, the values were never shown).
* Fetched real SPY daily bars from Alpaca: `data/alpaca/SPY_split.csv` and `SPY_all.csv`.
  * 2,728 sessions, 2016-01-04 to 2026-11-06, SIP feed.
  * Validation found **0 issues**.
  * The data is gitignored.
* `config.yaml` now uses `data.provider: alpaca` and `starting_cash: 100`.
* New bots, all signals-only and under the same risk engine:
  * moving-average trend 50/200, 20/100 and 10/50
  * momentum over 63 and 126 days
  * risk-limited buy & hold
* After a stop-out, a bot re-enters after a FLAT signal or a 28-day cooldown.
* `jtl compare` runs each bot on its own fresh ledger with identical cash, start date, costs and limits,
  then ranks them. `jtl dashboard --compare NAME` shows the leaderboard page.
* Tests: **120 passed**. Ruff is clean.

### First real-data comparison ($100 virtual each, in-sample 2016-10-18 to 2024-09-04, HYPOTHETICAL)

| # | Bot | End value | Return | Max DD | Trades |
|---|---|---|---|---|---|
| 1 | Buy & hold (risk-limited) | $115.76 | +15.76% | -5.11% (drawdown breaker latched in 2020) | 1 |
| 2 | MA trend 50/200 | $108.28 | +8.28% | -2.32% | 9 |
| 3 | MA trend 20/100 | $107.04 | +7.04% | -2.45% | 21 |
| 4 | Momentum 63 | $105.07 | +5.07% | -2.88% | 83 |
| 5 | Momentum 126 | $104.69 | +4.69% | -3.26% | 65 |
| 6 | MA trend 10/50 | $103.64 | +3.64% | -2.13% | 47 |

The benchmark, SPY buy & hold 100% invested, reached $257.16 price-only and $292.13 total return,
with about a -34% max drawdown.

* The bots sit mostly in cash because of the risk policy, which caps risk at 0.5% per trade with a
  5% stop.
* The out-of-sample period (2024-09 onwards) is still sealed.
* No bot is claimed to be profitable going forward.


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

## 2026-11-09 - Live price view (display only)
* `market_data/live.py`: latest IEX trade through the guarded data client, 20 s cache, never raises.
* `/api/live` (GET only, forward boards only): live SPY price and each bot's value marked to it;
  prices more than 15% from the last close are ignored. Nothing is written to any ledger.
* Dashboard live strip polls every 30 s while the market is open, every 5 min otherwise.
* Paper keys are also read from the Windows *user* environment (still env vars only, disabled in tests).
* Tests: 130 passing.
