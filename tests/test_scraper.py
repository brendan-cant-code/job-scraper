import csv
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


if __name__ == "__main__":
    unittest.main()
