from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "research" / "youtube_universe_v33"
WORKSPACES = BASE / "research_workspace_v33"

SOURCE_FIELDS = [
    "source_id", "title", "author", "organization", "published_date",
    "source_type", "url_or_doi", "accessed_date",
    "source_review_status", "notes"
]

DISCOVERY_METADATA_FIELDS = [
    "provider", "provider_id", "abstract",
    "discovery_query", "discovered_at"
]

DISCOVERED_REQUIRED = {
    "source_id", "title", "url_or_doi", "source_review_status"
}


def safe_video_id(value):
    value = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise ValueError("Invalid video ID.")
    return value


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def write_csv_atomic(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".phase2tmp")

    with temp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=fields, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)

    temp.replace(path)


def backup_file(path):
    if not path.exists():
        return None

    backup_dir = ROOT / "backups" / "phase2_workbench"
    backup_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = backup_dir / f"{path.stem}_{stamp}{path.suffix}"
    shutil.copy2(path, destination)
    return destination


def normalize_locator(value):
    value = str(value or "").strip().lower()
    value = value.replace("https://doi.org/", "")
    value = value.replace("http://doi.org/", "")
    value = value.replace("doi:", "")
    return value.rstrip("/")


def import_discovered(root, video_id):
    video_id = safe_video_id(video_id)
    workspace = Path(root) / "data/research/youtube_universe_v33/research_workspace_v33" / video_id

    discovered_path = workspace / "discovered_sources.csv"
    sources_path = workspace / "sources.csv"

    discovered, discovered_fields = read_csv(discovered_path)
    missing = DISCOVERED_REQUIRED - set(discovered_fields)
    if missing:
        raise ValueError(f"Discovered CSV missing columns: {sorted(missing)}")

    existing, fields = read_csv(sources_path)

    for field in SOURCE_FIELDS + DISCOVERY_METADATA_FIELDS:
        if field not in fields:
            fields.append(field)

    discovered_ids = [str(x.get("source_id", "")).strip() for x in discovered]
    if any(not x for x in discovered_ids):
        raise ValueError("Discovered file contains blank source IDs.")

    if len(discovered_ids) != len(set(discovered_ids)):
        raise ValueError("Discovered file contains duplicate source IDs.")

    existing_ids = {
        str(x.get("source_id", "")).strip()
        for x in existing
    }
    existing_locators = {
        normalize_locator(x.get("url_or_doi"))
        for x in existing
        if normalize_locator(x.get("url_or_doi"))
    }

    added = 0
    skipped = 0

    for row in discovered:
        source_id = str(row.get("source_id", "")).strip()
        locator = normalize_locator(row.get("url_or_doi"))

        if not str(row.get("title", "")).strip() or not locator:
            raise ValueError(f"Incomplete discovered source: {source_id}")

        if source_id in existing_ids or locator in existing_locators:
            skipped += 1
            continue

        record = {field: "" for field in fields}
        # Preserve all matching discovery/provenance columns.
        for field in fields:
            if field in row:
                record[field] = str(row.get(field, "") or "").strip()

        # Discovery is never equivalent to source review.
        record["source_review_status"] = "DISCOVERED"
        record["notes"] = (
            "Imported from source discovery. Not independently reviewed. "
            + str(row.get("notes", "") or "").strip()
        ).strip()

        existing.append(record)
        existing_ids.add(source_id)
        existing_locators.add(locator)
        added += 1

    if added:
        backup_file(sources_path)
        write_csv_atomic(sources_path, existing, fields)

    return {
        "video_id": video_id,
        "discovered_rows": len(discovered),
        "imported": added,
        "skipped_duplicates": skipped,
        "source_file": str(sources_path),
        "review_status": "DISCOVERED",
        "research_approval": "UNCHANGED",
        "production_approval": False,
        "upload_authorized": False,
    }


def review_source(root, video_id, source_id, decision, notes, confirm):
    video_id = safe_video_id(video_id)
    source_id = str(source_id or "").strip()
    decision = str(decision or "").strip().upper()
    notes = str(notes or "").strip()

    if not source_id:
        raise ValueError("Source ID is required.")

    if decision not in ("REVIEWED", "REJECTED", "PENDING"):
        raise ValueError("Decision must be REVIEWED, REJECTED or PENDING.")

    if decision in ("REVIEWED", "REJECTED") and not confirm:
        raise ValueError("Explicit --confirm is required for this decision.")

    if decision in ("REVIEWED", "REJECTED") and len(notes) < 10:
        raise ValueError("Provide meaningful reviewer notes (at least 10 characters).")

    workspace = Path(root) / "data/research/youtube_universe_v33/research_workspace_v33" / video_id
    path = workspace / "sources.csv"
    rows, fields = read_csv(path)

    matches = [
        row for row in rows
        if str(row.get("source_id", "")).strip() == source_id
    ]

    if len(matches) != 1:
        raise ValueError(f"Expected one source row; found {len(matches)}.")

    row = matches[0]
    old_status = str(row.get("source_review_status", "")).strip().upper()

    if old_status == "REVIEWED" and decision != "REVIEWED":
        raise ValueError("Refusing to downgrade an already reviewed source.")

    if "source_review_status" not in fields:
        raise ValueError("Source CSV has no review status column.")

    backup_file(path)
    row["source_review_status"] = decision

    old_notes = str(row.get("notes", "") or "").strip()
    if notes:
        row["notes"] = (old_notes + " | REVIEWER: " + notes).strip(" |")

    write_csv_atomic(path, rows, fields)

    return {
        "video_id": video_id,
        "source_id": source_id,
        "previous_status": old_status,
        "new_status": decision,
        "reviewer_notes_saved": bool(notes),
        "research_approval": "UNCHANGED",
        "production_approval": False,
        "upload_authorized": False,
    }


def load_gate_module(root):
    path = Path(root) / "production" / "research_to_script_v2.py"
    if not path.exists():
        raise FileNotFoundError(f"Research gate v2 missing: {path}")

    spec = importlib.util.spec_from_file_location("research_gate_v2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def batch_audit(root):
    root = Path(root)
    workspace_root = root / "data/research/youtube_universe_v33/research_workspace_v33"
    gate = load_gate_module(root)

    results = []

    for workspace in sorted(workspace_root.iterdir()):
        if not workspace.is_dir():
            continue

        required = ("sources.csv", "claims.csv", "evidence.csv")
        if not all((workspace / name).exists() for name in required):
            continue

        video_id = workspace.name

        try:
            report = gate.audit(video_id)
            results.append({
                "video_id": video_id,
                "status": report["overall_status"],
                "research_decision": report["research_decision"],
                "total_sources": report["total_sources"],
                "reviewed_sources": report["reviewed_sources"],
                "total_claims": report["total_claims"],
                "eligible_claims": report["eligible_claims"],
                "held_claims": report["held_claims"],
                "errors": report["errors"],
            })
        except Exception as exc:
            results.append({
                "video_id": video_id,
                "status": "ERROR",
                "error": str(exc),
            })

    report = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topics_scanned": len(results),
        "ready_for_controlled_script_draft": sum(
            x.get("status") == "READY_FOR_CONTROLLED_SCRIPT_DRAFT"
            for x in results
        ),
        "held_or_error": sum(
            x.get("status") != "READY_FOR_CONTROLLED_SCRIPT_DRAFT"
            for x in results
        ),
        "production_approved": False,
        "youtube_upload_authorized": False,
        "results": results,
    }

    output_dir = root / "reports" / "phase2"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / "batch_research_gate_latest.json"
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return report, output


def main():
    parser = argparse.ArgumentParser(
        description="Phase 2 research workbench integration"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    imp = sub.add_parser("import-discovered")
    imp.add_argument("--video-id", required=True)

    review = sub.add_parser("review-source")
    review.add_argument("--video-id", required=True)
    review.add_argument("--source-id", required=True)
    review.add_argument("--decision", required=True)
    review.add_argument("--notes", required=True)
    review.add_argument("--confirm", action="store_true")

    batch = sub.add_parser("batch-audit")

    args = parser.parse_args()

    if args.command == "import-discovered":
        result = import_discovered(ROOT, args.video_id)
        print(json.dumps(result, indent=2))
    elif args.command == "review-source":
        result = review_source(
            ROOT, args.video_id, args.source_id,
            args.decision, args.notes, args.confirm
        )
        print(json.dumps(result, indent=2))
    elif args.command == "batch-audit":
        result, output = batch_audit(ROOT)
        print(json.dumps(result, indent=2))
        print("BATCH REPORT:", output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
