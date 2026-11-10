from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CLIENT = ROOT / "client_secret.json"
TOKEN_PATH = ROOT / "credentials" / "youtube_token.json"
LEDGER_PATH = ROOT / "data" / "publishing" / "upload_ledger.sqlite3"
REPORT_DIR = ROOT / "reports" / "publishing"
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class PublishBlocked(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PublishBlocked(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PublishBlocked(f"Expected JSON object: {path}")
    return data


def load_channel_config(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise PublishBlocked("PyYAML missing. Install requirements.txt") from exc
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise PublishBlocked(f"Cannot read channel config: {exc}") from exc
    if not isinstance(data, dict):
        raise PublishBlocked("channel.yaml must contain a YAML object")
    return data


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def probe_video(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise PublishBlocked(f"Video file missing or empty: {path}")
    try:
        raw = subprocess.check_output([
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,width,height", "-of", "json", str(path)
        ], stderr=subprocess.STDOUT, text=True, timeout=30)
        info = json.loads(raw)
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise PublishBlocked(f"ffprobe validation failed: {exc}") from exc
    streams = info.get("streams", [])
    types = {s.get("codec_type") for s in streams}
    duration = float(info.get("format", {}).get("duration", 0) or 0)
    if "video" not in types or "audio" not in types or duration <= 0:
        raise PublishBlocked("Video must contain valid video + audio streams and positive duration")
    return {"duration_seconds": duration, "streams": sorted(types), "bytes": path.stat().st_size}


def validate_schedule(value: str | None) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublishBlocked("publish_at must be ISO-8601 with timezone, e.g. 2026-12-01T18:30:00+05:30") from exc
    if dt.tzinfo is None:
        raise PublishBlocked("publish_at must include timezone offset")
    if dt.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise PublishBlocked("publish_at must be in the future")
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    title = str(meta.get("title", "")).strip()
    description = str(meta.get("description", "")).strip()
    tags = meta.get("tags", [])
    if not title or len(title) > 100:
        raise PublishBlocked("Metadata title is required and must be <=100 characters")
    if len(description) > 5000:
        raise PublishBlocked("Description exceeds 5000 characters")
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise PublishBlocked("tags must be a list of strings")
    if sum(len(t) for t in tags) + max(0, len(tags) - 1) > 500:
        raise PublishBlocked("Combined tag text exceeds 500 characters")
    category_id = str(meta.get("category_id", "27"))
    language = str(meta.get("default_language", "hi"))
    return {"title": title, "description": description, "tags": tags,
            "categoryId": category_id, "defaultLanguage": language,
            "defaultAudioLanguage": str(meta.get("default_audio_language", "hi")),
            "madeForKids": bool(meta.get("made_for_kids", False))}


def validate_authorization(manifest: dict[str, Any], config: dict[str, Any], platform: str = "youtube") -> None:
    publishing = config.get("publishing", {})
    safety = manifest.get("safety", {})
    if platform != "youtube" or not publishing.get("youtube", False):
        raise PublishBlocked("YouTube publishing is disabled in config/channel.yaml")
    required = ("production_approved", "render_authorized", "upload_authorized")
    missing = [k for k in required if safety.get(k) is not True]
    if missing:
        raise PublishBlocked("Manifest safety gates are not passed: " + ", ".join(missing))
    if publishing.get("require_human_approval", True) and manifest.get("human_approved") is not True and safety.get("human_approved") is not True:
        raise PublishBlocked("Config requires human approval, but manifest has no human_approved=true")


def init_ledger(path: Path = LEDGER_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE IF NOT EXISTS uploads (
        sha256 TEXT PRIMARY KEY, status TEXT NOT NULL, video_id TEXT,
        video_path TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        note TEXT
    )""")
    db.commit()
    return db



@contextmanager
def ledger_connection(path: Path):
    """Open a ledger connection and always close it after the transaction."""
    db = init_ledger(path)
    try:
        with db:
            yield db
    finally:
        db.close()


def reserve_upload(digest: str, video: Path, db_path: Path = LEDGER_PATH) -> None:
    with ledger_connection(db_path) as db:
        row = db.execute("SELECT status, video_id FROM uploads WHERE sha256=?", (digest,)).fetchone()
        if row:
            raise PublishBlocked(f"Duplicate/uncertain upload blocked: status={row[0]}, video_id={row[1] or 'unknown'}")
        now = datetime.now(timezone.utc).isoformat()
        db.execute("INSERT INTO uploads VALUES (?, 'UPLOADING', NULL, ?, ?, ?, NULL)",
                   (digest, str(video), now, now))


def update_ledger(digest: str, status: str, video_id: str | None = None, note: str | None = None,
                  db_path: Path = LEDGER_PATH) -> None:
    with ledger_connection(db_path) as db:
        db.execute("UPDATE uploads SET status=?, video_id=?, updated_at=?, note=? WHERE sha256=?",
                   (status, video_id, datetime.now(timezone.utc).isoformat(), note, digest))


def youtube_client(client_secret: Path):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise PublishBlocked("Google API dependencies missing; install requirements.txt") from exc
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        if not client_secret.is_file():
            raise PublishBlocked(f"OAuth client JSON not found: {client_secret}")
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
        creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def write_report(payload: dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    path = REPORT_DIR / f"publish_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path, metadata_path, video_path = map(Path, (args.manifest, args.metadata, args.video))
    manifest, meta = load_json(manifest_path), validate_metadata(load_json(metadata_path))
    config = load_channel_config(Path(args.config))
    validate_authorization(manifest, config)
    video_info = probe_video(video_path)
    publish_at = validate_schedule(args.publish_at)
    privacy = args.privacy
    if privacy not in {"private", "unlisted", "public"}:
        raise PublishBlocked("privacy must be private, unlisted, or public")
    if (privacy == "public" or publish_at) and not args.confirm_public:
        raise PublishBlocked("Public or scheduled release requires --confirm-public")
    return {"manifest": str(manifest_path), "video": str(video_path), "video_info": video_info,
            "metadata": meta, "privacy": privacy, "publish_at_utc": publish_at,
            "sha256": sha256_file(video_path), "authorized": True}


def publish(args: argparse.Namespace) -> int:
    digest = None
    reserved = False
    report: dict[str, Any] = {"status": "STARTED", "started_at": datetime.now().astimezone().isoformat()}
    try:
        result = preflight(args)
        report.update(result)
        if args.dry_run:
            report["status"] = "PREFLIGHT_PASS_DRY_RUN"
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        digest = result["sha256"]
        reserve_upload(digest, Path(args.video))
        reserved = True
        yt = youtube_client(Path(args.client_secret))
        from googleapiclient.http import MediaFileUpload
        body = {"snippet": {"title": result["metadata"]["title"],
                            "description": result["metadata"]["description"],
                            "tags": result["metadata"]["tags"],
                            "categoryId": result["metadata"]["categoryId"],
                            "defaultLanguage": result["metadata"]["defaultLanguage"],
                            "defaultAudioLanguage": result["metadata"]["defaultAudioLanguage"]},
                "status": {"privacyStatus": "private" if result["publish_at_utc"] else args.privacy,
                           "selfDeclaredMadeForKids": result["metadata"]["madeForKids"]}}
        if result["publish_at_utc"]:
            body["status"]["publishAt"] = result["publish_at_utc"]
        request = yt.videos().insert(part="snippet,status", body=body,
                                     media_body=MediaFileUpload(args.video, chunksize=8*1024*1024, resumable=True))
        response = None
        while response is None:
            _, response = request.next_chunk()
        video_id = response["id"]
        update_ledger(digest, "UPLOADED", video_id)
        report.update({"status": "UPLOADED", "video_id": video_id})
        if args.thumbnail:
            thumb = Path(args.thumbnail)
            if not thumb.is_file():
                report["thumbnail_status"] = "MISSING"
            else:
                yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(thumb))).execute()
                report["thumbnail_status"] = "UPLOADED"
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    except Exception as exc:
        report.update({"status": "FAILED_OR_UNCERTAIN", "error": f"{type(exc).__name__}: {exc}"})
        if digest and reserved:
            try:
                update_ledger(digest, "UNCERTAIN", note=str(exc)[:1000])
            except Exception:
                pass
        print(json.dumps(report, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        report["finished_at"] = datetime.now().astimezone().isoformat()
        try:
            print("REPORT:", write_report(report))
        except Exception as exc:
            print("REPORT_WRITE_FAILED:", exc, file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Safety-gated YouTube publisher")
    p.add_argument("--manifest", required=True)
    p.add_argument("--metadata", required=True)
    p.add_argument("--video", required=True)
    p.add_argument("--config", default=str(ROOT / "config" / "channel.yaml"))
    p.add_argument("--client-secret", default=str(DEFAULT_CLIENT))
    p.add_argument("--thumbnail")
    p.add_argument("--privacy", choices=["private", "unlisted", "public"], default="private")
    p.add_argument("--publish-at", help="ISO-8601 datetime with timezone; future date only")
    p.add_argument("--confirm-public", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    return p


if __name__ == "__main__":
    try:
        raise SystemExit(publish(build_parser().parse_args()))
    except PublishBlocked as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        raise SystemExit(2)
