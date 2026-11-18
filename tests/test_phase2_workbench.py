import csv
import tempfile
import unittest
from pathlib import Path

from app.phase2_workbench_v1 import (
    import_discovered,
    review_source,
)


class Phase2WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.video_id = "VIDEO123"
        self.workspace = (
            self.root / "data/research/youtube_universe_v33/"
            "research_workspace_v33" / self.video_id
        )
        self.workspace.mkdir(parents=True)

        self.source_fields = [
            "source_id", "title", "author", "organization",
            "published_date", "source_type", "url_or_doi",
            "accessed_date", "source_review_status", "notes"
        ]
        self.discovered_fields = self.source_fields + [
            "provider", "provider_id", "abstract",
            "discovery_query", "discovered_at"
        ]

        self.write_csv(
            self.workspace / "sources.csv",
            self.source_fields,
            [{
                "source_id": "S01",
                "title": "Existing reviewed source",
                "url_or_doi": "https://doi.org/10.1000/existing",
                "source_review_status": "REVIEWED",
                "notes": "Original record",
            }],
        )

        self.write_csv(
            self.workspace / "discovered_sources.csv",
            self.discovered_fields,
            [{
                "source_id": "DISC-123",
                "title": "New discovered paper",
                "url_or_doi": "https://doi.org/10.1000/new",
                "source_review_status": "DISCOVERED",
                "notes": "Not reviewed",
                "provider": "OpenAlex",
                "provider_id": "https://openalex.org/W123",
                "abstract": "An abstract retained for later source review.",
                "discovery_query": "sleep and repetitive thinking",
                "discovered_at": "2026-11-18T00:00:00+00:00",
            }],
        )

    def tearDown(self):
        self.temp.cleanup()

    def write_csv(self, path, fields, rows):
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def read_rows(self, path):
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))

    def test_import_keeps_discovered_status(self):
        result = import_discovered(self.root, self.video_id)
        rows = self.read_rows(self.workspace / "sources.csv")
        imported = [x for x in rows if x["source_id"] == "DISC-123"]

        self.assertEqual(result["imported"], 1)
        self.assertEqual(len(imported), 1)
        self.assertEqual(imported[0]["source_review_status"], "DISCOVERED")
        self.assertEqual(imported[0]["provider"], "OpenAlex")
        self.assertEqual(imported[0]["provider_id"], "https://openalex.org/W123")
        self.assertIn("abstract retained", imported[0]["abstract"])
        self.assertEqual(
            imported[0]["discovery_query"],
            "sleep and repetitive thinking",
        )
        self.assertTrue(imported[0]["discovered_at"])

    def test_import_does_not_overwrite_existing_reviewed_source(self):
        import_discovered(self.root, self.video_id)
        rows = self.read_rows(self.workspace / "sources.csv")
        original = [x for x in rows if x["source_id"] == "S01"][0]

        self.assertEqual(original["source_review_status"], "REVIEWED")
        self.assertEqual(original["notes"], "Original record")

    def test_duplicate_discovered_ids_are_rejected(self):
        path = self.workspace / "discovered_sources.csv"
        rows = self.read_rows(path)
        rows.append(dict(rows[0]))
        self.write_csv(path, self.discovered_fields, rows)

        with self.assertRaises(ValueError):
            import_discovered(self.root, self.video_id)

    def test_review_requires_explicit_confirmation(self):
        import_discovered(self.root, self.video_id)

        with self.assertRaises(ValueError):
            review_source(
                self.root, self.video_id, "DISC-123",
                "REVIEWED", "Checked source and abstract", False
            )

    def test_review_requires_notes(self):
        import_discovered(self.root, self.video_id)

        with self.assertRaises(ValueError):
            review_source(
                self.root, self.video_id, "DISC-123",
                "REVIEWED", "short", True
            )

    def test_confirmed_review_is_backed_up_and_recorded(self):
        import_discovered(self.root, self.video_id)

        result = review_source(
            self.root, self.video_id, "DISC-123",
            "REVIEWED", "Title and abstract independently checked.", True
        )

        rows = self.read_rows(self.workspace / "sources.csv")
        reviewed = [x for x in rows if x["source_id"] == "DISC-123"][0]

        self.assertEqual(result["new_status"], "REVIEWED")
        self.assertEqual(reviewed["source_review_status"], "REVIEWED")
        self.assertIn("independently checked", reviewed["notes"])

    def test_invalid_video_id_is_rejected(self):
        with self.assertRaises(ValueError):
            import_discovered(self.root, "../outside")


if __name__ == "__main__":
    unittest.main()
