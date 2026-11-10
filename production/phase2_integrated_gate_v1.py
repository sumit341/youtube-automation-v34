from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

VERSION = "1.0.0"


def read_json(path: Path):
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_child(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Asset path escapes package directory: {relative}")
    return candidate


def validate_reports(script_report_path: Path, visual_report_path: Path):
    errors = []
    warnings = []

    script = read_json(script_report_path)
    visual = read_json(visual_report_path)

    topic_id = script.get("topic_id")
    draft_dir = Path(script.get("draft_directory", "")).resolve()

    if not topic_id:
        errors.append("SCRIPT_TOPIC_ID_MISSING")

    if not draft_dir.is_dir():
        errors.append("DRAFT_DIRECTORY_MISSING")

    if script.get("status") != "SCRIPT_GATES_PASS_VISUAL_RENDER_PENDING":
        errors.append("SCRIPT_PIPELINE_STATUS_NOT_PASS")

    if script.get("fact_check_status") != "PASS":
        errors.append("FACT_CHECK_NOT_PASS")

    if script.get("script_qa_status") != "PASS":
        errors.append("SCRIPT_QA_NOT_PASS")

    if script.get("production_approved") is not False:
        errors.append("PRODUCTION_FLAG_NOT_LOCKED")

    if script.get("render_authorized") is not False:
        errors.append("SCRIPT_RENDER_FLAG_NOT_LOCKED")

    if script.get("upload_authorized") is not False:
        errors.append("SCRIPT_UPLOAD_FLAG_NOT_LOCKED")

    if visual.get("status") != "PASS":
        errors.append("VISUAL_REPORT_NOT_PASS")

    if visual.get("production_approved") is not False:
        errors.append("VISUAL_PRODUCTION_FLAG_NOT_LOCKED")

    if visual.get("render_authorized") is not False:
        errors.append("VISUAL_RENDER_FLAG_NOT_LOCKED")

    if visual.get("upload_authorized") is not False:
        errors.append("VISUAL_UPLOAD_FLAG_NOT_LOCKED")

    manifest_path = Path(visual.get("manifest", "")).resolve()

    if not manifest_path.is_file():
        errors.append("VISUAL_MANIFEST_MISSING")
        return script, visual, None, errors, warnings

    manifest = read_json(manifest_path)
    package_dir = manifest_path.parent

    if manifest.get("topic_id") != topic_id:
        errors.append("TOPIC_ID_MISMATCH")

    manifest_draft = Path(manifest.get("draft_directory", "")).resolve()
    if manifest_draft != draft_dir:
        errors.append("DRAFT_DIRECTORY_MISMATCH")

    if Path(manifest.get("package_directory", "")).resolve() != package_dir:
        errors.append("PACKAGE_DIRECTORY_MISMATCH")

    if visual_report_path.parent.resolve() != package_dir:
        errors.append("VISUAL_REPORT_PACKAGE_MISMATCH")

    if manifest.get("generation_method") != "local_procedural_original":
        warnings.append("UNEXPECTED_GENERATION_METHOD")

    if manifest.get("external_media_used") is not False:
        warnings.append("EXTERNAL_MEDIA_PROVENANCE_REQUIRES_REVIEW")

    assets = manifest.get("assets")
    if not isinstance(assets, list) or not assets:
        errors.append("ASSET_LIST_EMPTY_OR_INVALID")
        return script, visual, manifest, errors, warnings

    expected_total = manifest.get("total_assets")
    if expected_total != len(assets):
        errors.append("MANIFEST_ASSET_COUNT_MISMATCH")

    if visual.get("total") != len(assets):
        errors.append("VISUAL_REPORT_ASSET_COUNT_MISMATCH")

    if visual.get("passed") != len(assets):
        errors.append("VISUAL_REPORT_PASS_COUNT_MISMATCH")

    if visual.get("rejected") != 0:
        errors.append("VISUAL_REPORT_HAS_REJECTED_ASSETS")

    seen_hashes = set()
    seen_ids = set()
    verified = 0
    asset_errors = []

    try:
        from PIL import Image
    except Exception as exc:
        errors.append(f"PILLOW_UNAVAILABLE: {exc}")
        return script, visual, manifest, errors, warnings

    for index, asset in enumerate(assets, start=1):
        asset_id = asset.get("asset_id")
        rel_path = asset.get("asset_path")
        item_errors = []

        if not asset_id or asset_id in seen_ids:
            item_errors.append("MISSING_OR_DUPLICATE_ASSET_ID")
        else:
            seen_ids.add(asset_id)

        if asset.get("status") != "AUTOMATED_TECHNICAL_PASS":
            item_errors.append("ASSET_STATUS_NOT_PASS")

        if not rel_path:
            item_errors.append("ASSET_PATH_MISSING")
            asset_errors.append({"asset": asset_id, "errors": item_errors})
            continue

        try:
            path = safe_child(package_dir, rel_path)
        except Exception as exc:
            item_errors.append(f"UNSAFE_ASSET_PATH: {exc}")
            asset_errors.append({"asset": asset_id, "errors": item_errors})
            continue

        if not path.is_file():
            item_errors.append("ASSET_FILE_MISSING")
            asset_errors.append({"asset": asset_id, "errors": item_errors})
            continue

        actual_hash = sha256_file(path)
        declared_hash = asset.get("sha256")

        if not declared_hash or actual_hash != declared_hash:
            item_errors.append("SHA256_MISMATCH")

        if actual_hash in seen_hashes:
            item_errors.append("EXACT_DUPLICATE_ASSET")
        seen_hashes.add(actual_hash)

        expected_size = (
            (1920, 1080) if asset.get("format") == "landscape"
            else (1080, 1920) if asset.get("format") == "vertical"
            else None
        )

        try:
            with Image.open(path) as im:
                im.verify()

            with Image.open(path) as im:
                actual_size = im.size
                actual_format = im.format

            if expected_size is None:
                item_errors.append("UNKNOWN_ASSET_FORMAT")
            elif actual_size != expected_size:
                item_errors.append(
                    f"WRONG_DIMENSIONS: expected={expected_size}, actual={actual_size}"
                )

            if actual_format != "JPEG":
                item_errors.append(f"WRONG_IMAGE_FORMAT: {actual_format}")

        except Exception as exc:
            item_errors.append(f"IMAGE_DECODE_FAILED: {exc}")

        provenance = asset.get("provenance") or {}
        if provenance.get("source_type") != "local_procedural_original":
            item_errors.append("PROVENANCE_SOURCE_TYPE_INVALID")

        if provenance.get("external_images_used") is not False:
            item_errors.append("EXTERNAL_IMAGE_PROVENANCE_NOT_CLEAR")

        if provenance.get("stock_media_used") is not False:
            item_errors.append("STOCK_MEDIA_PROVENANCE_NOT_CLEAR")

        if not provenance.get("renderer"):
            item_errors.append("RENDERER_PROVENANCE_MISSING")

        if not provenance.get("rights_basis"):
            item_errors.append("RIGHTS_BASIS_MISSING")

        if not asset.get("visual_direction"):
            warnings.append(f"VISUAL_DIRECTION_MISSING:{asset_id}")

        if not asset.get("narration_excerpt") and asset.get("category") != "thumbnail":
            warnings.append(f"NARRATION_EXCERPT_MISSING:{asset_id}")

        if item_errors:
            asset_errors.append({"asset": asset_id, "errors": item_errors})
        else:
            verified += 1

    if len(seen_ids) != len(assets):
        errors.append("ASSET_ID_UNIQUENESS_FAILED")

    if len(seen_hashes) != len(assets):
        errors.append("ASSET_HASH_UNIQUENESS_FAILED")

    if verified != len(assets):
        errors.append("ONE_OR_MORE_ASSETS_FAILED_REVALIDATION")

    if asset_errors:
        errors.append("ASSET_VALIDATION_ERRORS_PRESENT")

    if script.get("public_upload_authorization") is not False:
        errors.append("PUBLIC_UPLOAD_AUTHORIZATION_NOT_LOCKED")

    approval = manifest.get("approval") or {}
    for key in (
        "production_approved",
        "render_authorized",
        "upload_authorized",
        "public_upload_authorized",
    ):
        if approval.get(key) is not False:
            errors.append(f"MANIFEST_APPROVAL_NOT_LOCKED:{key}")

    return script, visual, manifest, errors, warnings, {
        "verified_assets": verified,
        "asset_errors": asset_errors,
        "package_directory": str(package_dir),
        "manifest_path": str(manifest_path),
    }


def latest_script_report(root: Path) -> Path:
    candidates = list((root / "reports" / "phase2_runs").glob("*/phase2_pipeline_report.json"))
    if not candidates:
        raise FileNotFoundError("No Phase 2 script pipeline report found.")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def latest_visual_report(draft_dir: Path) -> Path:
    candidates = list(draft_dir.glob("automated_visual_assets_v1_*/automated_visual_gate_report.json"))
    if not candidates:
        raise FileNotFoundError("No automated visual gate report found.")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def self_test():
    assert safe_child(Path.cwd(), "production") == (Path.cwd() / "production").resolve()
    try:
        safe_child(Path.cwd(), "../escape.txt")
    except ValueError:
        pass
    else:
        raise AssertionError("Path traversal test failed.")
    assert hashlib.sha256(b"test").hexdigest() == (
        "9f86d081884c7d659a2feaa0c55ad015"
        "a3bf4f1b2b0b822cd15d6c15b0f00a08"
    )
    print("[PASS] Integrated gate self-tests: 3 scenarios")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-id", required=False)
    parser.add_argument("--script-report")
    parser.add_argument("--visual-report")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    root = Path(__file__).resolve().parents[1]
    script_path = Path(args.script_report).resolve() if args.script_report else latest_script_report(root)
    if not script_path.is_file():
        raise FileNotFoundError(f"Script report not found: {script_path}")

    script = read_json(script_path)
    topic_id = args.topic_id or script.get("topic_id")
    if script.get("topic_id") != topic_id:
        raise ValueError("Requested topic ID does not match script report.")

    draft_dir = Path(script.get("draft_directory", "")).resolve()
    visual_path = Path(args.visual_report).resolve() if args.visual_report else latest_visual_report(draft_dir)

    result = validate_reports(script_path, visual_path)
    script, visual, manifest, errors, warnings = result[:5]
    details = result[5] if len(result) > 5 else {}

    passed = not errors
    now = datetime.now().astimezone()
    stamp = now.strftime("%Y%m%d_%H%M%S")
    out_dir = root / "reports" / "phase2_integrated_runs" / stamp
    out_dir.mkdir(parents=True, exist_ok=False)

    report = {
        "pipeline_version": VERSION,
        "topic_id": topic_id,
        "started_at": now.isoformat(),
        "script_report": str(script_path),
        "visual_report": str(visual_path),
        "status": "INTEGRATED_GATES_PASS_RENDER_PENDING" if passed else "HOLD",
        "script_gate_status": script.get("status"),
        "fact_check_status": script.get("fact_check_status"),
        "script_qa_status": script.get("script_qa_status"),
        "visual_gate_status": visual.get("status"),
        "asset_total": len((manifest or {}).get("assets", [])),
        "assets_revalidated": details.get("verified_assets", 0),
        "asset_errors": details.get("asset_errors", []),
        "errors": errors,
        "warnings": warnings,
        "capabilities": {
            "script_fact_traceability_gate": True,
            "script_quality_gate": True,
            "visual_file_integrity_gate": True,
            "visual_dimensions_gate": True,
            "visual_exact_duplicate_gate": True,
            "visual_provenance_metadata_gate": True,
            "semantic_truth_verification": False,
            "visual_semantic_relevance_verification": False,
            "automatic_script_regeneration": False,
            "automatic_visual_regeneration": False
        },
        "limitations": [
            "A deterministic fact-check pass does not independently prove scientific truth.",
            "Visual file checks do not establish semantic relevance to narration.",
            "Procedural graphics are not photorealistic AI-generated scenes.",
            "Provenance metadata is checked for completeness, not independently authenticated.",
            "This integrated gate does not render, publish, or grant authorization."
        ],
        "production_approved": False,
        "render_authorized": False,
        "upload_authorized": False,
        "public_upload_authorized": False,
        "finished_at": datetime.now().astimezone().isoformat()
    }

    report_path = out_dir / "phase2_integrated_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 60)
    print("PHASE 2 INTEGRATED GATE", VERSION)
    print("TOPIC:", topic_id)
    print("STATUS:", report["status"])
    print("ASSETS REVALIDATED:", report["assets_revalidated"], "/", report["asset_total"])
    print("ERRORS:", len(errors))
    print("WARNINGS:", len(warnings))
    for error in errors:
        print("[FAIL]", error)
    for warning in warnings:
        print("[WARN]", warning)
    print("PRODUCTION APPROVED:", report["production_approved"])
    print("RENDER AUTHORIZED:", report["render_authorized"])
    print("UPLOAD AUTHORIZED:", report["upload_authorized"])
    print("REPORT:", report_path)
    print("=" * 60)

    return 0 if passed else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("[HOLD]", str(exc), file=sys.stderr)
        sys.exit(2)
