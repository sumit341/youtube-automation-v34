from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import yaml

ROOT = Path(__file__).resolve().parent.parent
BACKUP_DIR = ROOT / "backups" / "foundation_snapshots"

ALLOWED_ROOTS = {"app", "production", "tests"}
ALLOWED_FILES = {
    ".gitignore", "requirements.txt", "requirements-lock.txt",
    "run_pipeline.bat", "setup_project.bat",
}
ALLOWED_SUFFIXES = {".py", ".bat", ".ps1", ".yaml", ".json"}
MANIFEST_NAME = "FOUNDATION_MANIFEST.json"

SENSITIVE_NAMES = {
    "token.json", "credentials.json", "client_secret.json",
    "service_account.json", "oauth_token.json",
}

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def is_sensitive(path: Path) -> bool:
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}

    if any(part in {"secrets", "credentials", ".venv", ".git", "__pycache__"} for part in parts):
        return True
    if name in SENSITIVE_NAMES:
        return True
    if name.startswith("client_secret"):
        return True
    if name.endswith((".token", ".env", ".pem", ".key", ".p12", ".pfx")):
        return True
    if name.startswith(".env"):
        return True
    return False

def validate_config() -> dict:
    path = ROOT / "config" / "channel.yaml"
    if not path.is_file():
        raise ValueError("Missing config/channel.yaml")

    try:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc

    if not isinstance(config, dict):
        raise ValueError("Configuration root must be a YAML mapping")

    channel = config.get("channel")
    content = config.get("content")
    publishing = config.get("publishing")
    budget = config.get("budget")

    if not isinstance(channel, dict) or not channel.get("name") or not channel.get("youtube_url"):
        raise ValueError("channel.name and channel.youtube_url are required")
    if not isinstance(content, dict):
        raise ValueError("content section is required")
    if not isinstance(content.get("niche"), list) or not content["niche"]:
        raise ValueError("content.niche must be a non-empty list")
    if not isinstance(content.get("formats"), list) or not content["formats"]:
        raise ValueError("content.formats must be a non-empty list")
    if not isinstance(publishing, dict):
        raise ValueError("publishing section is required")

    for key in ("youtube", "instagram", "facebook", "require_human_approval"):
        if not isinstance(publishing.get(key), bool):
            raise ValueError(f"publishing.{key} must be true or false")

    if publishing.get("default_privacy") not in {"private", "unlisted", "public"}:
        raise ValueError("publishing.default_privacy must be private, unlisted or public")

    if not isinstance(budget, dict):
        raise ValueError("budget section is required")
    amount = budget.get("monthly_target_inr")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount < 0:
        raise ValueError("budget.monthly_target_inr must be a non-negative number")

    return {
        "status": "PASS",
        "config_file": "config/channel.yaml",
        "channel_name": channel["name"],
        "publishing_enabled": {
            "youtube": publishing["youtube"],
            "instagram": publishing["instagram"],
            "facebook": publishing["facebook"],
        },
        "default_privacy": publishing["default_privacy"],
    }

def included_files() -> list[Path]:
    files = []

    for folder in ("app", "production", "tests"):
        base = ROOT / folder
        if base.exists():
            files.extend(
                p for p in base.rglob("*")
                if p.is_file() and p.suffix.lower() in ALLOWED_SUFFIXES
            )

    for name in ALLOWED_FILES:
        path = ROOT / name
        if path.is_file():
            files.append(path)

    channel = ROOT / "config" / "channel.yaml"
    if channel.is_file():
        files.append(channel)

    safe = []
    for path in set(files):
        rel = path.relative_to(ROOT)
        if not is_sensitive(rel):
            safe.append(path)

    return sorted(safe)

def create_backup() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    archive = BACKUP_DIR / f"foundation_{stamp}.zip"
    files = included_files()
    manifest = {}

    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            rel = path.relative_to(ROOT).as_posix()
            content = path.read_bytes()
            zf.writestr(rel, content)
            manifest[rel] = sha256(content)

        zf.writestr(
            MANIFEST_NAME,
            json.dumps({
                "created_at": datetime.now(timezone.utc).isoformat(),
                "files": manifest,
            }, indent=2),
        )

    return archive

def read_manifest(zf: zipfile.ZipFile) -> dict:
    infos = zf.infolist()
    names = [info.filename for info in infos]

    if len(names) != len(set(names)):
        raise ValueError("Archive contains duplicate entry names")
    if MANIFEST_NAME not in names:
        raise ValueError("Backup manifest missing")

    try:
        manifest = json.loads(zf.read(MANIFEST_NAME))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Backup manifest is invalid") from exc

    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        raise ValueError("Backup manifest has an invalid files section")

    return manifest

def validate_restore_manifest(zf: zipfile.ZipFile, manifest: dict) -> list[str]:
    entries = []
    archive_names = set(zf.namelist())

    for rel, expected_hash in manifest["files"].items():
        if not isinstance(rel, str) or not isinstance(expected_hash, str):
            raise ValueError("Invalid manifest entry")

        if "\\" in rel or ":" in rel:
            raise ValueError(f"Unsafe archive path: {rel}")

        pure = PurePosixPath(rel)
        if pure.is_absolute() or not pure.parts or ".." in pure.parts or "." in pure.parts:
            raise ValueError(f"Unsafe archive path: {rel}")

        if pure.parts[0] == "config":
            allowed = rel == "config/channel.yaml"
        elif pure.parts[0] in ALLOWED_ROOTS:
            allowed = len(pure.parts) >= 2 and pure.suffix.lower() in ALLOWED_SUFFIXES
        else:
            allowed = rel in ALLOWED_FILES

        if not allowed:
            raise ValueError(f"Restore path not permitted: {rel}")

        if is_sensitive(Path(*pure.parts)):
            raise ValueError(f"Sensitive path blocked: {rel}")

        if rel not in archive_names:
            raise ValueError(f"Backup entry missing: {rel}")

        info = zf.getinfo(rel)
        unix_mode = (info.external_attr >> 16) & 0xFFFF
        if (unix_mode & 0o170000) == 0o120000:
            raise ValueError(f"Symbolic link entry blocked: {rel}")

        actual_hash = sha256(zf.read(rel))
        if actual_hash != expected_hash:
            raise ValueError(f"Checksum mismatch: {rel}")

        entries.append(rel)

    return entries

def verify_backup(archive: Path) -> dict:
    if not archive.is_file():
        raise ValueError(f"Backup archive not found: {archive}")

    with zipfile.ZipFile(archive, "r") as zf:
        manifest = read_manifest(zf)
        entries = validate_restore_manifest(zf, manifest)

    return {
        "status": "PASS",
        "files_verified": len(entries),
        "archive": str(archive),
    }

def restore_backup(archive: Path) -> dict:
    if not archive.is_file():
        raise ValueError(f"Backup archive not found: {archive}")

    # Validate every entry before creating a recovery point or writing files.
    with zipfile.ZipFile(archive, "r") as zf:
        manifest = read_manifest(zf)
        entries = validate_restore_manifest(zf, manifest)

    safety_archive = create_backup()
    restored = 0

    with zipfile.ZipFile(archive, "r") as zf:
        for rel in entries:
            target = ROOT.joinpath(*PurePosixPath(rel).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(rel))
            restored += 1

    return {
        "status": "PASS",
        "files_restored": restored,
        "pre_restore_backup": str(safety_archive.relative_to(ROOT)),
        "verified_source_files": len(entries),
    }

def main() -> int:
    parser = argparse.ArgumentParser(description="YouTube Automation Phase 1 foundation tools")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate-config")
    sub.add_parser("backup")

    verify = sub.add_parser("verify-backup")
    verify.add_argument("archive")

    restore = sub.add_parser("restore")
    restore.add_argument("archive")
    restore.add_argument("--confirm-restore", action="store_true")

    args = parser.parse_args()

    try:
        if args.command == "validate-config":
            result = validate_config()
        elif args.command == "backup":
            result = {"status": "PASS", "archive": str(create_backup().relative_to(ROOT))}
        elif args.command == "verify-backup":
            result = verify_backup(Path(args.archive))
        else:
            if not args.confirm_restore:
                raise ValueError("Restore blocked: pass --confirm-restore explicitly")
            result = restore_backup(Path(args.archive))

        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"FOUNDATION ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
