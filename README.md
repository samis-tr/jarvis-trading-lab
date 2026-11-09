# Jarvis Trading Lab

**PAPER-ONLY** trading research and local simulation platform (Windows, Python 3.12).
It never trades real money, has no live adapter or live toggle, and never asks for or stores live
brokerage credentials.

> All performance numbers produced by this lab are **HYPOTHETICAL / SIMULATED**. The bundled sample data
> is **SYNTHETIC** (a seeded random walk), not real market prices.

Status: **Phase 1 (scaffold, data model, safety, storage, tests) and Phase 2 (historical data, SMA trend
baseline, local simulator, risk engine) are done.** Phases 3-5 are not started. Phase 4 (Alpaca *paper*)
needs explicit permission. See [PROGRESS.md](PROGRESS.md).

## Quick start

```powershell
cd D:\jarvis-trading-lab
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1      # venv + pinned deps + ruff + tests
powershell -ExecutionPolicy Bypass -File scripts\start-sim.ps1  # offline LOCAL_SIM replay + report
powershell -ExecutionPolicy Bypass -File scripts\start-sim.ps1 -Dashboard   # ...then a read-only dashboard on http://127.0.0.1:8765
powershell -ExecutionPolicy Bypass -File scripts\run-gate.ps1   # tests + sim -> var\gate.json
```

`-ExecutionPolicy Bypass` applies to that one PowerShell process only; it does not change system settings.

Other commands (`.venv\Scripts\python -m jtl <command>`):

| Command | What it does |
|---|---|
| `sim [--csv F --tr-csv F]` | Deterministic replay on the **in-sample** slice; writes `reports\out\*.md/json` and a ledger DB in `var\runs\` |
| `sim --final-holdout "reason"` | Opens the sealed out-of-sample slice **once** for a final check (never use it to tune) |
| `fetch-data --start 2016-01-01 --end 2025-12-31` | Fetches Alpaca daily bars (split-adjusted and total-return). Needs **your own** paper/data keys in env vars |
| `verify-journal --db F` / `backup --db F` / `breakers --db F` | Audit-trail verification, verified backup, breaker status |
| `reset-breaker --db F --name drawdown --operator NAME` | **Human-only** reset of a latched breaker (asks for an exact phrase) |
| `paper-status` | Explains why paper trading is not allowed (Phase 4 is not built) |
| `next-run` | When the next confirmed daily bar is due (NYSE close + delay, New York time) |

## Using real data (optional; needs your permission and keys)

1. Create a free Alpaca account yourself and generate **paper** API keys (never live keys).
2. Set them only as env vars in your own shell: `$env:APCA_API_KEY_ID="..."; $env:APCA_API_SECRET_KEY="..."`.
   Never put them in files, chat, or git.
3. `python -m jtl fetch-data --start 2016-01-04 --end 2025-12-31`, then set `data.provider: alpaca` in `config.yaml`.
4. If validation reports issues (missing sessions, anomalies), research stops until they are resolved.

## Docs

* [ARCHITECTURE.md](ARCHITECTURE.md): modules and data flow
* [SECURITY.md](SECURITY.md): network allowlist, secrets, threat model
* [RISK_POLICY.md](RISK_POLICY.md): risk limits and breakers
* [PROGRESS.md](PROGRESS.md): status, test results, limitations

---

## بالعربي (ملخص سريع)

* المشروع **محاكاة وتداول ورقي فقط**: ما في أي تداول بفلوس حقيقية، ولا في أي مفتاح أو خيار للتداول الحي.
* كل الأرقام اللي بيطلعها **افتراضية (Hypothetical)**، والبيانات المرفقة **اصطناعية** وما هي أسعار حقيقية.
* للتشغيل: شغّل `scripts\setup.ps1` مرة وحدة، وبعدها `scripts\start-sim.ps1`.
* البيانات الحقيقية من Alpaca اختيارية، وبدها مفاتيح **paper** تبعك بمتغيرات البيئة بس.
