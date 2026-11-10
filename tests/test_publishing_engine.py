import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

from publishing.engine import (PublishBlocked, validate_metadata, validate_schedule,
                               validate_authorization, reserve_upload, update_ledger)


class PublishingEngineTests(unittest.TestCase):
    def test_metadata_valid(self):
        data = validate_metadata({"title": "Valid title", "description": "desc", "tags": ["one", "two"]})
        self.assertEqual(data["title"], "Valid title")

    def test_metadata_title_limit(self):
        with self.assertRaises(PublishBlocked):
            validate_metadata({"title": "x" * 101, "description": "", "tags": []})

    def test_schedule_requires_timezone(self):
        with self.assertRaises(PublishBlocked):
            validate_schedule("2027-01-01T10:00:00")

    def test_schedule_must_be_future(self):
        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        self.assertTrue(validate_schedule(future).endswith("Z"))

    def test_authorization_blocks_false_flags(self):
        with self.assertRaises(PublishBlocked):
            validate_authorization({"safety": {"production_approved": False}},
                                   {"publishing": {"youtube": True, "require_human_approval": False}})

    def test_authorization_requires_explicit_human_approval_when_configured(self):
        manifest = {"safety": {"production_approved": True, "render_authorized": True, "upload_authorized": True}}
        with self.assertRaises(PublishBlocked):
            validate_authorization(manifest, {"publishing": {"youtube": True, "require_human_approval": True}})

    def test_duplicate_and_uncertain_uploads_block(self):
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "ledger.sqlite3"
            reserve_upload("abc", Path("sample.mp4"), db)
            with self.assertRaises(PublishBlocked):
                reserve_upload("abc", Path("sample.mp4"), db)
            update_ledger("abc", "UNCERTAIN", note="timeout", db_path=db)
            with self.assertRaises(PublishBlocked):
                reserve_upload("abc", Path("sample.mp4"), db)


if __name__ == "__main__":
    unittest.main()
