from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.0.0"


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def add(items: list, code: str, detail: str = ""):
    items.append({"code": code, "detail": detail})


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Central automated production readiness gate"
    )
    parser.add_argument("--topic-id", required=True)
    parser.add_argument("--draft", required=True)
    parser.add_argument("--runs-root", default="production/runs")
    args = parser.parse_args()

    draft = Path(args.draft).resolve()
    topic_id = args.topic_id.strip()
    now = datetime.now(timezone.utc).isoformat()

    blockers = []
    regeneration = []
    rejections = []
    warnings = []
    checks = []

    def check(name: str, passed: bool, detail: str = ""):
        checks.append({
            "name": name,
            "status": "PASS" if passed else "FAIL",
            "detail": detail,
        })

    if not draft.is_dir():
        print("ERROR: Draft directory does not exist:", draft)
        return 2

    if draft.name == "":
        print("ERROR: Invalid draft directory.")
        return 2

    # Fixed report paths
    fact_path = draft / "automated_fact_check_v2_report.json"
    qa_path = draft / "script_qa_report.json"
    originality_path = draft / "premium_originality_gate_v1_2_report.json"

    long_script = draft / "long_video_script_draft.md"
    short_script = draft / "short_video_script_draft.md"

    # 1. Fact-check
    fact = None
    try:
        fact = load_json(fact_path)
        valid = (
            str(fact.get("report_version")) == "2.3"
            and fact.get("status") == "PASS"
            and fact.get("topic_id") == topic_id
            and Path(str(fact.get("draft_directory", ""))).resolve() == draft
            and int(fact.get("claims_checked", 0)) > 0
            and int(fact.get("passed_checks", 0)) == int(fact.get("total_checks", -1))
            and not fact.get("blockers")
        )
        check("fact_check_v2_3", valid, fact.get("status", "MISSING"))
        if not valid:
            add(blockers, "FACT_CHECK_NOT_VALID", str(fact.get("status")))
    except Exception as exc:
        add(blockers, "FACT_CHECK_REPORT_MISSING_OR_INVALID", str(exc))
        check("fact_check_v2_3", False, str(exc))

    # 2. Script QA
    qa = None
    try:
        qa = load_json(qa_path)
        safety = qa.get("safety") or {}
        safety_locked = (
            safety.get("production_approved") is False
            and safety.get("render_authorized") is False
            and safety.get("upload_authorized") is False
        )
        valid = (
            str(qa.get("qa_version")) == "1.2"
            and qa.get("status") == "PASS"
            and qa.get("topic_id") == topic_id
            and Path(str(qa.get("draft_directory", ""))).resolve() == draft
            and int(qa.get("passed_checks", 0)) == int(qa.get("total_checks", -1))
            and int(qa.get("total_checks", 0)) > 0
            and safety_locked
        )
        check("script_qa_v1_2", valid, qa.get("status", "MISSING"))
        if not valid:
            add(blockers, "SCRIPT_QA_NOT_VALID_OR_SAFETY_FLAGS_UNSAFE")
    except Exception as exc:
        add(blockers, "SCRIPT_QA_REPORT_MISSING_OR_INVALID", str(exc))
        check("script_qa_v1_2", False, str(exc))

    for p in (long_script, short_script):
        ok = p.is_file() and p.stat().st_size > 0
        check(f"script_file:{p.name}", ok)
        if not ok:
            add(blockers, "SCRIPT_FILE_MISSING_OR_EMPTY", str(p))

    # 3. Fact-check and QA freshness
    if fact is not None and fact_path.exists():
        script_times = [
            p.stat().st_mtime for p in (long_script, short_script) if p.exists()
        ]
        fresh = bool(script_times) and fact_path.stat().st_mtime >= max(script_times)
        check("fact_check_freshness", fresh)
        if not fresh:
            add(blockers, "FACT_CHECK_REPORT_STALE")

    if fact_path.exists() and qa_path.exists():
        fresh = qa_path.stat().st_mtime >= fact_path.stat().st_mtime
        check("script_qa_freshness", fresh)
        if not fresh:
            add(blockers, "SCRIPT_QA_REPORT_STALE")

    # 4. Find latest visual package
    packages = sorted(
        [
            p for p in draft.glob("visual_asset_package_*")
            if p.is_dir() and (p / "asset_manifest.json").is_file()
        ],
        key=lambda p: p.name,
    )

    manifest = None
    manifest_path = None
    package_dir = None
    asset_records = []

    if not packages:
        add(blockers, "VISUAL_PACKAGE_OR_MANIFEST_MISSING")
        check("visual_package_exists", False)
    else:
        package_dir = packages[-1].resolve()
        manifest_path = package_dir / "asset_manifest.json"

        try:
            manifest = load_json(manifest_path)
            identity_ok = (
                manifest.get("topic_id") == topic_id
                and Path(str(manifest.get("draft_folder", ""))).resolve() == draft
                and Path(str(manifest.get("asset_package_folder", ""))).resolve()
                    == package_dir
            )
            check("visual_manifest_identity", identity_ok)
            if not identity_ok:
                rejections.append({
                    "code": "VISUAL_MANIFEST_IDENTITY_MISMATCH",
                    "detail": str(manifest_path),
                })

            assets = manifest.get("assets")
            count_ok = (
                isinstance(assets, list)
                and len(assets) > 0
                and int(manifest.get("total_tasks", -1)) == len(assets)
            )
            check("visual_manifest_asset_count", count_ok)
            if not count_ok:
                add(blockers, "VISUAL_MANIFEST_ASSET_COUNT_INVALID")
            else:
                asset_records = assets

        except Exception as exc:
            add(blockers, "VISUAL_MANIFEST_INVALID", str(exc))

    # 5. Validate each visual file independently
    seen_hashes = {}
    asset_mtimes = []
    asset_fail_count = 0

    if manifest is not None and package_dir is not None:
        for asset in asset_records:
            aid = str(asset.get("asset_id", "UNKNOWN"))
            reasons = []

            rel = str(asset.get("asset_path", "")).strip()
            if not rel:
                reasons.append("ASSET_PATH_MISSING")
                asset_path = None
            else:
                asset_path = (package_dir / rel).resolve()
                if not inside(asset_path, package_dir):
                    reasons.append("ASSET_PATH_OUTSIDE_PACKAGE")
                    asset_path = None

            if asset_path is None or not asset_path.is_file():
                reasons.append("ASSET_FILE_MISSING")
            else:
                asset_mtimes.append(asset_path.stat().st_mtime)

                try:
                    from PIL import Image
                    with Image.open(asset_path) as im:
                        width, height = im.size
                        im.verify()

                    fmt = str(asset.get("format", "")).lower()
                    if fmt in ("portrait", "vertical"):
                        minimum = (1080, 1920)
                    else:
                        minimum = (1920, 1080)

                    if width < minimum[0] or height < minimum[1]:
                        reasons.append(
                            f"BELOW_PREMIUM_DIMENSIONS_{minimum[0]}x{minimum[1]}"
                            f"_ACTUAL_{width}x{height}"
                        )

                    quality = asset.get("quality") or {}
                    expected_hash = str(quality.get("sha256", "")).lower()
                    actual_hash = sha256(asset_path)

                    if not expected_hash:
                        reasons.append("ASSET_SHA256_MISSING")
                    elif expected_hash != actual_hash:
                        reasons.append("ASSET_SHA256_MISMATCH")

                    if actual_hash in seen_hashes:
                        reasons.append("EXACT_DUPLICATE_ASSET")
                    else:
                        seen_hashes[actual_hash] = aid

                except Exception as exc:
                    reasons.append("IMAGE_READ_OR_VALIDATION_ERROR:" + str(exc))

            provenance = asset.get("provenance") or {}
            source_type = str(provenance.get("source_type", "")).lower()
            creator = str(provenance.get("creator", "")).strip()
            prompt_used = str(
                provenance.get("generation_prompt_used", "")
            ).strip()

            if source_type not in ("original", "ai_generated", "licensed"):
                reasons.append("SOURCE_TYPE_UNKNOWN_OR_UNSUPPORTED")
            if not creator:
                reasons.append("CREATOR_NOT_DECLARED")
            if not prompt_used and source_type in ("original", "ai_generated"):
                reasons.append("GENERATION_PROMPT_PROVENANCE_MISSING")
            if provenance.get("rights_confirmation") is not True:
                reasons.append("RIGHTS_NOT_CONFIRMED")
            if provenance.get("commercial_use_confirmed") is not True:
                reasons.append("COMMERCIAL_USE_NOT_CONFIRMED")

            if source_type == "licensed":
                if not provenance.get("license_name") or not provenance.get("license_url"):
                    reasons.append("LICENSE_DETAILS_MISSING")

            if reasons:
                asset_fail_count += 1
                regeneration.append({
                    "asset_id": aid,
                    "asset_path": rel,
                    "reasons": sorted(set(reasons)),
                })

        check(
            "visual_asset_files_and_provenance",
            asset_fail_count == 0,
            f"{len(asset_records)} assets; {asset_fail_count} require regeneration"
        )

    # 6. Originality report
    originality = None
    try:
        originality = load_json(originality_path)
        identity_ok = (
            originality.get("topic_id_from_path") == topic_id
            and originality.get("topic_id_from_manifest") == topic_id
            and originality.get("topic_id_match") is True
        )
        check("originality_report_identity", identity_ok)
        if not identity_ok:
            add(blockers, "ORIGINALITY_REPORT_TOPIC_MISMATCH")

        gate_ok = (
            originality.get("gate_version") == "1.2.0"
            and originality.get("status") == "PASS_ORIGINALITY_GATE"
            and originality.get("gate_pass") is True
        )
        check(
            "premium_originality_gate_v1_2",
            gate_ok,
            originality.get("status", "MISSING")
        )
        if not gate_ok:
            add(
                regeneration,
                "PREMIUM_ORIGINALITY_GATE_FAILED",
                str(originality.get("status"))
            )

        if originality.get("rights_hold_asset_ids"):
            add(
                regeneration,
                "ORIGINALITY_RIGHTS_HOLDS",
                str(len(originality["rights_hold_asset_ids"])) + " assets"
            )

        if originality.get("script_holds"):
            add(
                blockers,
                "SCRIPT_NOVELTY_CORPUS_ORIGINALITY_HOLD",
                str(originality.get("script_holds"))
            )

    except Exception as exc:
        add(blockers, "ORIGINALITY_REPORT_MISSING_OR_INVALID", str(exc))
        check("premium_originality_gate_v1_2", False, str(exc))

    # 7. Originality report freshness against visual package and assets
    if manifest_path and originality_path.exists():
        source_times = [manifest_path.stat().st_mtime] + asset_mtimes
        fresh = bool(source_times) and originality_path.stat().st_mtime >= max(source_times)
        check("originality_report_freshness", fresh)
        if not fresh:
            add(blockers, "ORIGINALITY_REPORT_STALE")

    # 8. Check for an actual render implementation.
    # FFmpeg being installed on Windows is not proof of a project render engine.
    render_candidates = []
    production_root = Path("production")
    if production_root.is_dir():
        for p in production_root.rglob("*.py"):
            if p.name == Path(__file__).name:
                continue
            if re.search(r"render|video_engine", p.name, re.I):
                render_candidates.append(str(p))

    render_engine_present = bool(render_candidates)
    check(
        "project_render_engine_exists",
        render_engine_present,
        "; ".join(render_candidates) if render_candidates else "No render engine module found"
    )
    if not render_engine_present:
        add(blockers, "RENDER_ENGINE_NOT_IMPLEMENTED")

    # 9. Status: fail closed
    if rejections:
        status = "REJECTED"
    elif regeneration:
        status = "REGENERATE_REQUIRED"
    elif blockers:
        status = "BLOCKED"
    else:
        status = "PASS_TO_RENDER"

    report = {
        "gate_version": VERSION,
        "created_at": now,
        "topic_id": topic_id,
        "draft_directory": str(draft),
        "status": status,
        "checks_passed": sum(1 for x in checks if x["status"] == "PASS"),
        "checks_total": len(checks),
        "checks": checks,
        "blockers": blockers,
        "regeneration_queue": regeneration,
        "rejections": rejections,
        "warnings": warnings,
        "visual_asset_count": len(asset_records),
        "visual_assets_requiring_regeneration": asset_fail_count,
        "render_engine_detected": render_engine_present,
        "production_approved": False,
        "render_authorized": False,
        "upload_authorized": False,
        "public_upload_authorization": False,
        "limitations": [
            "This gate checks report consistency, file integrity, dimensions and declared provenance.",
            "It does not independently prove scientific truth, semantic originality or visual suitability.",
            "Rights declarations are not independently verified against provider terms.",
            "PASS_TO_RENDER is a readiness result only; it does not grant render or upload authorization.",
            "No source manifest, source asset, research file or approval flag is modified.",
        ],
    }

    report_path = draft / "central_production_gate_v1_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("=" * 68)
    print("CENTRAL PRODUCTION GATE", VERSION)
    print("=" * 68)
    print("TOPIC:", topic_id)
    print("STATUS:", status)
    print("CHECKS:", report["checks_passed"], "/", report["checks_total"])
    print("VISUAL ASSETS:", len(asset_records))
    print("ASSETS REQUIRING REGENERATION:", asset_fail_count)
    print("BLOCKERS:", len(blockers))
    print("REGENERATION ITEMS:", len(regeneration))
    print("REJECTIONS:", len(rejections))
    print("RENDER ENGINE:", render_engine_present)
    print("PRODUCTION APPROVED: False")
    print("RENDER AUTHORIZED: False")
    print("UPLOAD AUTHORIZED: False")
    print("REPORT:", report_path)

    if regeneration:
        print("\nREGENERATION QUEUE:")
        for item in regeneration[:20]:
            if isinstance(item, dict):
                print("-", item.get("asset_id", item.get("code")), item.get("reasons", item.get("detail", "")))
            else:
                print("-", item)

    if blockers:
        print("\nBLOCKERS:")
        for item in blockers:
            print("-", item["code"], item.get("detail", ""))

    return 0 if status == "PASS_TO_RENDER" else 1


if __name__ == "__main__":
    sys.exit(main())
