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
