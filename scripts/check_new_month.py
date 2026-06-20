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
from datetime import date

# CIA / FTSE Russell prescribed CV rates for month M are typically published in
# the first days of month M (derived from the prior month-end bond yields).
# Treat month M as "expected available" once we are at/after this day-of-month.
PUBLISH_DAY = int(os.environ.get("PUBLISH_DAY", "5"))


def month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def expected_latest(today: date) -> str:
    if today.day >= PUBLISH_DAY:
        return month_key(today.year, today.month)
    year, month = previous_month(today.year, today.month)
    return month_key(year, month)


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "cia_rates.json"
    with open(path) as f:
        data = json.load(f)

    latest = max(r["monthKey"] for r in data)
    expected = expected_latest(date.today())
    due = expected > latest

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
