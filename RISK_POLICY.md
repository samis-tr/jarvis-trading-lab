# Risk Policy

These are **ceilings**. `config.yaml` may make them stricter but never looser; looser values are
rejected at load. The risk engine is deterministic: the same inputs always produce the same decision.

| Rule | Limit | Enforcement |
|---|---|---|
| Instruments | explicit allowlist (default `SPY`), US equities, long-only | typed `OrderIntent`, allowlist check |
| Leverage / margin / shorts / options / futures / forex / derivatives | **forbidden** | not expressible in the types; sells capped at the held quantity; buying power above cash halts |
| Cash | cash-only; pending buys reserve cash, with a 3% overnight-gap buffer plus estimated costs | `RiskEngine.evaluate` |
| Risk per trade | <= **0.5%** of equity (qty x price x stop distance, stop = 5%) | sizing + evaluate |
| Position size | <= **20%** of equity, counting existing position + pending + new order | evaluate |
| Orders | <= 2 strategy orders per session; one pending order per symbol; idempotent IDs | evaluate + broker lock + DB unique index |
| Daily loss | close-to-close loss >= **1%** -> pause new entries (this and the next session) | `daily_loss` breaker |
| Weekly loss | loss >= **2%** vs. the last close of the previous week -> pause until the week ends | `weekly_loss` breaker |
| Drawdown | peak-to-trough >= **5%** -> **latched** circuit breaker | `drawdown` breaker; persists across restarts; never auto-resets |
| Fail-safe | any SafetyError -> **latched** `system_halt` | supervisor |

## Behaviour while a breaker is active

* New **buys** are rejected.
* **Risk-reducing sells** (exits, protective stops) are still allowed, except under `system_halt`,
  where no new strategy orders are placed at all.
* Latched breakers (`drawdown`, `system_halt`) clear only through
  `python -m jtl reset-breaker --name ... --operator ...`, typed by a human with the exact
  confirmation phrase. Each reset is journaled. Resetting `drawdown` also resets the peak to the
  current equity.

## Known limitation: gap risk

Stops are modelled. When the market opens **below** the stop (an overnight gap), the simulated exit
fills at that open minus slippage. **Realised losses can therefore exceed the 0.5% risk budget and the
breaker thresholds.** Tests cover this behaviour (`tests/test_g_costs_gaps.py`).

## Costs modelled (all adverse; configurable assumptions)

* half-spread 2 bps
* slippage 3 bps
* latency drift 1 bps, with a 2 s latency on the fill timestamp
* commission $0 per order
* SEC fee and FINRA TAF on sells

Check the fee rates against current regulations before relying on them.
