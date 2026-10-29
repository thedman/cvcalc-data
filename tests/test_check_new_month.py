import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_new_month.py"
SPEC = importlib.util.spec_from_file_location("check_new_month", SCRIPT)
check_new_month = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["check_new_month"] = check_new_month
SPEC.loader.exec_module(check_new_month)


def rates_through(month_key: str) -> list[dict[str, object]]:
    return [{"monthKey": month_key, "i1": 0.037, "i2": 0.05}]


class CheckNewMonthTests(unittest.TestCase):
    def test_no_preceding_month_discovery(self) -> None:
        self.assertEqual(check_new_month.last_wednesday(2026, 8), date(2026, 8, 26))
        self.assertEqual(check_new_month.expected_latest(date(2026, 8, 27)), "2026-08")

    def test_weekend_transition_for_business_day_helper(self) -> None:
        self.assertEqual(
            check_new_month.next_business_day(date(2026, 8, 28)),
            date(2026, 8, 31),
        )

    def test_before_publication_window_keeps_current_month_expected(self) -> None:
        self.assertEqual(check_new_month.expected_latest(date(2026, 8, 26)), "2026-08")

    def test_fifth_starts_current_month_publication(self) -> None:
        latest, expected, due = check_new_month.discovery_status(
            rates_through("2026-08"),
            date(2026, 9, 5),
        )
        self.assertEqual((latest, expected, due), ("2026-08", "2026-09", True))

    def test_delayed_publication_remains_due_after_normal_window(self) -> None:
        latest, expected, due = check_new_month.discovery_status(
            rates_through("2026-08"),
            date(2026, 9, 15),
        )
        self.assertEqual((latest, expected, due), ("2026-08", "2026-09", True))

    def test_year_end_december_to_january(self) -> None:
        self.assertEqual(check_new_month.last_wednesday(2026, 12), date(2026, 12, 30))
        self.assertEqual(check_new_month.expected_latest(date(2026, 12, 31)), "2026-12")

    def test_first_through_fourth_keep_previous_month(self):
        for day in range(1, 5):
            self.assertEqual(check_new_month.expected_latest(date(2026, 11, day)), "2026-10")
        self.assertEqual(check_new_month.expected_latest(date(2026, 11, 5)), "2026-11")
        self.assertEqual(check_new_month.expected_latest(date(2027, 1, 4)), "2026-12")
        self.assertEqual(check_new_month.expected_latest(date(2027, 1, 5)), "2027-01")

    def test_sourcing_escalation_uses_missing_month(self):
        self.assertFalse(check_new_month.sourcing_overdue("2026-11", date(2026, 11, 14)))
        self.assertTrue(check_new_month.sourcing_overdue("2026-11", date(2026, 11, 15)))
        self.assertTrue(check_new_month.sourcing_overdue("2026-10", date(2026, 11, 1)))

    def test_canonical_already_current(self) -> None:
        latest, expected, due = check_new_month.discovery_status(
            rates_through("2026-09"),
            date(2026, 9, 15),
        )
        self.assertEqual((latest, expected, due), ("2026-09", "2026-09", False))

    def test_canonical_one_month_behind(self) -> None:
        latest, expected, due = check_new_month.discovery_status(
            rates_through("2026-07"),
            date(2026, 9, 15),
        )
        self.assertEqual((latest, expected, due), ("2026-07", "2026-09", True))


if __name__ == "__main__":
    unittest.main()
