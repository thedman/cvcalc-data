import json
from datetime import date
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fetch_convyta_rates import extract_from_resources
import publish_reviewed_rates as publisher
from publish_reviewed_rates import candidate, verify
from select_reviewed_source import select_source


SOURCE = "https://convyta.com/resources"
RESOURCES = '<a href="/files/cv-guidance.pdf">CV guidance PDF</a>'
GUIDANCE = """CIA Commuted Value and Group Annuity Proxy Guidance
COMMUTED VALUE INTEREST RATES
Period First 10 Yrs. Thereafter First 10 Yrs. Thereafter First 10 Yrs. Thereafter Short Medium Long
Dec-2026 4.5% 5.4% 2.3% 2.4% 2.312% 2.441%
Pension Escalation Rates - Rounded**
Pension Escalation Rates - Unrounded**
GROUP ANNUITY PROXY INTEREST RATES
December 3, 2026
"""
MONTH = "2026-12"
BEFORE = [{"monthKey": "2026-11", "i1": .043, "i2": .053}]


class RoundedEscalationTests(unittest.TestCase):
    def discover(self, text=GUIDANCE, page=RESOURCES):
        with patch("fetch_convyta_rates.extract_pdf_text", return_value=text) as pdf:
            result = extract_from_resources(page, SOURCE, MONTH)
        pdf.assert_called_once()
        return select_source(MONTH, result.__dict__, None)

    def test_same_pdf_one_read_and_complete_publication(self):
        source = self.discover()
        rows = candidate(BEFORE, MONTH, source)
        self.assertEqual(rows[:-1], BEFORE)
        self.assertEqual(rows[-1]["i1"], .045)
        self.assertEqual(rows[-1]["i2"], .054)
        pair = rows[-1]["roundedEscalation"]
        self.assertEqual((pair["first"], pair["later"]), (.023, .024))
        self.assertEqual(pair["sourceSHA256"], source["content_sha256"])
        self.assertEqual(pair["publicationDate"], "2026-12-03")
        verify(BEFORE, json.loads(json.dumps(rows)), MONTH, source)

    def test_missing_or_ambiguous_rounded_tiers_leave_nominal_path_intact(self):
        for text in (
            GUIDANCE.replace("Pension Escalation Rates - Rounded**", ""),
            GUIDANCE.replace("2.4%", "2.456%"),
            GUIDANCE.replace("2.4% ", ""),
            GUIDANCE.replace("December 3, 2026", ""),
            GUIDANCE.replace("Dec-2026", "\fDec-2026"),
        ):
            with self.subTest(text=text):
                source = self.discover(text)
                self.assertIsNone(source["rounded_escalation"])
                self.assertEqual(candidate(BEFORE, MONTH, source)[-1],
                                 {"monthKey": MONTH, "i1": .045, "i2": .054})

    def test_html_match_and_nominal_disagreement(self):
        page = RESOURCES + """COMMUTED VALUE INTEREST RATES
        <table><tr><th>Period</th><th>First 10 Yrs.</th><th>Thereafter</th></tr>
        <tr><td>Dec-2026</td><td>4.5%</td><td>5.4%</td></tr></table>"""
        self.assertEqual(self.discover(page=page)["source_type"], "html")
        self.assertIsNotNone(self.discover(page=page)["rounded_escalation"])
        self.assertIsNone(self.discover(GUIDANCE.replace("4.5%", "4.6%"), page)["rounded_escalation"])

    def test_candidate_refuses_wrong_month_stale_nominal_and_invalid_pair(self):
        source = self.discover()
        for field, value in (("monthKey", "2026-11"), ("i1", .047), ("later", None)):
            mismatch = {**source, "rounded_escalation": {**source["rounded_escalation"], field: value}}
            with self.subTest(field=field), self.assertRaises(ValueError):
                candidate(BEFORE, MONTH, mismatch)

    def test_post_publish_compare_catches_changed_rounded_tier(self):
        source = self.discover()
        after = json.loads(json.dumps(candidate(BEFORE, MONTH, source)))
        after[-1]["roundedEscalation"]["later"] = .026
        with self.assertRaises(ValueError):
            verify(BEFORE, after, MONTH, source)

    def test_penad_fallback_is_nominal_only(self):
        source = select_source(MONTH, None, {"month_key": MONTH, "i1": .045, "i2": .054})
        self.assertEqual(candidate(BEFORE, MONTH, source)[-1],
                         {"monthKey": MONTH, "i1": .045, "i2": .054})

    def test_late_pair_adds_only_escalation_and_is_idempotent(self):
        nominal = BEFORE + [{"monthKey": MONTH, "i1": .045, "i2": .054, "metadata": "keep"}]
        source = self.discover()
        updated = publisher.escalation_candidate(nominal, MONTH, source)
        self.assertEqual(updated[:-1], BEFORE)
        self.assertEqual({k: v for k, v in updated[-1].items() if k != "roundedEscalation"}, nominal[-1])
        proof = source["rounded_escalation"]
        repeated = {**source, "rounded_escalation": {**proof, "reviewedAtUTC": "2026-12-06T00:00:00Z"}}
        self.assertIs(publisher.escalation_candidate(updated, MONTH, repeated), updated)

    def test_only_newer_source_can_correct_rounded_tier(self):
        source = self.discover()
        start = candidate(BEFORE, MONTH, source)
        proof = source["rounded_escalation"]
        changed = {**source, "rounded_escalation": {**proof, "later": .025}}
        with self.assertRaisesRegex(ValueError, "later dated"):
            publisher.escalation_candidate(start, MONTH, changed)
        changed["rounded_escalation"]["publicationDate"] = "2026-12-06"
        updated = publisher.escalation_candidate(start, MONTH, changed)
        self.assertEqual(updated[-1]["roundedEscalation"]["later"], .025)
        self.assertEqual(updated[-1]["i1"], start[-1]["i1"])
        self.assertEqual(updated[-1]["i2"], start[-1]["i2"])

    def test_same_month_retry_rejects_wrong_month_or_nominal_pair(self):
        source = self.discover()
        start = candidate(BEFORE, MONTH, source)
        with self.assertRaisesRegex(ValueError, "latest canonical month"):
            publisher.escalation_candidate(start, "2026-11", source)
        with self.assertRaisesRegex(ValueError, "published nominal pair"):
            publisher.escalation_candidate(start, MONTH, {**source, "i1": .046})

    def retry_run(self, *, mismatch=False, unavailable=False, today=date(2026, 12, 6)):
        source = self.discover()
        nominal = BEFORE + [{"monthKey": MONTH, "i1": .045, "i2": .054}]
        enriched = candidate(BEFORE, MONTH, source)
        after = nominal if mismatch else enriched
        with (TemporaryDirectory() as directory,
              patch.object(publisher, "canonical", side_effect=[("head", nominal), ("new", after)]),
              patch.object(publisher, "command", return_value="head"),
              patch.object(publisher, "reconcile"),
              patch.object(publisher, "discover") as append,
              patch.object(publisher, "discover_existing_escalation", return_value=None if unavailable else source) as discover,
              patch.object(publisher, "RATES", Path(directory) / "cia_rates.json"),
              patch.object(publisher, "push_candidate") as push,
              patch.object(publisher, "resolve") as resolve,
              patch.object(publisher, "exception") as report_exception,
              patch.object(publisher, "summary")):
            status = publisher.run(today, Path(directory))
            append.assert_not_called()
            resolve.assert_not_called()
            report_exception.assert_not_called()
            return status, push.call_count, discover.call_count

    def test_scheduled_retry_verifies_exact_enrichment_without_issue_actions(self):
        self.assertEqual(self.retry_run(), (0, 1, 1))
        self.assertEqual(self.retry_run(mismatch=True), (1, 1, 1))

    def test_no_current_enrichment_when_source_unavailable_or_month_not_due(self):
        self.assertEqual(self.retry_run(unavailable=True), (0, 0, 1))
        self.assertEqual(self.retry_run(today=date(2027, 1, 4)), (0, 0, 0))
