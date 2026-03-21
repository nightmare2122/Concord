"""
Bots/utils/timezone.py — Centralized Timezone Definition
Copyright (c) 2026 Concord Desk. All rights reserved.
PROPRIETARY AND CONFIDENTIAL.

Single source of truth for the IST timezone used across all Concord modules.
Import `IST` or `now_ist()` from here instead of defining timezone locally.
"""

from datetime import datetime, timedelta, timezone

# IST Timezone (UTC+5:30) — used globally for all Concord timestamps
IST = timezone(timedelta(hours=5, minutes=30))


def now_ist() -> datetime:
    """Return the current datetime in IST."""
    return datetime.now(IST)


# ---------------------------------------------------------------------------
# Flexible date / time parsers
# ---------------------------------------------------------------------------
# Accepted date separators: / . -   Year: 4-digit or 2-digit (YY → 2000+YY)
# Accepted time separators: : .     Clock: 12-hour AM/PM only
# Each function returns (datetime_obj, canonical_str) so callers can both
# validate and persist a normalised value in one step.
# ---------------------------------------------------------------------------

_DATE_FMTS = [
    "%d/%m/%Y", "%d/%m/%y",
    "%d.%m.%Y", "%d.%m.%y",
    "%d-%m-%Y", "%d-%m-%y",
]
_TIME_FMTS = ["%I:%M %p", "%I.%M %p"]


def parse_datetime_flexible(date_str: str, time_str: str) -> tuple[datetime, str]:
    """Parse date + time accepting multiple separators and 2/4-digit years.

    Returns (datetime_obj, canonical) where canonical is 'DD/MM/YYYY HH:MM AM/PM'
    (the format used for task deadline storage).
    Raises ValueError with a user-friendly message on failure.
    """
    date_str = date_str.strip()
    time_str = time_str.strip().upper()

    for dfmt in _DATE_FMTS:
        for tfmt in _TIME_FMTS:
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", f"{dfmt} {tfmt}")
                return dt, dt.strftime("%d/%m/%Y %I:%M %p")
            except ValueError:
                continue

    raise ValueError(
        f"Unrecognised date/time: '{date_str}  {time_str}'. "
        "Date: DD/MM/YYYY, DD.MM.YY, DD-MM-YYYY etc. "
        "Time: HH:MM AM/PM or HH.MM AM/PM (e.g. 02:30 PM)."
    )


def parse_date_flexible(date_str: str) -> tuple[datetime, str]:
    """Parse a date-only string accepting multiple separators and year lengths.

    Returns (datetime_obj, canonical) where canonical is 'DD-MM-YYYY'
    (the format used for leave date storage).
    Raises ValueError with a user-friendly message on failure.
    """
    date_str = date_str.strip()

    for dfmt in _DATE_FMTS:
        try:
            dt = datetime.strptime(date_str, dfmt)
            return dt, dt.strftime("%d-%m-%Y")
        except ValueError:
            continue

    raise ValueError(
        f"Unrecognised date: '{date_str}'. "
        "Use DD-MM-YYYY, DD/MM/YYYY, DD.MM.YY etc. (e.g. 27-03-2026)."
    )


def parse_time_flexible(time_str: str) -> tuple[datetime, str]:
    """Parse a 12-hour time string accepting : or . as separator.

    Returns (datetime_obj, canonical) where canonical is 'HH:MM AM/PM'.
    Raises ValueError with a user-friendly message on failure.
    """
    time_str = time_str.strip().upper()

    for tfmt in _TIME_FMTS:
        try:
            dt = datetime.strptime(time_str, tfmt)
            return dt, dt.strftime("%I:%M %p")
        except ValueError:
            continue

    raise ValueError(
        f"Unrecognised time: '{time_str}'. "
        "Use HH:MM AM/PM or HH.MM AM/PM (e.g. 09:30 AM)."
    )
