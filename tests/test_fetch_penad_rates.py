import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fetch_penad_rates.py"
FIXTURES = ROOT / "tests" / "fixtures"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class FetchPenadRatesTests(unittest.TestCase):
    def test_successful_extraction(self) -> None:
        result = run_script(
            "--month", "2026-08",
            "--html-file", str(FIXTURES / "penad_success.html"),
            "--rates-file", str(FIXTURES / "rates_through_july.json"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["month_key"], "2026-08")
        self.assertEqual(data["i1"], 0.039)
        self.assertEqual(data["i2"], 0.053)
        self.assertEqual(data["source_name"], "Penad")
        self.assertEqual(data["source_type"], "html")
        self.assertEqual(data["extracted_text"], "AUG | 3.90 | 5.30")

    def test_blank_month_row_fails(self) -> None:
        result = run_script(
            "--month", "2026-08",
            "--html-file", str(FIXTURES / "penad_blank_month.html"),
            "--rates-file", str(FIXTURES / "rates_through_july.json"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("blank Penad row", result.stderr)

    def test_malformed_table_fails(self) -> None:
        result = run_script(
            "--month", "2026-08",
            "--html-file", str(FIXTURES / "penad_malformed.html"),
            "--rates-file", str(FIXTURES / "rates_through_july.json"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("malformed Penad table", result.stderr)

    def test_wrong_year_section_fails(self) -> None:
        result = run_script(
            "--month", "2026-08",
            "--html-file", str(FIXTURES / "penad_wrong_year.html"),
            "--rates-file", str(FIXTURES / "rates_through_july.json"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no 2026", result.stderr)

    def test_ambiguous_values_fail(self) -> None:
        result = run_script(
            "--month", "2026-08",
            "--html-file", str(FIXTURES / "penad_ambiguous.html"),
            "--rates-file", str(FIXTURES / "rates_through_july.json"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("multiple conflicting", result.stderr)

    def test_wrong_next_month_fails(self) -> None:
        result = run_script(
            "--month", "2026-08",
            "--html-file", str(FIXTURES / "penad_success.html"),
            "--rates-file", str(FIXTURES / "rates_through_june.json"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not expected next month", result.stderr)


if __name__ == "__main__":
    unittest.main()
