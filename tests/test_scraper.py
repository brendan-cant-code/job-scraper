import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Unit tests exercise local filtering and CSV behavior; they do not need the
# optional HTTP client installed by the GitHub Actions runtime.
sys.modules.setdefault("requests", unittest.mock.Mock())

import scraper


class JobScoringTests(unittest.TestCase):
    def test_relevant_internship_meets_threshold(self):
        self.assertEqual(scraper.score_job("Electrical Engineering Intern"), 30)
        self.assertTrue(scraper.matches_filters("Electrical Engineering Intern"))

    def test_generic_internship_does_not_meet_threshold(self):
        self.assertEqual(scraper.score_job("Business Operations Intern"), 10)
        self.assertFalse(scraper.matches_filters("Business Operations Intern"))

    def test_description_terms_can_make_an_engineering_intern_relevant(self):
        evaluation = scraper.evaluate_job(
            "Engineering Intern",
            "Support substation protection and relay-control projects.",
        )
        self.assertEqual(evaluation["title_score"], 10)
        self.assertEqual(evaluation["description_score"], 30)
        self.assertEqual(evaluation["match_score"], 40)
        self.assertIn("description: substation (+12)", evaluation["match_reasons"])

    def test_description_cannot_bypass_title_role_requirement(self):
        self.assertIsNone(
            scraper.evaluate_job(
                "Electrical Engineer",
                "Work on power systems, substations, and protection relays.",
            )
        )

    def test_html_description_is_normalized_before_matching(self):
        self.assertEqual(
            scraper.html_to_text("<p>Power&nbsp;systems<br>and relays</p>"),
            "Power systems and relays",
        )

    def test_specific_phrase_does_not_double_count_its_shorter_keyword(self):
        score, reasons = scraper.score_keyword_matches(
            "Protection and control intern",
            {"protection": 10, "protection and control": 12},
            "description",
        )
        self.assertEqual(score, 12)
        self.assertEqual(reasons, ["description: protection and control (+12)"])

    def test_excluded_title_is_rejected_regardless_of_score(self):
        self.assertIsNone(scraper.score_job("Senior Embedded Systems Intern"))

    def test_posting_key_includes_company_and_source(self):
        posting = {"source": "greenhouse", "company": "Example", "job_id": "42"}
        self.assertEqual(scraper.posting_key(posting), "greenhouse:Example:42")


class CsvMigrationTests(unittest.TestCase):
    def test_existing_log_is_migrated_to_include_score(self):
        with tempfile.TemporaryDirectory() as directory:
            data_file = Path(directory) / "postings.csv"
            data_file.write_text(
                "job_id,company,source,title,location,url,date_found\n"
                "42,Example,greenhouse,Electrical Intern,Remote,https://example.com,2026-08-05\n",
                encoding="utf-8",
            )

            with patch.object(scraper, "DATA_FILE", data_file):
                scraper.ensure_posting_schema()

            with data_file.open(newline="", encoding="utf-8") as file:
                rows = list(csv.DictReader(file))
            self.assertEqual(rows[0]["match_score"], "")


class CompanyConfigurationTests(unittest.TestCase):
    def test_load_companies_defaults_enabled_to_true(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "companies.json"
            config_file.write_text(
                json.dumps([{"name": "Example", "platform": "lever", "slug": "example"}]),
                encoding="utf-8",
            )
            self.assertEqual(
                scraper.load_companies(config_file),
                [{"name": "Example", "platform": "lever", "slug": "example", "enabled": True}],
            )

    def test_load_companies_rejects_missing_workday_field(self):
        with tempfile.TemporaryDirectory() as directory:
            config_file = Path(directory) / "companies.json"
            config_file.write_text(
                json.dumps([{"name": "Example", "platform": "workday", "tenant": "example", "site": "careers"}]),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "wd_server"):
                scraper.load_companies(config_file)


class RequestRetryTests(unittest.TestCase):
    def test_retries_transient_server_error_then_returns_response(self):
        first_response = unittest.mock.Mock(status_code=503, headers={})
        second_response = unittest.mock.Mock(status_code=200, headers={})
        with patch.object(scraper.requests, "request", side_effect=[first_response, second_response]) as request:
            with patch.object(scraper.time, "sleep") as sleep:
                response = scraper.request_with_retries("get", "https://example.com", max_attempts=2, backoff_seconds=0.5)

        self.assertIs(response, second_response)
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once_with(0.5)

    def test_does_not_retry_non_transient_client_error(self):
        response = unittest.mock.Mock(status_code=404, headers={})
        with patch.object(scraper.requests, "request", return_value=response) as request:
            with patch.object(scraper.time, "sleep") as sleep:
                result = scraper.request_with_retries("get", "https://example.com")

        self.assertIs(result, response)
        request.assert_called_once()
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
