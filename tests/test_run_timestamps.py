"""
ARTHA Terminal - ingestion run timestamps carry a timezone

A full session of monitoring showed the Alerts panel rendering a job that had
finished 90 seconds earlier as "7h ago", beside a correct "Next: due now".
Cause: finished_at was written as a bare datetime.now().isoformat() in a UTC
container, and JS parses an offset-less ISO string as *local* time, so an IST
browser read 10:12 UTC as 10:12 IST — 5.5h adrift. next_run was fine because
APScheduler stamps it with the trigger's +05:30.

These pin the offset onto both ends: what is written, and what is read back
for rows written before the fix.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion import scheduler as sch


def test_stamp_is_timezone_aware_and_ist():
    ts = sch._stamp()
    parsed = datetime.fromisoformat(ts)

    assert parsed.tzinfo is not None, "an offset-less stamp is what caused the 5.5h drift"
    assert parsed.utcoffset() == timedelta(hours=5, minutes=30)


def test_stamp_round_trips_to_the_real_instant():
    # The bug was not a formatting nit — the rendered instant was wrong. Parsed
    # back, the stamp must agree with now() to within a breath.
    drift = abs((datetime.fromisoformat(sch._stamp())
                 - datetime.now(timezone.utc)).total_seconds())
    assert drift < 5


def test_legacy_naive_rows_are_labelled_utc_not_shifted():
    # Rows written before the fix are naive UTC. Reading them as IST would move
    # them 5.5h the wrong way; they must keep their instant and gain an offset.
    out = sch._as_ist("2026-07-29T10:12:03.351719")
    parsed = datetime.fromisoformat(out)

    assert parsed.tzinfo is not None
    assert parsed == datetime(2026, 7, 29, 10, 12, 3, 351719, tzinfo=timezone.utc)
    # Same instant, expressed in IST, is 15:42 — the time the job actually ran.
    assert parsed.astimezone(sch.IST).strftime("%H:%M") == "15:42"


def test_already_aware_rows_pass_through_unchanged():
    aware = "2026-07-29T15:42:03.351719+05:30"
    assert datetime.fromisoformat(sch._as_ist(aware)) == datetime.fromisoformat(aware)


def test_none_and_junk_survive():
    assert sch._as_ist(None) is None
    assert sch._as_ist("") == ""
    assert sch._as_ist("not a date") == "not a date"
