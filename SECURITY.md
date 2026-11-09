# Security

## Hard rules

1. **No real-money trading, ever.** There is no live adapter, live mode, or live toggle. `Mode` accepts
   only `LOCAL_SIM` in Phase 1-2.
2. **Hardcoded destinations only** (`safety/endpoints.py`):
   * trading: `https://paper-api.alpaca.markets` (path `/v2/...`). Disabled until Phase 4.
   * data: `https://data.alpaca.markets` (path `/v2/stocks/...`).
   * `api.alpaca.markets` and `broker-api.alpaca.markets` are explicitly denied.
3. `validate_destination` rejects any non-https scheme, userinfo (`user@host`), a non-default port,
   non-ASCII (homograph) hosts, backslashes, lookalike or suffix hosts, wrong paths, and fragments.
4. `GuardedClient` re-validates every request in an httpx event hook and uses `follow_redirects=False`.
   It treats any 3xx as a refusal, and with `trust_env=False` it ignores proxy env vars.
5. **No broker URL can be configured.** Config has no URL field, rejects unknown keys and any
   string containing a URL. Setting `APCA_API_BASE_URL` (or a similar variable) to anything other than
   the paper URL makes startup fail closed.
6. **Secrets come from env vars only** (`APCA_API_KEY_ID`, `APCA_API_SECRET_KEY`). They are never read
   from config. The journal and reports refuse secret-like keys and any value equal to a live secret
   (`SecretLeak`). `.env` and `config.yaml` are gitignored.
7. **The dashboard is localhost only and read-only.** It binds to 127.0.0.1, ::1 or localhost, has no
   POST endpoints and no docs/openapi routes, and opens SQLite in `mode=ro`. No firewall rules,
   tunnels or port forwarding are used.
8. **No LLM or Jarvis path to orders or risk.** Orders go only through
   `Supervisor.submit`, which runs `RiskEngine.evaluate` before `Broker.submit`. Config objects are frozen.
   Breaker resets are a CLI-only human action that requires an exact phrase and an operator name, and
   each reset is journaled.
9. **No paid software or subscriptions.** All dependencies are free and open source, with pinned
   versions in `requirements.txt`.

## Fail-closed conditions (stop new orders)

The following all stop new orders:

* missing, stale or unconfirmed bars
* API or network failures
* price anomalies
* timezone errors
* duplicate or rejected orders
* buying power above cash (margin)
* ledger/fill reconciliation mismatches
* journal corruption
* suspicious config or environment
* a session processed twice

## Threat notes

* *Prompt injection*: text from news, research notes or LLM output has no code path into config, risk
  or orders. Tests in `tests/test_a_destinations.py` cover this.
* *DB tampering*: dropping the immutability triggers and editing history is detected by hash-chain
  verification when the DB opens, periodically, and before every order.
* *Network*: the test-suite blocks all non-loopback sockets, so a test that tries to reach the
  internet fails.

Report issues locally. This project is never exposed to the internet.
