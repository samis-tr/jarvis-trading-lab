"""Scheduler: computes when the next daily cycle may run (after a session's close + confirmation delay).

Phase 1-2 has no background daemon; this module only answers "when is the next confirmed bar due?"
so a future local scheduler (Windows Task Scheduler / Jarvis) can call `jtl` at the right time.
"""

from __future__ import annotations

import datetime as dt

from jtl.market_data import calendar


def next_run_time(now: dt.datetime, delay_minutes: int) -> dt.datetime:
    now_ny = calendar.require_aware(now)
    d = now_ny.date()
    s = d if calendar.is_session(d) else calendar.next_session(d)
    while True:
        t = calendar.session_close(s) + dt.timedelta(minutes=delay_minutes)
        if t > now_ny:
            return t
        s = calendar.next_session(s)
