#!/usr/bin/env python3
"""Reference-only estimate of CIA commuted-value i1/i2 for a target month,
derived from Bank of Canada marketable-bond yields plus maintained spread
factors.

IMPORTANT: This is a *cross-check reference only*. It is NOT the authoritative
CIA / FTSE Russell prescribed rate and must never be written to cia_rates.json
automatically. A human sources the authoritative value; this estimate exists
only to sanity-check that the sourced value is in the right neighbourhood.

Usage: python3 scripts/boc_estimate.py YYYY-MM
Prints: i1_estimate / i2_estimate (or a clear failure message).
Exits 0 on success, 1 if the source data could not be retrieved.
"""
import json
import os
import sys
import urllib.request
from datetime import date

# Maintained adjustment factors (percentage points) applied to BoC monthly-average
# yields. These approximate the CIA spread; they are heuristic and drift over time.
SPREAD_I1 = 0.60
SPREAD_I2 = 1.61


def preceding_month_window(target: str) -> tuple[str, str]:
    """The CV rate for month M uses the prior month's month-end yields."""
    year, month = (int(x) for x in target.split("-"))
    py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    start = f"{py:04d}-{pm:02d}-01"
    # Last day of the preceding month = day before the target month's 1st.
    first_of_target = date(year, month, 1)
    last_of_prev = date.fromordinal(first_of_target.toordinal() - 1)
    return start, last_of_prev.isoformat()


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: boc_estimate.py YYYY-MM")
        return 1
    target = sys.argv[1]
    start, end = preceding_month_window(target)
    url = (
        "https://www.bankofcanada.ca/valet/observations/group/"
        f"bond_yields_marketable/json?start_date={start}&end_date={end}"
    )
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as exc:  # network / source failure -> report, never guess
        print(f"UNAVAILABLE: could not retrieve BoC reference data: {exc}")
        return 1

    obs = data.get("observations", [])
    s510 = [float(o["CDN.AVG.5YTO10Y.AVG"]["v"]) for o in obs if o.get("CDN.AVG.5YTO10Y.AVG", {}).get("v")]
    s10p = [float(o["CDN.AVG.OVER.10.AVG"]["v"]) for o in obs if o.get("CDN.AVG.OVER.10.AVG", {}).get("v")]
    if not s510 or not s10p:
        print("UNAVAILABLE: expected BoC series missing from response")
        return 1

    i1 = round(round((sum(s510) / len(s510) + SPREAD_I1) * 10) / 10 / 100, 3)
    i2 = round(round((sum(s10p) / len(s10p) + SPREAD_I2) * 10) / 10 / 100, 3)
    print(f"i1_estimate={i1} i2_estimate={i2} window={start}..{end} (REFERENCE ONLY — verify against CIA/FTSE)")

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a") as f:
            f.write(f"i1_estimate={i1}\ni2_estimate={i2}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
