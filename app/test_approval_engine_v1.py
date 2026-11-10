import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("approval_engine_v1.py")
SPEC = importlib.util.spec_from_file_location("approval_engine_v1", MODULE_PATH)
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)


class ApprovalEngineHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.history = Path(self.temp.name) / "history.csv"

    def tearDown(self):
        self.temp.cleanup()

    def row(self, decision="HOLD", fingerprint="abc", decision_id="new-id"):
        return {
            "decision_id": decision_id,
            "video_id": "video-1",
            "stage": "RESEARCH",
            "decision": decision,
            "ruleset_version": engine.RULESET_VERSION,
            "decided_at": "2026-01-01T00:00:00+00:00",
            "reason_codes": "TEST",
            "reason_details": "test",
            "source_count": 1,
            "reviewed_source_count": 1,
            "claim_count": 1,
            "supported_claim_count": 1,
            "evidence_count": 1,
            "reviewed_evidence_count": 1,
            "conflict_count": 0,
            "input_fingerprint": fingerprint,
        }

    def test_first_decision_appends_and_writes_header(self):
        decision_id, action = engine.record_decision(self.row(), self.history)
        self.assertEqual(decision_id, "new-id")
        self.assertEqual(action, "APPENDED_NEW_DECISION")
        with self.history.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision_id"], "new-id")

    def test_duplicate_does_not_modify_file_and_reuses_id(self):
        engine.record_decision(self.row(decision_id="original-id"), self.history)
        before = self.history.read_bytes()
        decision_id, action = engine.record_decision(
            self.row(decision_id="should-not-be-used"), self.history
        )
        after = self.history.read_bytes()
        self.assertEqual(decision_id, "original-id")
        self.assertEqual(action, "SKIPPED_IDENTICAL_DECISION")
        self.assertEqual(before, after)

    def test_changed_fingerprint_appends_new_history(self):
        engine.record_decision(self.row(fingerprint="one"), self.history)
        engine.record_decision(self.row(fingerprint="two", decision_id="second"), self.history)
        with self.history.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 2)

    def test_header_mismatch_fails_without_rewriting(self):
        self.history.write_text("wrong,header\nx,y\n", encoding="utf-8")
        before = self.history.read_bytes()
        with self.assertRaises(ValueError):
            engine.record_decision(self.row(), self.history)
        self.assertEqual(before, self.history.read_bytes())

    def test_decision_or_video_difference_is_not_duplicate(self):
        engine.record_decision(self.row(decision="HOLD"), self.history)
        engine.record_decision(
            self.row(decision="AUTO_REJECT", decision_id="reject-id"), self.history
        )
        with self.history.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
