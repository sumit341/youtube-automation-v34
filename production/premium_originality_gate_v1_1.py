
#!/usr/bin/env python3
"""Premium Originality Gate V1.1.

Read-only validation of source assets and scripts.
Writes a separate report. Never modifies manifests, assets or approvals.
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

VERSION = "1.1.0"
LANDSCAPE_MIN = (1920, 1080)
VERTICAL_MIN = (1080, 1920)

SCRIPT_NAMES = {
    "long": "long_video_script_draft.md",
    "short": "short_video_script_draft.md",
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"^\s*#{1,6}\s+.*$", " ", text, flags=re.M)
    text = re.sub(r"https?://\S+", " ", text)
    text = text.lower()
    text = re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", text)

    ignored = {
        "the", "and", "for", "this", "that", "with", "from",
        "hai", "hain", "aur", "ye", "woh", "ek", "ke", "ki",
        "ka", "ko", "se", "mein", "par", "video", "script",
        "draft", "scene", "visual", "section", "claim",
    }

    return " ".join(
        word for word in text.split()
        if len(word) > 2 and word not in ignored
    )


def shingles(text, size=5):
    words = text.split()
    return {
        " ".join(words[i:i + size])
        for i in range(max(0, len(words) - size + 1))
    }


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def average_hash(path):
    with Image.open(path) as image:
        image = image.convert("L").resize((16, 16))
        pixels = list(image.getdata())

    average = sum(pixels) / len(pixels)
    value = 0

    for pixel in pixels:
        value = (value << 1) | int(pixel >= average)

    return value


def visual_similarity(hash_a, hash_b):
    return 1.0 - ((hash_a ^ hash_b).bit_count() / 256)


def topic_id_from_draft(draft):
    # Expected: runs/<topic_id>/drafts/<draft_id>
    try:
        return draft.resolve().parents[1].name
    except IndexError:
        return None


def topic_id_from_script(path):
    # Expected: runs/<topic_id>/drafts/<draft_id>/<script>.md
    try:
        return path.resolve().parents[2].name
    except IndexError:
        return None


def read_script(path):
    if not path.is_file():
        return ""

    return normalize(
        path.read_text(encoding="utf-8", errors="replace")
    )


def find_previous_scripts(runs_root, current_draft, script_kind):
    if not runs_root.is_dir():
        return []

    current_topic = topic_id_from_draft(current_draft)
    filename = SCRIPT_NAMES[script_kind]
    found = []

    for path in runs_root.rglob(filename):
        if current_draft.resolve() in path.resolve().parents:
            continue

        old_topic = topic_id_from_script(path)

        # Earlier iterations of the same topic are not separate videos.
        if current_topic and old_topic == current_topic:
            continue

        try:
            text = read_script(path)
            if text:
                found.append((path, text, old_topic))
        except OSError:
            continue

    return found


def inspect_provenance(asset):
    provenance = asset.get("provenance") or {}
    errors = []

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

    if provenance.get("source_type") != "ai_generated":
        errors.append("SOURCE_NOT_DECLARED_AI_GENERATED")

    if missing:
        errors.append(
            "PROVENANCE_MISSING_" + "_".join(missing)
        )

    if provenance.get("commercial_use_confirmed") is not True:
        errors.append("COMMERCIAL_USE_NOT_CONFIRMED")

    if provenance.get("rights_confirmation") is not True:
        errors.append("RIGHTS_NOT_CONFIRMED")

    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Read-only Premium Originality Gate V1.1"
    )

    parser.add_argument("--draft", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--runs-root", default="production/runs"
    )
    parser.add_argument(
        "--visual-warning-threshold",
        type=float,
        default=0.94,
    )
    parser.add_argument(
        "--script-threshold",
        type=float,
        default=0.30,
    )

    args = parser.parse_args()

    draft = Path(args.draft).resolve()
    manifest_path = Path(args.manifest).resolve()
    runs_root = Path(args.runs_root).resolve()

    if not draft.is_dir():
        print("ERROR: Draft folder does not exist:", draft)
        return 2

    if not manifest_path.is_file():
        print("ERROR: Manifest does not exist:", manifest_path)
        return 2

    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        print("ERROR: Cannot read manifest:", exc)
        return 2

    assets = manifest.get("assets")

    if not isinstance(assets, list):
        print("ERROR: Manifest assets must be a list.")
        return 2

    asset_results = []
    exact_hashes = {}
    visual_hashes = []
    direction_history = []
    failed_assets = []
    warnings = []

    for asset in assets:
        if not isinstance(asset, dict):
            continue

        asset_id = str(asset.get("asset_id", "UNKNOWN"))
        relative_path = str(asset.get("asset_path", ""))
        image_path = (manifest_path.parent / relative_path).resolve()

        errors = []
        asset_warnings = []
        details = {}

        # Prevent reading files outside this package.
        try:
            image_path.relative_to(manifest_path.parent.resolve())
        except ValueError:
            errors.append("ASSET_PATH_ESCAPES_PACKAGE")
            image_path = None

        if (
            image_path is None
            or not relative_path
            or not image_path.is_file()
        ):
            errors.append("ASSET_FILE_MISSING")

        else:
            try:
                digest = sha256(image_path)
                details["sha256"] = digest

                if digest in exact_hashes:
                    errors.append(
                        "EXACT_DUPLICATE_OF_" + exact_hashes[digest]
                    )
                else:
                    exact_hashes[digest] = asset_id

                with Image.open(image_path) as image:
                    image.verify()

                with Image.open(image_path) as image:
                    width, height = image.size
                    image_format = image.format or ""

                fmt = str(
                    asset.get("format", "landscape")
                ).lower()

                minimum = (
                    VERTICAL_MIN
                    if fmt == "vertical"
                    else LANDSCAPE_MIN
                )

                details["dimensions"] = [width, height]
                details["image_format"] = image_format
                details["required_minimum"] = list(minimum)

                if width < minimum[0] or height < minimum[1]:
                    errors.append(
                        "BELOW_PREMIUM_MINIMUM_"
                        + f"{minimum[0]}x{minimum[1]}"
                    )

                current_hash = average_hash(image_path)

                for other_id, other_hash in visual_hashes:
                    score = visual_similarity(
                        current_hash, other_hash
                    )

                    if score >= args.visual_warning_threshold:
                        asset_warnings.append(
                            f"VISUAL_SIMILAR_TO_{other_id}_{score:.3f}"
                        )

                visual_hashes.append((asset_id, current_hash))

            except (
                UnidentifiedImageError,
                OSError,
                ValueError,
            ):
                errors.append("IMAGE_UNREADABLE")

        errors.extend(inspect_provenance(asset))

        direction = normalize(
            str(asset.get("visual_direction", ""))
        )
        direction_grams = shingles(direction, 3)

        for other_id, other_grams in direction_history:
            score = jaccard(direction_grams, other_grams)

            if direction_grams and score >= 0.75:
                asset_warnings.append(
                    f"REPEATED_VISUAL_DIRECTION_{other_id}_{score:.3f}"
                )

        direction_history.append((asset_id, direction_grams))

        if asset_warnings:
            warnings.extend(
                f"{asset_id}:{warning}"
                for warning in asset_warnings
            )

        asset_results.append({
            "asset_id": asset_id,
            "asset_path": relative_path,
            "details": details,
            "errors": errors,
            "warnings": asset_warnings,
            "status": "FAIL" if errors else "PASS",
        })

        if errors:
            failed_assets.append(asset_id)

    # Compare long and short scripts independently.
    script_comparisons = []
    script_holds = []
    current_topic = topic_id_from_draft(draft)

    for script_kind, filename in SCRIPT_NAMES.items():
        current_path = draft / filename
        current_text = read_script(current_path)

        if not current_text:
            script_holds.append(
                f"SCRIPT_MISSING_OR_EMPTY:{script_kind}"
            )
            continue

        current_grams = shingles(current_text, 5)

        previous = find_previous_scripts(
            runs_root, draft, script_kind
        )

        for old_path, old_text, old_topic in previous:
            old_grams = shingles(old_text, 5)

            gram_score = jaccard(
                current_grams, old_grams
            )

            sequence_score = SequenceMatcher(
                None,
                current_text[:12000],
                old_text[:12000],
            ).ratio()

            comparison = {
                "script_kind": script_kind,
                "current_topic_id": current_topic,
                "previous_topic_id": old_topic,
                "file": str(old_path),
                "five_gram_jaccard": round(gram_score, 4),
                "sequence_similarity": round(sequence_score, 4),
            }

            script_comparisons.append(comparison)

            if (
                gram_score >= args.script_threshold
                or sequence_score >= 0.65
            ):
                script_holds.append(
                    f"POSSIBLE_SCRIPT_REUSE:{script_kind}:{old_path}"
                )

    gate_pass = not failed_assets and not script_holds

    status = (
        "PASS_ORIGINALITY_AND_PREMIUM_ASSET_GATE"
        if gate_pass
        else "AUTO_REGENERATE_OR_HOLD"
    )

    report = {
        "gate_version": VERSION,
        "status": status,
        "gate_pass": gate_pass,
        "read_only_inputs": True,
        "production_authorization": False,
        "youtube_upload_authorization": False,
        "public_upload_authorization": False,
        "manifest": str(manifest_path),
        "draft_folder": str(draft),
        "topic_id": current_topic,
        "asset_count": len(asset_results),
        "failed_asset_ids": failed_assets,
        "hold_reasons": script_holds,
        "warnings": warnings,
        "warning_count": len(warnings),
        "asset_results": asset_results,
        "script_comparisons": script_comparisons,
        "thresholds": {
            "landscape_minimum": list(LANDSCAPE_MIN),
            "vertical_minimum": list(VERTICAL_MIN),
            "visual_warning_threshold": (
                args.visual_warning_threshold
            ),
            "script_similarity": args.script_threshold,
        },
        "limitations": [
            "Perceptual hash similarity is a warning heuristic, not semantic duplicate detection.",
            "Visual direction similarity is a warning, not an automatic rejection.",
            "Script similarity is a heuristic and needs calibration.",
            "This gate does not fact-check narration.",
            "This gate does not independently verify provider terms online.",
            "A PASS does not grant production, rendering or upload authorization.",
            "This module does not generate replacement assets.",
        ],
    }

    report_path = (
        draft / "premium_originality_gate_v1_1_report.json"
    )

    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    reason_counts = Counter(
        error
        for item in asset_results
        for error in item["errors"]
    )

    print("=" * 60)
    print("PREMIUM ORIGINALITY GATE V1.1")
    print("=" * 60)
    print("STATUS:", status)
    print("TOPIC:", current_topic)
    print("ASSETS:", len(asset_results))
    print("FAILED ASSETS:", len(failed_assets))
    print("SCRIPT HOLDS:", len(script_holds))
    print("WARNINGS:", len(warnings))
    print("SCRIPT COMPARISONS:", len(script_comparisons))

    print("\nFAILURE REASONS:")
    for reason, count in reason_counts.most_common():
        print(f"{reason}: {count}")

    print("\nSCRIPT HOLDS:")
    for reason in script_holds:
        print(reason)

    print("\nREPORT:", report_path)
    print("SOURCE MANIFEST MODIFIED: False")
    print("SOURCE ASSETS MODIFIED: False")
    print("PRODUCTION AUTHORIZATION: False")
    print("UPLOAD AUTHORIZATION: False")

    return 0 if gate_pass else 1


if __name__ == "__main__":
    sys.exit(main())
