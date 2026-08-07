import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "select_reviewed_source.py"


def source(name: str, i1: float = 0.039, i2: float = 0.053) -> dict[str, object]:
    return {
        "month_key": "2026-08",
        "i1": i1,
        "i2": i2,
        "source_name": name,
        "source_url": f"https://example.com/{name.lower()}",
        "source_type": "html",
        "heading": "2026 Commuted Value Interest Rates",
        "extracted_text": "AUG | 3.90 | 5.30",
        "retrieved_at_utc": "2026-08-07T00:00:00+00:00",
        "content_sha256": "abc123",
    }


def run_selector(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class SelectReviewedSourceTests(unittest.TestCase):
    def write_json(self, directory: Path, name: str, data: dict[str, object]) -> Path:
        path = directory / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_convyta_unavailable_penad_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            penad = self.write_json(temp, "penad.json", source("Penad"))
            selected = temp / "selected.json"
            result = run_selector("--month", "2026-08", "--penad-json", str(penad), "--json-out", str(selected))
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(selected.read_text())
            self.assertEqual(data["source_name"], "Penad")
            self.assertEqual(data["corroboration_status"], "convyta_unavailable")

    def test_both_sources_agree_prefers_convyta(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            convyta = self.write_json(temp, "convyta.json", source("Convyta"))
            penad = self.write_json(temp, "penad.json", source("Penad"))
            selected = temp / "selected.json"
            result = run_selector(
                "--month", "2026-08",
                "--convyta-json", str(convyta),
                "--penad-json", str(penad),
                "--json-out", str(selected),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            data = json.loads(selected.read_text())
            self.assertEqual(data["source_name"], "Convyta")
            self.assertEqual(data["corroboration_status"], "penad_agrees")

    def test_sources_disagree_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            convyta = self.write_json(temp, "convyta.json", source("Convyta"))
            penad = self.write_json(temp, "penad.json", source("Penad", i1=0.04))
            selected = temp / "selected.json"
            result = run_selector(
                "--month", "2026-08",
                "--convyta-json", str(convyta),
                "--penad-json", str(penad),
                "--json-out", str(selected),
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("reviewed sources disagree", result.stderr)
            self.assertFalse(selected.exists())

    def test_neither_source_available_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            selected = Path(temp_dir) / "selected.json"
            result = run_selector("--month", "2026-08", "--json-out", str(selected))
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no reviewed source found", result.stderr)
            self.assertFalse(selected.exists())


if __name__ == "__main__":
    unittest.main()
