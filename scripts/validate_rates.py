#!/usr/bin/env python3
"""Validate cia_rates.json: structure, ordering, plausibility, gaps.

Exit 0 if valid (warnings allowed), 1 if any hard error.
Usage: python3 scripts/validate_rates.py [path]   (default: cia_rates.json)

Validation rules (Data Operations sprint, Task 3):
  - top-level is a non-empty JSON array
  - each monthKey matches YYYY-MM
  - i1 and i2 are numeric (not bool)
  - i1/i2 within hard bounds  -> error if outside
  - i1/i2 within typical band -> warning if outside
  - months strictly ascending, no duplicates
  - consecutive months (gap -> warning, surfaced for review)
"""
import json
import re
import sys

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

# CIA commuted-value i1/i2 have historically sat ~3%-6%. Hard bounds fail the
# build; the typical band only warns (so an unusual-but-real value is reviewable
# rather than silently blocked).
HARD_MIN, HARD_MAX = 0.0, 0.12
SOFT_MIN, SOFT_MAX = 0.02, 0.08


def month_index(key: str) -> int:
    year, month = key.split("-")
    return int(year) * 12 + (int(month) - 1)


def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else "cia_rates.json"
    errors: list[str] = []
    warnings: list[str] = []

    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: cannot read/parse {path}: {exc}")
        return 1

    if not isinstance(data, list) or not data:
        print("ERROR: top-level JSON must be a non-empty array")
        return 1

    seen: set[str] = set()
    prev_idx: int | None = None
    valid_keys: list[str] = []

    for i, row in enumerate(data):
        ctx = f"[{i}] {row.get('monthKey', '?') if isinstance(row, dict) else '?'}"
        if not isinstance(row, dict):
            errors.append(f"{ctx}: entry is not an object")
            continue

        key = row.get("monthKey")
        if not isinstance(key, str) or not MONTH_RE.match(key):
            errors.append(f"{ctx}: invalid monthKey (expected YYYY-MM)")
            continue
        if key in seen:
            errors.append(f"{ctx}: duplicate month")
        seen.add(key)

        idx = month_index(key)
        if prev_idx is not None and idx <= prev_idx:
            errors.append(f"{ctx}: not strictly ascending")
        prev_idx = idx
        valid_keys.append(key)

        for field in ("i1", "i2"):
            value = row.get(field)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(f"{ctx}: {field} is not numeric")
                continue
            if not (HARD_MIN <= value <= HARD_MAX):
                errors.append(
                    f"{ctx}: {field}={value} outside hard bounds [{HARD_MIN}, {HARD_MAX}]"
                )
            elif not (SOFT_MIN <= value <= SOFT_MAX):
                warnings.append(
                    f"{ctx}: {field}={value} outside typical band [{SOFT_MIN}, {SOFT_MAX}] — review"
                )

    # Gap detection across consecutive valid months.
    for a, b in zip(valid_keys, valid_keys[1:]):
        if month_index(b) - month_index(a) != 1:
            warnings.append(f"gap between {a} and {b} (months not consecutive)")

    for w in warnings:
        print(f"WARN: {w}")
    for e in errors:
        print(f"ERROR: {e}")

    if errors:
        print(f"FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1

    print(f"OK: {len(valid_keys)} months, latest {valid_keys[-1]}, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
