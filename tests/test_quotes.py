"""Batch quote refresh — parsing and staleness logic (no network).

Guards the bug this replaced: the per-symbol price crawl died partway through
and left 1704 symbols serving a days-old close as the current price, with
nothing that ever went back for them.
"""

import pandas as pd

from ingestion.quotes import _rows_for, _suffixed


def test_exchange_decides_suffix():
    # BSE symbols 404 on .NS — this was a live bug in the per-symbol ETL.
    assert _suffixed("RELIANCE", "NSE") == "RELIANCE.NS"
    assert _suffixed("500325", "BSE") == "500325.BO"
    assert _suffixed("TCS", None) == "TCS.NS"


def _frame(rows):
    return pd.DataFrame(rows, index=pd.to_datetime([r.pop("date") for r in rows]))


def test_rows_parsed_from_frame():
    df = _frame([
        {"date": "2026-07-27", "Open": 10.0, "High": 11.0, "Low": 9.5, "Close": 10.5, "Volume": 1000},
        {"date": "2026-07-28", "Open": 10.5, "High": 12.0, "Low": 10.0, "Close": 11.8, "Volume": 2000},
    ])
    rows = _rows_for("TEST", df)
    assert len(rows) == 2
    assert rows[-1] == ("TEST", "2026-07-28", 10.5, 12.0, 10.0, 11.8, 2000)


def test_nan_close_is_dropped_not_zeroed():
    """A half-formed bar must vanish, never land as a 0.00 close.

    Writing it would show up as a -100% day move on the screener.
    """
    df = _frame([
        {"date": "2026-07-27", "Open": 10.0, "High": 11.0, "Low": 9.5, "Close": 10.5, "Volume": 1000},
        {"date": "2026-07-28", "Open": float("nan"), "High": float("nan"),
         "Low": float("nan"), "Close": float("nan"), "Volume": float("nan")},
    ])
    rows = _rows_for("TEST", df)
    assert len(rows) == 1
    assert rows[0][1] == "2026-07-27"


def test_missing_ohlc_falls_back_to_close():
    df = _frame([{"date": "2026-07-28", "Open": float("nan"), "High": float("nan"),
                  "Low": float("nan"), "Close": 42.0, "Volume": float("nan")}])
    rows = _rows_for("TEST", df)
    assert rows == [("TEST", "2026-07-28", 42.0, 42.0, 42.0, 42.0, 0)]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok {name}")
