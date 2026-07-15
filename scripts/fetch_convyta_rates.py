#!/usr/bin/env python3
"""Fetch reviewed CIA commuted-value rates from Convyta.

The primary evidence path is Convyta-hosted HTML. PDF evidence is optional
corroboration only; a clear HTML table is sufficient.

This script never guesses from estimates. It exits non-zero when the source
content is stale, ambiguous, missing, or cannot be mapped to the commuted-value
columns.
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
from io import BytesIO
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

CONVYTA_RESOURCES_URL = "https://convyta.com/resources"
APPROVED_DOMAINS = {"convyta.com", "www.convyta.com"}
GUIDANCE_PATTERNS = (
    "cia commuted value",
    "group annuity proxy guidance",
    "cv rates and annuity guidance",
    "commuted value interest rates",
)
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
PERCENT_RE = re.compile(r"^\d+(?:\.\d+)?%$")


class SourceError(Exception):
    pass


@dataclass(frozen=True)
class ExtractedRate:
    month_key: str
    i1: float
    i2: float
    source_url: str
    source_type: str
    heading: str
    extracted_text: str
    retrieved_at_utc: str
    content_sha256: str
    pdf_status: str = "not_checked"

    def as_rate_row(self) -> dict[str, object]:
        return {"monthKey": self.month_key, "i1": self.i1, "i2": self.i2}


class EvidenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.links: list[str] = []
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            attrs_dict = {k.lower(): v for k, v in attrs if v is not None}
            self._href = attrs_dict.get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a":
            self._href = None

    def handle_data(self, data: str) -> None:
        stripped = " ".join(data.split())
        if stripped:
            self.text_parts.append(stripped)
        if self._href:
            self.links.append(self._href)

    def text(self) -> str:
        return " ".join(self.text_parts)


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "table":
            self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            stripped = " ".join(data.split())
            if stripped:
                self._current_cell.append(stripped)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._current_cell is not None and self._current_row is not None:
            self._current_row.append(" ".join(self._current_cell).strip())
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None and self._current_table is not None:
            if any(self._current_row):
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._current_table is not None:
            self.tables.append(self._current_table)
            self._current_table = None


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


def target_label(month_key: str) -> str:
    year, month = month_key.split("-")
    for name, number in MONTH_NAMES.items():
        if number == month:
            return f"{name.title()}-{year}"
    raise SourceError(f"invalid target month: {month_key}")


def normalize_month(value: str) -> str | None:
    cleaned = normalize_space(value).strip(".")
    m = re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[- ](\d{4})$", cleaned, re.I)
    if m:
        return f"{m.group(2)}-{MONTH_NAMES[m.group(1)[:3].lower()]}"
    m = re.match(r"^(\d{4})-(0[1-9]|1[0-2])$", cleaned)
    if m:
        return cleaned
    return None


def percent_to_decimal(value: str) -> float:
    cleaned = normalize_space(value)
    if not PERCENT_RE.match(cleaned):
        raise SourceError(f"non-numeric percent value: {value!r}")
    return round(float(cleaned[:-1]) / 100, 3)


def guidance_heading(text: str) -> str:
    lowered = text.lower()
    for pattern in GUIDANCE_PATTERNS:
        idx = lowered.find(pattern)
        if idx != -1:
            start = max(0, idx - 80)
            end = min(len(text), idx + 160)
            return normalize_space(text[start:end])
    raise SourceError("source content does not identify CIA/CV guidance")


def table_has_guidance_context(table: list[list[str]], page_text: str) -> bool:
    table_text = normalize_space(" ".join(cell for row in table for cell in row)).lower()
    combined = f"{page_text.lower()} {table_text}"
    return any(pattern in combined for pattern in GUIDANCE_PATTERNS)


def header_indices(header: list[str]) -> tuple[int, int, int] | None:
    normalized = [normalize_space(cell).lower() for cell in header]
    try:
        period_idx = next(i for i, cell in enumerate(normalized) if "period" in cell or "month" in cell)
        i1_idx = next(i for i, cell in enumerate(normalized) if "first 10" in cell)
        i2_idx = next(i for i, cell in enumerate(normalized) if "thereafter" in cell)
        return period_idx, i1_idx, i2_idx
    except StopIteration:
        return None


def extract_from_tables(html_text: str, source_url: str, target_month: str) -> ExtractedRate:
    evidence = EvidenceParser()
    evidence.feed(html_text)
    page_text = normalize_space(evidence.text())
    heading = guidance_heading(page_text)

    parser = TableParser()
    parser.feed(html_text)
    matches: list[tuple[list[str], tuple[int, int, int]]] = []

    for table in parser.tables:
        if not table_has_guidance_context(table, page_text):
            continue
        for header_pos, header in enumerate(table):
            indices = header_indices(header)
            if indices is None:
                continue
            period_idx, i1_idx, i2_idx = indices
            for row in table[header_pos + 1 :]:
                if max(indices) >= len(row):
                    continue
                if normalize_month(row[period_idx]) == target_month:
                    matches.append((row, indices))

    if not matches:
        raise SourceError(f"no unambiguous {target_label(target_month)} commuted-value row found")
    unique_rows = {tuple(row) for row, _ in matches}
    if len(unique_rows) > 1:
        raise SourceError(f"multiple conflicting {target_label(target_month)} rows found")

    row, indices = matches[0]
    _, i1_idx, i2_idx = indices
    extracted_text = " | ".join(normalize_space(cell) for cell in row)
    return ExtractedRate(
        month_key=target_month,
        i1=percent_to_decimal(row[i1_idx]),
        i2=percent_to_decimal(row[i2_idx]),
        source_url=source_url,
        source_type="html",
        heading=heading,
        extracted_text=extracted_text,
        retrieved_at_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        content_sha256=hashlib.sha256(html_text.encode("utf-8")).hexdigest(),
    )


def extract_from_plain_text(text: str, source_url: str, target_month: str, source_type: str) -> ExtractedRate:
    page_text = normalize_space(text)
    heading = guidance_heading(page_text)
    target = target_label(target_month)
    idx = page_text.lower().find("commuted value interest rates")
    if idx == -1:
        raise SourceError("plain text does not identify commuted-value interest-rate section")
    scoped = page_text[idx:]
    row_match = re.search(
        rf"\b{re.escape(target)}\b\s+(\d+(?:\.\d+)?%)\s+(\d+(?:\.\d+)?%)",
        scoped,
        re.I,
    )
    if not row_match:
        raise SourceError(f"no {target} commuted-value row found in plain text")
    extracted_text = f"{target} | {row_match.group(1)} | {row_match.group(2)}"
    return ExtractedRate(
        month_key=target_month,
        i1=percent_to_decimal(row_match.group(1)),
        i2=percent_to_decimal(row_match.group(2)),
        source_url=source_url,
        source_type=source_type,
        heading=heading,
        extracted_text=extracted_text,
        retrieved_at_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        pdf_status="used" if source_type == "pdf" else "not_checked",
    )


def discover_pdf_links(html_text: str, base_url: str) -> list[str]:
    parser = EvidenceParser()
    parser.feed(html_text)
    links: list[str] = []
    for link in parser.links:
        absolute = urllib.parse.urljoin(base_url, link)
        if urllib.parse.urlparse(absolute).path.lower().endswith(".pdf") and is_approved_url(absolute):
            links.append(absolute)
    return sorted(set(links))


def extract_pdf_text(url: str) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise SourceError("pypdf unavailable for optional PDF fallback") from exc
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "cvcalc-data-rate-discovery/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data = response.read()
    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def discover_html_links(html_text: str, base_url: str) -> list[str]:
    parser = EvidenceParser()
    parser.feed(html_text)
    links: list[str] = []
    for link in parser.links:
        absolute = urllib.parse.urljoin(base_url, link)
        parsed = urllib.parse.urlparse(absolute)
        if not is_approved_url(absolute):
            continue
        if parsed.path.lower().endswith(".pdf"):
            continue
        normalized = absolute.lower().replace("-", " ").replace("_", " ")
        if any(token in normalized for token in ("cia", "commuted", "annuity", "guidance", "rates")):
            links.append(absolute)
    return sorted(set(links))


def extract_from_resources(html_text: str, source_url: str, target_month: str) -> ExtractedRate:
    errors: list[str] = []
    try:
        return extract_from_tables(html_text, source_url, target_month)
    except SourceError as exc:
        errors.append(f"{source_url}: {exc}")

    for link in discover_html_links(html_text, source_url)[:10]:
        try:
            linked_html = fetch_url(link)
            return extract_from_tables(linked_html, link, target_month)
        except Exception as exc:
            errors.append(f"{link}: {exc}")

    for link in discover_pdf_links(html_text, source_url)[:5]:
        try:
            pdf_text = extract_pdf_text(link)
            return extract_from_plain_text(pdf_text, link, target_month, "pdf")
        except Exception as exc:
            errors.append(f"{link}: {exc}")

    raise SourceError("; ".join(errors))


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


def next_month(month_key: str) -> str:
    if not MONTH_KEY_RE.match(month_key):
        raise SourceError(f"invalid month key: {month_key}")
    year, month = (int(part) for part in month_key.split("-"))
    if month == 12:
        return f"{year + 1:04d}-01"
    return f"{year:04d}-{month + 1:02d}"


def append_rate(rate: ExtractedRate, rates_path: Path) -> None:
    with rates_path.open() as f:
        data = json.load(f)
    data.append(rate.as_rate_row())
    data.sort(key=lambda row: row["monthKey"])
    with rates_path.open("w", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def load_source(args: argparse.Namespace) -> tuple[str, str]:
    if args.html_file:
        path = Path(args.html_file)
        return path.read_text(encoding="utf-8"), args.source_url or CONVYTA_RESOURCES_URL
    source_url = args.source_url or CONVYTA_RESOURCES_URL
    if not is_approved_url(source_url):
        raise SourceError(f"unapproved source URL: {source_url}")
    return fetch_url(source_url), source_url


def emit_outputs(rate: ExtractedRate, found: bool, error: str | None = None) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with open(output_path, "a", encoding="utf-8") as f:
        f.write(f"found={'true' if found else 'false'}\n")
        if error:
            f.write(f"error={error}\n")
        if found:
            f.write(f"month={rate.month_key}\n")
            f.write(f"i1={rate.i1}\n")
            f.write(f"i2={rate.i2}\n")
            f.write(f"source_url={rate.source_url}\n")
            f.write(f"source_type={rate.source_type}\n")


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--month", required=True, help="target month, YYYY-MM")
    parser.add_argument("--rates-file", default="cia_rates.json")
    parser.add_argument("--source-url", default=CONVYTA_RESOURCES_URL)
    parser.add_argument("--html-file", help="test fixture or saved HTML file")
    parser.add_argument("--json-out", help="write normalized evidence JSON")
    parser.add_argument("--append-rate", action="store_true", help="append the sourced row to rates file")
    parser.add_argument("--check-pdf-links", action="store_true", help="record direct PDF links when present")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] = sys.argv[1:]) -> int:
    args = parse_args(argv)
    try:
        if not MONTH_KEY_RE.match(args.month):
            raise SourceError("--month must be YYYY-MM")
        html_text, source_url = load_source(args)
        if args.html_file:
            rate = extract_from_tables(html_text, source_url, args.month)
        else:
            rate = extract_from_resources(html_text, source_url, args.month)
        validate_against_rates(rate, Path(args.rates_file))
        if args.check_pdf_links:
            pdf_links = discover_pdf_links(html_text, source_url)
            rate = ExtractedRate(**{**rate.__dict__, "pdf_status": "available" if pdf_links else "not_found"})
        if args.append_rate:
            append_rate(rate, Path(args.rates_file))
        if args.json_out:
            Path(args.json_out).write_text(json.dumps(rate.__dict__, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(rate.__dict__, indent=2))
        emit_outputs(rate, True)
        return 0
    except Exception as exc:
        print(f"UNAVAILABLE: {exc}", file=sys.stderr)
        output_path = os.environ.get("GITHUB_OUTPUT")
        if output_path:
            with open(output_path, "a", encoding="utf-8") as f:
                f.write("found=false\n")
                f.write(f"error={exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
