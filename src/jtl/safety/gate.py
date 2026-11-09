"""Paper-trading gate (acceptance test J).

Paper trading may only start after BOTH the full safety test-suite and a local simulation pass on
the exact current source code. `jtl gate` writes var/gate.json with a hash of all source files; any
code change invalidates it. In Phase 1-2 the gate additionally always reports Phase 4 as disabled.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SRC_ROOT.parents[1]
GATE_FILE = PROJECT_ROOT / "var" / "gate.json"


def source_hash(root: Path = SRC_ROOT) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*.py")):
        h.update(p.relative_to(root).as_posix().encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def write_gate(tests_passed: bool, sim_passed: bool, details: dict, path: Path = GATE_FILE) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "tests_passed": bool(tests_passed),
                "sim_passed": bool(sim_passed),
                "source_hash": source_hash(),
                "created_utc": dt.datetime.now(dt.UTC).isoformat(),
                "details": details,
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return path


def paper_trading_allowed(path: Path = GATE_FILE, *, phase4_enabled: bool | None = None) -> tuple[bool, list[str]]:
    if phase4_enabled is None:
        from jtl.alpaca_paper import PHASE4_ENABLED  # local import: avoid cycle

        phase4_enabled = PHASE4_ENABLED
    reasons: list[str] = []
    if not phase4_enabled:
        reasons.append("Phase 4 (Alpaca paper) is not enabled in this build")
    if not path.exists():
        reasons.append("no gate record - run `jtl gate` (tests + local simulation) first")
        return False, reasons
    try:
        g = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, [*reasons, "gate record unreadable"]
    if g.get("tests_passed") is not True:
        reasons.append("safety test-suite did not pass")
    if g.get("sim_passed") is not True:
        reasons.append("local simulation did not pass")
    if g.get("source_hash") != source_hash():
        reasons.append("source changed since the gate ran - re-run `jtl gate`")
    return not reasons, reasons
