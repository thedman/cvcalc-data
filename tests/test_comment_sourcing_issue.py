import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "comment_sourcing_issue.py"
SPEC = importlib.util.spec_from_file_location("comment_sourcing_issue", SCRIPT)
comment_sourcing_issue = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["comment_sourcing_issue"] = comment_sourcing_issue
SPEC.loader.exec_module(comment_sourcing_issue)


class CommentSourcingIssueTests(unittest.TestCase):
    def decide(
        self,
        *,
        today: date,
        comments: list[str] | None = None,
        latest: str = "2026-08",
        expected: str = "2026-09",
        source_status: str = "no reviewed source found",
        canonical_current: bool = False,
        source_actionable: bool = False,
    ):
        return comment_sourcing_issue.decide_comment(
            expected=expected,
            latest=latest,
            source_status=source_status,
            existing_comments=comments or [],
            today=today,
            canonical_current=canonical_current,
            source_actionable=source_actionable,
        )

    def test_day_14_uses_normal_non_overdue_comment(self) -> None:
        decision = self.decide(today=date(2026, 9, 14))
        self.assertIsNotNone(decision.body)
        self.assertFalse(decision.add_overdue_label)
        self.assertIn("did not find a usable 2026-09 row", decision.body or "")

    def test_day_15_escalates_overdue(self) -> None:
        decision = self.decide(today=date(2026, 9, 15))
        self.assertIsNotNone(decision.body)
        self.assertTrue(decision.add_overdue_label)
        self.assertIn("Overdue monthly-rate source status", decision.body or "")

    def test_repeated_day_15_run_does_not_duplicate(self) -> None:
        first = self.decide(today=date(2026, 9, 15))
        second = self.decide(today=date(2026, 9, 15), comments=[first.body or ""])
        self.assertIsNone(second.body)
        self.assertTrue(second.add_overdue_label)

    def test_later_identical_run_does_not_duplicate(self) -> None:
        first = self.decide(today=date(2026, 9, 15))
        second = self.decide(today=date(2026, 9, 23), comments=[first.body or ""])
        self.assertIsNone(second.body)
        self.assertTrue(second.add_overdue_label)

    def test_materially_changed_source_status_can_be_surfaced(self) -> None:
        first = self.decide(today=date(2026, 9, 15))
        second = self.decide(
            today=date(2026, 9, 23),
            comments=[first.body or ""],
            source_status="Penad blank; Convyta PDF parser unavailable",
        )
        self.assertIsNotNone(second.body)
        self.assertIn("Convyta PDF parser unavailable", second.body or "")

    def test_canonical_current_does_not_escalate(self) -> None:
        decision = self.decide(today=date(2026, 9, 15), latest="2026-09", canonical_current=True)
        self.assertIsNone(decision.body)
        self.assertFalse(decision.add_overdue_label)

    def test_source_actionable_pr_path_takes_precedence(self) -> None:
        decision = self.decide(today=date(2026, 9, 15), source_actionable=True)
        self.assertIsNone(decision.body)
        self.assertFalse(decision.add_overdue_label)


if __name__ == "__main__":
    unittest.main()
