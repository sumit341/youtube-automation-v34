
#!/usr/bin/env python3
"""
Premium Originality Gate V1.2
Read-only validation. Never modifies source manifests, assets or approvals.
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image, UnidentifiedImageError

VERSION = "1.2.0"

MINIMUMS = {
    "landscape": (1920, 1080),
    "vertical": (1080, 1920),
}

SCRIPT_NAMES = {
    "long": "long_video_script_draft.md",
    "short": "short_video_script_draft.md",
}

IGNORED_WORDS = {
    "the", "and", "for", "this", "that", "with", "from",
    "hai", "hain", "aur", "ye", "woh", "ek", "ke", "ki",
    "ka", "ko", "se", "mein", "par", "video", "script",
    "draft", "scene", "visual", "section", "claim",
}


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_text(value):
    value = re.sub(r"```.*?```", " ", value, flags=re.S)
    value = re.sub(r"^\s*#{1,6}\s+.*$", " ", value, flags=re.M)
    value = re.sub(r"https?://\S+", " ", value)
    value = value.lower()
    value = re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", value)

    return " ".join(
        word for word in value.split()
        if len(word) > 2 and word not in IGNORED_WORDS
    )


def make_shingles(text, size=5):
    words = text.split()
    if len(words) < size:
        return {" ".join(words)} if words else set()

    return {
        " ".join(words[index:index + size])
        for index in range(len(words) - size + 1)
    }


def jaccard_similarity(first, second):
    if not first or not second:
        return 0.0

    union = first | second
    return len(first & second) / len(union) if union else 0.0


def average_hash(path):
    with Image.open(path) as image:
        image = image.convert("L").resize((16, 16))

        try:
            pixels = list(image.get_flattened_data())
        except AttributeError:
            pixels = list(image.getdata())

    average = sum(pixels) / len(pixels)
    value = 0

    for pixel in pixels:
        value = (value << 1) | int(pixel >= average)

    return value


def hash_similarity(first, second):
    return 1.0 - ((first ^ second).bit_count() / 256)


def topic_id_from_draft(draft):
    # runs/<topic_id>/drafts/<draft_id>
    try:
        return draft.resolve().parents[1].name
    except IndexError:
        return None


def topic_id_from_script(script_path):
    # runs/<topic_id>/drafts/<draft_id>/<script>.md
    try:
        return script_path.resolve().parents[2].name
    except IndexError:
        return None


def load_script(path):
    if not path.is_file():
        return ""

    return normalize_text(
        path.read_text(encoding="utf-8", errors="replace")
    )


def collect_other_topic_scripts(runs_root, current_draft, kind):
    filename = SCRIPT_NAMES[kind]
    current_topic = topic_id_from_draft(current_draft)
    results = []

    if not runs_root.is_dir():
        return results

    for path in runs_root.rglob(filename):
        try:
            resolved = path.resolve()

            if current_draft.resolve() in resolved.parents:
                continue

            old_topic = topic_id_from_script(resolved)

            if not old_topic or old_topic == current_topic:
                continue

            content = load_script(resolved)

            if content:
                results.append({
                    "path": resolved,
                    "topic_id": old_topic,
                    "content": content,
                })

        except (OSError, RuntimeError):
            continue

    return results


def validate_provenance(asset):
    provenance = asset.get("provenance") or {}

    failures = []
    holds = []
    source_type = str(
        provenance.get("source_type", "")
    ).strip().lower()

    if source_type == "original":
        if not provenance.get("creator"):
            holds.append("ORIGINAL_CREATOR_MISSING")

        if provenance.get("rights_confirmation") is not True:
            holds.append("ORIGINAL_RIGHTS_NOT_CONFIRMED")

        if provenance.get("commercial_use_confirmed") is not True:
            holds.append("ORIGINAL_COMMERCIAL_USE_NOT_CONFIRMED")

        if not (
            provenance.get("source_url")
            or provenance.get("source_code_reference")
            or provenance.get("generation_prompt_used")
        ):
            holds.append("ORIGINAL_SOURCE_TRACEABILITY_MISSING")

    elif source_type == "ai_generated":
        required = (
            "provider",
            "model",
            "terms_reference",
            "terms_checked_at",
            "generation_prompt_used",
        )

        missing = [
            field for field in required
            if not provenance.get(field)
        ]

        if missing:
            holds.append(
                "AI_PROVENANCE_MISSING_" + "_".join(missing)
            )

        if provenance.get("commercial_use_confirmed") is not True:
            holds.append("AI_COMMERCIAL_USE_NOT_CONFIRMED")

        if provenance.get("rights_confirmation") is not True:
            holds.append("AI_RIGHTS_NOT_CONFIRMED")

    elif source_type == "stock":
        if not provenance.get("source_url"):
            holds.append("STOCK_SOURCE_URL_MISSING")

        if not provenance.get("license_name"):
            holds.append("STOCK_LICENSE_MISSING")

        if not provenance.get("license_url"):
            holds.append("STOCK_LICENSE_REFERENCE_MISSING")

        if provenance.get("commercial_use_confirmed") is not True:
            holds.append("STOCK_COMMERCIAL_USE_NOT_CONFIRMED")

    else:
        holds.append("UNKNOWN_OR_UNDECLARED_SOURCE_TYPE")

    return failures, holds


def validate_asset_path(manifest_dir, relative_path):
    if not relative_path:
        return None, "ASSET_PATH_MISSING"

    candidate = (manifest_dir / relative_path).resolve()

    try:
        candidate.relative_to(manifest_dir.resolve())
    except ValueError:
        return None, "ASSET_PATH_ESCAPES_PACKAGE"

    if not candidate.is_file():
        return None, "ASSET_FILE_MISSING"

    return candidate, None


def main():
    parser = argparse.ArgumentParser(
        description="Read-only Premium Originality Gate V1.2"
    )

    parser.add_argument("--draft", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--runs-root",
        default="production/runs",
    )
    parser.add_argument(
        "--visual-warning-threshold",
        type=float,
        default=0.94,
    )
    parser.add_argument(
        "--script-jaccard-threshold",
        type=float,
        default=0.30,
    )
    parser.add_argument(
        "--script-sequence-threshold",
        type=float,
        default=0.65,
    )

    args = parser.parse_args()

    draft = Path(args.draft).resolve()
    manifest_path = Path(args.manifest).resolve()
    runs_root = Path(args.runs_root).resolve()

    if not draft.is_dir():
        print("ERROR: Draft directory not found:", draft)
        return 2

    if not manifest_path.is_file():
        print("ERROR: Manifest not found:", manifest_path)
        return 2

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        print("ERROR: Manifest read failed:", exc)
        return 2

    assets = manifest.get("assets")

    if not isinstance(assets, list):
        print("ERROR: Manifest assets is not a list.")
        return 2

    topic_id = topic_id_from_draft(draft)
    manifest_topic = manifest.get("topic_id")

    asset_results = []
    hard_failures = []
    rights_holds = []
    warnings = []

    exact_hash_groups = {}
    visual_hashes = []
    direction_history = []

    for asset in assets:
        if not isinstance(asset, dict):
            continue

        asset_id = str(asset.get("asset_id", "UNKNOWN"))
        relative_path = str(asset.get("asset_path", ""))

        failures = []
        holds = []
        asset_warnings = []
        details = {}

        image_path, path_error = validate_asset_path(
            manifest_path.parent,
            relative_path,
        )

        if path_error:
            failures.append(path_error)

        else:
            try:
                file_hash = sha256_file(image_path)
                details["sha256"] = file_hash

                exact_hash_groups.setdefault(
                    file_hash, []
                ).append(asset_id)

                with Image.open(image_path) as image:
                    image.verify()

                with Image.open(image_path) as image:
                    width, height = image.size
                    image_format = image.format or ""

                details["dimensions"] = [width, height]
                details["image_format"] = image_format

                fmt = str(
                    asset.get("format", "landscape")
                ).strip().lower()

                minimum = MINIMUMS.get(fmt)

                if minimum is None:
                    failures.append("UNKNOWN_ASSET_FORMAT")
                else:
                    details["premium_minimum"] = list(minimum)

                    declared_minimum = asset.get(
                        "minimum_dimensions", {}
                    )

                    details["manifest_declared_minimum"] = {
                        "width": declared_minimum.get("width"),
                        "height": declared_minimum.get("height"),
                    }

                    if width < minimum[0] or height < minimum[1]:
                        failures.append(
                            f"BELOW_PREMIUM_MINIMUM_{minimum[0]}x{minimum[1]}"
                        )

                current_visual_hash = average_hash(image_path)

                for other_id, other_hash in visual_hashes:
                    score = hash_similarity(
                        current_visual_hash, other_hash
                    )

                    if score >= args.visual_warning_threshold:
                        asset_warnings.append({
                            "type": "PERCEPTUAL_SIMILARITY",
                            "other_asset_id": other_id,
                            "score": round(score, 4),
                        })

                visual_hashes.append(
                    (asset_id, current_visual_hash)
                )

            except (
                UnidentifiedImageError,
                OSError,
                ValueError,
            ) as exc:
                failures.append("IMAGE_UNREADABLE")
                details["image_error"] = str(exc)

        provenance_failures, provenance_holds = (
            validate_provenance(asset)
        )

        failures.extend(provenance_failures)
        holds.extend(provenance_holds)

        direction = normalize_text(
            str(asset.get("visual_direction", ""))
        )
        direction_grams = make_shingles(direction, 3)

        for other_id, other_grams in direction_history:
            score = jaccard_similarity(
                direction_grams, other_grams
            )

            if direction_grams and score >= 0.75:
                asset_warnings.append({
                    "type": "REPEATED_VISUAL_DIRECTION",
                    "other_asset_id": other_id,
                    "score": round(score, 4),
                })

        direction_history.append(
            (asset_id, direction_grams)
        )

        if failures:
            hard_failures.append(asset_id)

        if holds:
            rights_holds.append(asset_id)

        warnings.extend(
            f"{asset_id}:{item['type']}"
            for item in asset_warnings
        )

        asset_results.append({
            "asset_id": asset_id,
            "asset_path": relative_path,
            "source_type": (
                (asset.get("provenance") or {}).get("source_type")
            ),
            "details": details,
            "failures": sorted(set(failures)),
            "holds": sorted(set(holds)),
            "warnings": asset_warnings,
        })

    # Mark every member of an exact duplicate group except its
    # first occurrence. The original file is not modified.
    duplicate_groups = []

    for digest, ids in exact_hash_groups.items():
        if len(ids) > 1:
            duplicate_groups.append({
                "sha256": digest,
                "asset_ids": ids,
                "duplicate_asset_ids": ids[1:],
            })

            for duplicate_id in ids[1:]:
                for result in asset_results:
                    if result["asset_id"] == duplicate_id:
                        result["failures"].append(
                            "EXACT_DUPLICATE_OF_" + ids[0]
                        )
                        if duplicate_id not in hard_failures:
                            hard_failures.append(duplicate_id)

    # Script comparison: long-to-long and short-to-short,
    # excluding all earlier drafts belonging to the same topic.
    script_results = []
    script_holds = []

    for kind, filename in SCRIPT_NAMES.items():
        current_path = draft / filename
        current_text = load_script(current_path)

        if not current_text:
            script_holds.append(
                f"CURRENT_SCRIPT_MISSING_OR_EMPTY:{kind}"
            )
            script_results.append({
                "kind": kind,
                "status": "HOLD",
                "reason": "CURRENT_SCRIPT_MISSING_OR_EMPTY",
                "comparisons": [],
            })
            continue

        previous_scripts = collect_other_topic_scripts(
            runs_root, draft, kind
        )

        comparisons = []
        current_grams = make_shingles(current_text, 5)

        for previous in previous_scripts:
            old_text = previous["content"]
            old_grams = make_shingles(old_text, 5)

            jaccard_score = jaccard_similarity(
                current_grams, old_grams
            )

            sequence_score = SequenceMatcher(
                None,
                current_text[:15000],
                old_text[:15000],
            ).ratio()

            comparisons.append({
                "other_topic_id": previous["topic_id"],
                "file": str(previous["path"]),
                "jaccard_similarity": round(jaccard_score, 4),
                "sequence_similarity": round(sequence_score, 4),
            })

            if (
                jaccard_score >= args.script_jaccard_threshold
                or sequence_score >= args.script_sequence_threshold
            ):
                script_holds.append(
                    f"POSSIBLE_CROSS_TOPIC_SCRIPT_REUSE:{kind}:"
                    f"{previous['topic_id']}"
                )

        if not previous_scripts:
            script_holds.append(
                f"SCRIPT_CORPUS_INSUFFICIENT:{kind}"
            )
            status = "HOLD_NO_CROSS_TOPIC_COMPARISON"
        elif any(
            item["jaccard_similarity"] >= args.script_jaccard_threshold
            or item["sequence_similarity"] >= args.script_sequence_threshold
            for item in comparisons
        ):
            status = "HOLD_POSSIBLE_REUSE"
        else:
            status = "COMPARISON_CLEAR"

        script_results.append({
            "kind": kind,
            "status": status,
            "current_script": str(current_path),
            "other_topic_comparison_count": len(previous_scripts),
            "comparisons": comparisons,
        })

    hard_failures = sorted(set(hard_failures))
    rights_holds = sorted(set(rights_holds))
    script_holds = sorted(set(script_holds))

    all_holds = sorted(set(rights_holds + script_holds))

    if hard_failures:
        gate_status = "FAIL_REGENERATION_REQUIRED"
    elif all_holds:
        gate_status = "HOLD_INSUFFICIENT_EVIDENCE"
    else:
        gate_status = "PASS_ORIGINALITY_GATE"

    failure_counts = Counter(
        failure
        for result in asset_results
        for failure in result["failures"]
    )

    hold_counts = Counter(
        hold
        for result in asset_results
        for hold in result["holds"]
    )

    report = {
        "gate_version": VERSION,
        "status": gate_status,
        "gate_pass": gate_status == "PASS_ORIGINALITY_GATE",
        "topic_id_from_path": topic_id,
        "topic_id_from_manifest": manifest_topic,
        "topic_id_match": topic_id == manifest_topic,
        "read_only": True,
        "source_manifest_modified": False,
        "source_assets_modified": False,
        "approval_flags_modified": False,
        "production_authorization": False,
        "render_authorization": False,
        "youtube_upload_authorization": False,
        "public_upload_authorization": False,
        "asset_count": len(asset_results),
        "failed_asset_ids": hard_failures,
        "rights_hold_asset_ids": rights_holds,
        "script_holds": script_holds,
        "failure_counts": dict(failure_counts),
        "asset_hold_counts": dict(hold_counts),
        "duplicate_groups": duplicate_groups,
        "warnings": warnings,
        "warning_count": len(warnings),
        "assets": asset_results,
        "scripts": script_results,
        "thresholds": {
            "landscape": list(MINIMUMS["landscape"]),
            "vertical": list(MINIMUMS["vertical"]),
            "visual_similarity_warning": args.visual_warning_threshold,
            "script_jaccard_hold": args.script_jaccard_threshold,
            "script_sequence_hold": args.script_sequence_threshold,
        },
        "limitations": [
            "This is a technical and evidence gate, not a complete semantic originality detector.",
            "Perceptual hash and visual direction matches are warnings only.",
            "Script similarity is a heuristic and requires a growing cross-topic corpus.",
            "No provider commercial terms are independently verified by this local gate.",
            "Rights uncertainty results in HOLD, not PASS.",
            "A gate PASS never grants production or upload authorization.",
            "No source asset, manifest or approval record is modified.",
        ],
    }

    report_path = (
        draft / "premium_originality_gate_v1_2_report.json"
    )

    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("=" * 64)
    print("PREMIUM ORIGINALITY GATE V1.2")
    print("=" * 64)
    print("STATUS:", gate_status)
    print("TOPIC:", topic_id)
    print("MANIFEST TOPIC MATCH:", topic_id == manifest_topic)
    print("ASSETS:", len(asset_results))
    print("FAILED ASSETS:", len(hard_failures))
    print("RIGHTS HOLD ASSETS:", len(rights_holds))
    print("SCRIPT HOLDS:", len(script_holds))
    print("EXACT DUPLICATE GROUPS:", len(duplicate_groups))
    print("WARNINGS:", len(warnings))

    print("\nFAILURE REASONS:")
    for reason, count in failure_counts.most_common():
        print(f"{reason}: {count}")

    print("\nRIGHTS HOLD REASONS:")
    for reason, count in hold_counts.most_common():
        print(f"{reason}: {count}")

    print("\nSCRIPT RESULTS:")
    for item in script_results:
        print(
            item["kind"],
            "|", item["status"],
            "| comparisons:", item.get(
                "other_topic_comparison_count", 0
            ),
        )

    print("\nSCRIPT HOLDS:")
    for reason in script_holds:
        print(reason)

    print("\nDUPLICATE GROUPS:")
    for group in duplicate_groups:
        print(", ".join(group["asset_ids"]))

    print("\nREPORT:", report_path)
    print("SOURCE MANIFEST MODIFIED: False")
    print("SOURCE ASSETS MODIFIED: False")
    print("APPROVAL FLAGS MODIFIED: False")
    print("PRODUCTION AUTHORIZATION: False")
    print("UPLOAD AUTHORIZATION: False")

    return 0 if gate_status == "PASS_ORIGINALITY_GATE" else 1


if __name__ == "__main__":
    sys.exit(main())
