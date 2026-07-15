import json
import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "fetch_convyta_rates.py"
FIXTURES = ROOT / "tests" / "fixtures"
SPEC = importlib.util.spec_from_file_location("fetch_convyta_rates", SCRIPT)
fetch_convyta_rates = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["fetch_convyta_rates"] = fetch_convyta_rates
SPEC.loader.exec_module(fetch_convyta_rates)


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class FetchConvytaRatesTests(unittest.TestCase):
    def test_successful_html_extraction(self) -> None:
        result = run_script(
            "--month", "2026-07",
            "--html-file", str(FIXTURES / "convyta_success.html"),
            "--rates-file", str(FIXTURES / "rates_through_june.json"),
            "--check-pdf-links",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["month_key"], "2026-07")
        self.assertEqual(data["i1"], 0.037)
        self.assertEqual(data["i2"], 0.05)
        self.assertEqual(data["source_type"], "html")
        self.assertEqual(data["pdf_status"], "available")

    def test_stale_html_fails(self) -> None:
        result = run_script(
            "--month", "2026-07",
            "--html-file", str(FIXTURES / "convyta_stale.html"),
            "--rates-file", str(FIXTURES / "rates_through_june.json"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no unambiguous", result.stderr)

    def test_missing_row_fails(self) -> None:
        result = run_script(
            "--month", "2026-08",
            "--html-file", str(FIXTURES / "convyta_success.html"),
            "--rates-file", str(FIXTURES / "rates_through_july.json"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no unambiguous", result.stderr)

    def test_ambiguous_columns_fail(self) -> None:
        result = run_script(
            "--month", "2026-07",
            "--html-file", str(FIXTURES / "convyta_ambiguous_columns.html"),
            "--rates-file", str(FIXTURES / "rates_through_june.json"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no unambiguous", result.stderr)

    def test_duplicate_month_in_rates_fails(self) -> None:
        result = run_script(
            "--month", "2026-07",
            "--html-file", str(FIXTURES / "convyta_success.html"),
            "--rates-file", str(FIXTURES / "rates_through_july.json"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)

    def test_duplicate_conflicting_source_rows_fail(self) -> None:
        result = run_script(
            "--month", "2026-07",
            "--html-file", str(FIXTURES / "convyta_duplicate_conflict.html"),
            "--rates-file", str(FIXTURES / "rates_through_june.json"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("multiple conflicting", result.stderr)

    def test_non_numeric_values_fail(self) -> None:
        result = run_script(
            "--month", "2026-07",
            "--html-file", str(FIXTURES / "convyta_non_numeric.html"),
            "--rates-file", str(FIXTURES / "rates_through_june.json"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-numeric", result.stderr)

    def test_annuity_columns_are_not_extracted(self) -> None:
        result = run_script(
            "--month", "2026-07",
            "--html-file", str(FIXTURES / "convyta_annuity_only.html"),
            "--rates-file", str(FIXTURES / "rates_through_june.json"),
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no unambiguous", result.stderr)

    def test_pdf_unavailable_but_valid_html_present(self) -> None:
        result = run_script(
            "--month", "2026-07",
            "--html-file", str(FIXTURES / "convyta_success.html"),
            "--rates-file", str(FIXTURES / "rates_through_june.json"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["pdf_status"], "not_checked")

    def test_pdf_fallback_when_html_has_no_values(self) -> None:
        resources_html = (FIXTURES / "convyta_resources_with_pdf_link.html").read_text()
        pdf_text = (
            "CIA Commuted Value and Group Annuity Proxy Guidance "
            "COMMUTED VALUE INTEREST RATES "
            "Period First 10 Yrs. Thereafter "
            "Jul-2026 3.7% 5.0% "
            "GROUP ANNUITY PROXY INTEREST RATES Short Medium Long"
        )

        original_extract_pdf = fetch_convyta_rates.extract_pdf_text
        try:
            fetch_convyta_rates.extract_pdf_text = lambda url: pdf_text
            rate = fetch_convyta_rates.extract_from_resources(
                resources_html,
                "https://convyta.com/resources",
                "2026-07",
            )
        finally:
            fetch_convyta_rates.extract_pdf_text = original_extract_pdf

        self.assertEqual(rate.source_url, "https://convyta.com/files/cv-rates-and-annuity-guidance.pdf")
        self.assertEqual(rate.source_type, "pdf")
        self.assertEqual(rate.pdf_status, "used")
        self.assertEqual(rate.i1, 0.037)
        self.assertEqual(rate.i2, 0.05)

    def test_resources_page_can_discover_linked_html_guidance(self) -> None:
        resources_html = (FIXTURES / "convyta_resources_with_link.html").read_text()
        guidance_html = (FIXTURES / "convyta_success.html").read_text()

        original_fetch = fetch_convyta_rates.fetch_url
        try:
            fetch_convyta_rates.fetch_url = lambda url: guidance_html
            rate = fetch_convyta_rates.extract_from_resources(
                resources_html,
                "https://convyta.com/resources",
                "2026-07",
            )
        finally:
            fetch_convyta_rates.fetch_url = original_fetch

        self.assertEqual(rate.source_url, "https://convyta.com/resources/cv-rates-and-annuity-guidance")
        self.assertEqual(rate.i1, 0.037)
        self.assertEqual(rate.i2, 0.05)

    def test_append_rate_writes_only_new_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            rates = Path(temp_dir) / "rates.json"
            shutil.copyfile(FIXTURES / "rates_through_june.json", rates)
            result = run_script(
                "--month", "2026-07",
                "--html-file", str(FIXTURES / "convyta_success.html"),
                "--rates-file", str(rates),
                "--append-rate",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = json.loads(rates.read_text())
            self.assertEqual(rows[-1], {"monthKey": "2026-07", "i1": 0.037, "i2": 0.05})


if __name__ == "__main__":
    unittest.main()
