#!/usr/bin/env python3
"""Fetch reviewed CIA commuted-value rates from Penad.

Penad is an approved reviewed-source fallback when Convyta has not yet exposed
a clear current-month row. This script only accepts the Penad commuted-value
interest-rate table and exits non-zero for blank, missing, ambiguous, stale, or
malformed source content.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

PENAD_RATES_URL = "https://penad.com/resources/rates/commuted-value-interest-rates/"
APPROVED_DOMAINS = {"penad.com", "www.penad.com"}
MONTH_NAMES = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}
MONTH_KEY_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
NUMBER_RE = re.compile(r"^\d+(?:\.\d+)?%?$")
YEAR_HEADING_RE = re.compile(r"^\d{4}\s+Commuted Value Interest Rates", re.I)


class SourceError(Exception):
    pass


@dataclass(frozen=True)
class ExtractedRate:
    month_key: str
    i1: float
    i2: float
    source_name: str
    source_url: str
    source_type: str
    heading: str
    extracted_text: str
    retrieved_at_utc: str
    content_sha256: str
    corroboration_status: str = "not_checked"


class TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        stripped = normalize_space(data)
        if stripped:
            self.parts.append(stripped)


def normalize_space(value: str) -> str:
    return " ".join(html.unescape(value).replace("\xa0", " ").split())


def fetch_url(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "cvcalc-data-rate-discovery/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def is_approved_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() in APPROVED_DOMAINS


def month_abbrev(month_key: str) -> str:
    year, month = month_key.split("-")
    for name, number in MONTH_NAMES.items():
        if number == month:
            return name.upper()
    raise SourceError(f"invalid target month: {month_key}")


def decimal_percent(value: str) -> float:
    cleaned = normalize_space(value).rstrip("%")
    if not NUMBER_RE.match(value) or not cleaned:
        raise SourceError(f"non-numeric percent value: {value!r}")
    return round(float(cleaned) / 100, 3)


def html_text_parts(html_text: str) -> list[str]:
    parser = TextParser()
    parser.feed(html_text)
    return parser.parts


def find_year_section(parts: list[str], year: str) -> tuple[str, list[str]]:
    heading_index: int | None = None
    heading = ""
    for index, part in enumerate(parts):
        if YEAR_HEADING_RE.match(part):
            if part.startswith(year):
                heading_index = index
                heading = part
                break
    if heading_index is None:
        raise SourceError(f"no {year} commuted-value interest-rate section found")

    section: list[str] = []
    for part in parts[heading_index + 1 :]:
        if YEAR_HEADING_RE.match(part):
            break
        section.append(part)
    return heading, section


def require_headers(section: list[str]) -> None:
    lowered = [part.lower() for part in section[:12]]
    if "month" not in lowered or "rate" not in lowered or "post period rate" not in lowered:
        raise SourceError("malformed Penad table: expected Month, Rate, and Post Period Rate headers")


def extract_from_html(html_text: str, source_url: str, target_month: str) -> ExtractedRate:
    if not MONTH_KEY_RE.match(target_month):
        raise SourceError("target month must be YYYY-MM")
    year, _ = target_month.split("-")
    target = month_abbrev(target_month)
    parts = html_text_parts(html_text)
    heading, section = find_year_section(parts, year)
    require_headers(section)

    matches: list[tuple[str, str, str]] = []
    for index, part in enumerate(section):
        if part.upper() != target:
            continue
        if index + 2 >= len(section):
            raise SourceError(f"blank Penad row for {target_month}")
        i1_text = section[index + 1]
        i2_text = section[index + 2]
        if i1_text.lower() in MONTH_NAMES or i2_text.lower() in MONTH_NAMES:
            raise SourceError(f"blank Penad row for {target_month}")
        matches.append((part, i1_text, i2_text))

    if not matches:
        raise SourceError(f"no {target_month} Penad commuted-value row found")
    unique = set(matches)
    if len(unique) > 1:
        raise SourceError(f"multiple conflicting {target_month} Penad rows found")

    month_text, i1_text, i2_text = matches[0]
    extracted_text = f"{month_text.upper()} | {normalize_space(i1_text).rstrip('%')} | {normalize_space(i2_text).rstrip('%')}"
    return ExtractedRate(
        month_key=target_month,
        i1=decimal_percent(i1_text),
        i2=decimal_percent(i2_text),
        source_name="Penad",
        source_url=source_url,
        source_type="html",
        heading=heading,
        extracted_text=extracted_text,
        retrieved_at_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        content_sha256=hashlib.sha256(html_text.encode("utf-8")).hexdigest(),
    )


def next_month(month_key: str) -> str:
    if not MONTH_KEY_RE.match(month_key):
        raise SourceError(f"invalid month key: {month_key}")
    year, month = (int(part) for part in month_key.split("-"))
    if month == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month + 1:02d}"


def validate_against_rates(rate: ExtractedRate, rates_path: Path) -> None:
    with rates_path.open() as f:
        data = json.load(f)
    existing = {row["monthKey"] for row in data}
    if rate.month_key in existing:
        raise SourceError(f"{rate.month_key} already exists in {rates_path}")
    latest = max(existing)
    expected_next = next_month(latest)
    if rate.month_key != expected_next:
        raise SourceError(f"{rate.month_key} is not expected next month after {latest} ({expected_next})")
    for field in ("i1", "i2"):
        value = getattr(rate, field)
        if not isinstance(value, float) or not (0.0 <= value <= 0.12):
            raise SourceError(f"{field}={value} outside hard plausibility bounds")


def load_source(args: argparse.Namespace) -> tuple[str, str]:
    if args.html_file:
        path = Path(args.html_file)
        return path.read_text(encoding="utf-8"), args.source_url or PENAD_RATES_URL
    source_url = args.source_url or PENAD_RATES_URL
    if not is_approved_url(source_url):
        raise SourceError(f"unapproved source URL: {source_url}")
    return fetch_url(source_url), source_url


def emit_outputs(rate: ExtractedRate | None, found: bool, error: str | None = None) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(f"found={'true' if found else 'false'}\n")
        if error:
            f.write(f"error={error}\n")
        if found and rate is not None:
            f.write(f"month={rate.month_key}\n")
            f.write(f"i1={rate.i1}\n")
            f.write(f"i2={rate.i2}\n")
            f.write(f"source_name={rate.source_name}\n")
            f.write(f"source_url={rate.source_url}\n")
            f.write(f"source_type={rate.source_type}\n")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="target month, YYYY-MM")
    parser.add_argument("--rates-file", default="cia_rates.json")
    parser.add_argument("--source-url", default=PENAD_RATES_URL)
    parser.add_argument("--html-file", help="test fixture or saved HTML file")
    parser.add_argument("--json-out", help="write normalized evidence JSON")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    try:
        html_text, source_url = load_source(args)
        rate = extract_from_html(html_text, source_url, args.month)
        validate_against_rates(rate, Path(args.rates_file))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(rate.__dict__, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(rate.__dict__, indent=2))
        emit_outputs(rate, True)
        return 0
    except Exception as exc:
        print(f"UNAVAILABLE: {exc}", file=sys.stderr)
        emit_outputs(None, False, str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
