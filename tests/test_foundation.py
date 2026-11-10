import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.foundation_v1 import (
    ROOT, validate_config, create_backup, verify_backup,
    validate_restore_manifest, is_sensitive,
)


class FoundationTests(unittest.TestCase):
    def test_channel_config_validates(self):
        result = validate_config()
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["channel_name"])

    def test_backup_is_created_and_checksum_verified(self):
        archive = create_backup()
        try:
            result = verify_backup(archive)
            self.assertEqual(result["status"], "PASS")
            self.assertGreater(result["files_verified"], 0)
        finally:
            archive.unlink(missing_ok=True)

    def test_backup_rejects_missing_file(self):
        with self.assertRaises(ValueError):
            verify_backup(ROOT / "backups" / "does-not-exist.zip")

    def test_sensitive_files_are_excluded(self):
        for name in (
            "token.json", "credentials.json", "client_secret_test.json",
            ".env", ".env.local", "private.pem", "private.key",
        ):
            self.assertTrue(is_sensitive(Path("config") / name), name)

    def test_restore_rejects_traversal_before_writing(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "malicious.zip"
            manifest = {
                "files": {
                    "app/harmless.py": "placeholder",
                    "../outside.txt": "placeholder",
                }
            }
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("app/harmless.py", "print('safe')")
                zf.writestr("../outside.txt", "malicious")
                zf.writestr("FOUNDATION_MANIFEST.json", json.dumps(manifest))

            with zipfile.ZipFile(archive, "r") as zf:
                with self.assertRaises(ValueError):
                    validate_restore_manifest(zf, manifest)

    def test_restore_rejects_sensitive_target(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "sensitive.zip"
            manifest = {"files": {"config/token.json": "placeholder"}}
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("config/token.json", "secret")
                zf.writestr("FOUNDATION_MANIFEST.json", json.dumps(manifest))

            with zipfile.ZipFile(archive, "r") as zf:
                with self.assertRaises(ValueError):
                    validate_restore_manifest(zf, manifest)


if __name__ == "__main__":
    unittest.main()
