#!/usr/bin/env python3
"""Detect whether a CIA commuted-value rate month newer than the latest in
cia_rates.json is expected to be published but is missing.

Never fabricates or writes values. Detection only — the workflow decides whether
to alert. Always exits 0 (a missing month is a signal, not a job failure).

Emits GitHub Actions outputs when $GITHUB_OUTPUT is set:
  new_month_due   = true|false
  expected_month  = YYYY-MM
  latest_in_data  = YYYY-MM

Usage: python3 scripts/check_new_month.py [path]   (default: cia_rates.json)
"""
import json
import os
import sys
from datetime import date, timedelta

WEDNESDAY = 2


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def last_wednesday(year: int, month: int) -> date:
    next_year, next_month_number = next_month(year, month)
    cursor = date(next_year, next_month_number, 1) - timedelta(days=1)
    while cursor.weekday() != WEDNESDAY:
        cursor -= timedelta(days=1)
    return cursor


def next_business_day(day: date) -> date:
    cursor = day + timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor += timedelta(days=1)
    return cursor


def expected_latest(today: date) -> str:
    """Return the latest valuation month expected to be discoverable by date.

    Convyta says rates for month M are normally available by the end of the
    first business day after the last Wednesday of month M-1. Statutory
    holidays are intentionally not modeled here: checking early is safe because
    a missing source is a normal no-result condition.
    """
    publication_check_starts = next_business_day(last_wednesday(today.year, today.month))
    if today >= publication_check_starts:
        year, month = next_month(today.year, today.month)
        return month_key(year, month)
    return month_key(today.year, today.month)


def discovery_status(data: list[dict[str, object]], today: date) -> tuple[str, str, bool]:
    latest = max(str(r["monthKey"]) for r in data)
    expected = expected_latest(today)
    due = expected > latest
    return latest, expected, due


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "cia_rates.json"
    with open(path) as f:
        data = json.load(f)

    latest, expected, due = discovery_status(data, date.today())

    print(f"latest_in_data={latest} expected={expected} new_month_due={str(due).lower()}")

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"new_month_due={str(due).lower()}\n")
            f.write(f"expected_month={expected}\n")
            f.write(f"latest_in_data={latest}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
