#!/usr/bin/env python3
"""Select the reviewed CIA rate source for a due month."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Iterable


class SourceSelectionError(Exception):
    pass


def load_optional_json(path_value: str | None) -> dict[str, object] | None:
    if not path_value:
        return None
    path = Path(path_value)
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def source_name(source: dict[str, object], fallback: str) -> str:
    value = source.get("source_name")
    return str(value) if value else fallback


def rate_tuple(source: dict[str, object]) -> tuple[str, float, float]:
    return (str(source["month_key"]), float(source["i1"]), float(source["i2"]))


def annotate(source: dict[str, object], fallback_name: str, corroboration_status: str) -> dict[str, object]:
    selected = dict(source)
    selected["source_name"] = source_name(selected, fallback_name)
    selected["corroboration_status"] = corroboration_status
    return selected


def select_source(
    month: str,
    convyta: dict[str, object] | None,
    penad: dict[str, object] | None,
) -> dict[str, object]:
    if convyta is not None and str(convyta.get("month_key")) != month:
        raise SourceSelectionError(f"Convyta result is for {convyta.get('month_key')}, expected {month}")
    if penad is not None and str(penad.get("month_key")) != month:
        raise SourceSelectionError(f"Penad result is for {penad.get('month_key')}, expected {month}")

    if convyta is not None and penad is not None:
        if rate_tuple(convyta) != rate_tuple(penad):
            raise SourceSelectionError(
                "reviewed sources disagree: "
                f"Convyta={rate_tuple(convyta)} Penad={rate_tuple(penad)}"
            )
        return annotate(convyta, "Convyta", "penad_agrees")
    if convyta is not None:
        return annotate(convyta, "Convyta", "penad_unavailable")
    if penad is not None:
        return annotate(penad, "Penad", "convyta_unavailable")
    raise SourceSelectionError("no reviewed source found")


def emit_outputs(source: dict[str, object] | None, found: bool, error: str | None = None) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(f"found={'true' if found else 'false'}\n")
        if error:
            f.write(f"error={error}\n")
        if found and source is not None:
            f.write(f"month={source['month_key']}\n")
            f.write(f"i1={source['i1']}\n")
            f.write(f"i2={source['i2']}\n")
            f.write(f"source_name={source['source_name']}\n")
            f.write(f"source_url={source['source_url']}\n")
            f.write(f"source_type={source['source_type']}\n")
            f.write(f"corroboration_status={source['corroboration_status']}\n")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="target month, YYYY-MM")
    parser.add_argument("--convyta-json")
    parser.add_argument("--penad-json")
    parser.add_argument("--json-out", required=True)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    try:
        selected = select_source(
            args.month,
            load_optional_json(args.convyta_json),
            load_optional_json(args.penad_json),
        )
        Path(args.json_out).write_text(json.dumps(selected, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(selected, indent=2))
        emit_outputs(selected, True)
        return 0
    except Exception as exc:
        print(f"UNAVAILABLE: {exc}", file=sys.stderr)
        emit_outputs(None, False, str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
