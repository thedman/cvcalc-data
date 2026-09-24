#!/usr/bin/env python3
"""Update a monthly CIA rate sourcing issue without noisy duplicate comments."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import date

OVERDUE_LABEL = "overdue-rate-source"


@dataclass(frozen=True)
class CommentDecision:
    body: str | None
    add_overdue_label: bool = False


def month_day(today: date) -> int:
    return today.day


def source_status_hash(source_status: str) -> str:
    return hashlib.sha256(source_status.encode("utf-8")).hexdigest()[:12]


def standard_body(expected: str, source_status: str) -> str:
    return (
        f"Reviewed-source automation did not find a usable {expected} row. "
        f"Reason: {source_status or 'unavailable'}. "
        "The issue remains open for manual sourcing."
    )


def overdue_body(expected: str, latest: str, source_status: str, today: date) -> str:
    status = source_status or "unavailable"
    marker = f"<!-- cia-rate-overdue {expected} {source_status_hash(status)} -->"
    return "\n".join(
        [
            marker,
            f"Overdue monthly-rate source status for {expected} as of {today.isoformat()}.",
            "",
            f"- Expected month: {expected}",
            f"- Canonical latest month: {latest}",
            f"- Reviewed-source status: {status}",
            "- Status: monthly source is overdue under the documented 15th-of-month escalation threshold.",
            "- Canonical data remains unchanged pending reviewed evidence and human-reviewed PR merge.",
        ]
    )


def decide_comment(
    *,
    expected: str,
    latest: str,
    source_status: str,
    existing_comments: list[str],
    today: date,
    canonical_current: bool,
    source_actionable: bool,
) -> CommentDecision:
    if canonical_current or source_actionable:
        return CommentDecision(None)

    if month_day(today) >= 15:
        body = overdue_body(expected, latest, source_status, today)
        marker = f"<!-- cia-rate-overdue {expected} {source_status_hash(source_status or 'unavailable')} -->"
        if any(marker in comment for comment in existing_comments):
            return CommentDecision(None, add_overdue_label=True)
        return CommentDecision(body, add_overdue_label=True)

    body = standard_body(expected, source_status)
    if body in existing_comments:
        return CommentDecision(None)
    return CommentDecision(body)


def gh_json(args: list[str]) -> dict[str, object]:
    result = subprocess.run(["gh", *args], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return json.loads(result.stdout)


def run_gh(args: list[str]) -> None:
    result = subprocess.run(["gh", *args], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


def main() -> int:
    issue_number = os.environ.get("ISSUE_NUMBER", "")
    if not issue_number:
        return 0

    expected = os.environ["EXPECTED"]
    latest = os.environ["LATEST"]
    source_status = os.environ.get("SOURCE_ERROR", "unavailable")
    today = date.fromisoformat(os.environ.get("TODAY", date.today().isoformat()))

    issue = gh_json(["issue", "view", issue_number, "--json", "comments"])
    comments = [str(comment.get("body", "")) for comment in issue.get("comments", [])]
    decision = decide_comment(
        expected=expected,
        latest=latest,
        source_status=source_status,
        existing_comments=comments,
        today=today,
        canonical_current=latest >= expected,
        source_actionable=False,
    )

    if decision.add_overdue_label:
        run_gh(["label", "create", OVERDUE_LABEL, "--color", "d73a4a", "--description", "Monthly CIA rate source is overdue", "--force"])
        run_gh(["issue", "edit", issue_number, "--add-label", OVERDUE_LABEL])
    if decision.body:
        run_gh(["issue", "comment", issue_number, "--body", decision.body])
    return 0


if __name__ == "__main__":
    sys.exit(main())
