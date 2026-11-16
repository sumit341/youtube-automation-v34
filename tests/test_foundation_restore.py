import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import foundation_v1 as foundation


class FoundationRestoreTests(unittest.TestCase):
    def test_backup_restore_and_recovery_point(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            backup_dir = root / "backups" / "foundation_snapshots"

            (root / "app").mkdir(parents=True)
            (root / "config").mkdir(parents=True)

            source = root / "app" / "restore_probe.py"
            config = root / "config" / "channel.yaml"

            original_source = b"original source\n"
            original_config = b"channel:\n  name: Original\n"

            source.write_bytes(original_source)
            config.write_bytes(original_config)

            with (
                patch.object(foundation, "ROOT", root),
                patch.object(foundation, "BACKUP_DIR", backup_dir),
            ):
                archive = foundation.create_backup()
                self.assertEqual(foundation.verify_backup(archive)["status"], "PASS")

                source.write_bytes(b"modified source\n")
                config.write_bytes(b"channel:\n  name: Modified\n")

                result = foundation.restore_backup(archive)

                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["files_restored"], 2)
                self.assertEqual(source.read_bytes(), original_source)
                self.assertEqual(config.read_bytes(), original_config)

                recovery = root / result["pre_restore_backup"]
                self.assertTrue(recovery.is_file())
                self.assertEqual(
                    foundation.verify_backup(recovery)["status"], "PASS"
                )


if __name__ == "__main__":
    unittest.main()
