
#!/usr/bin/env python3
"""Premium Originality Gate V1 - read-only asset/script validation."""

import argparse
import hashlib
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

from PIL import Image, UnidentifiedImageError

VERSION = "1.0.0"
LANDSCAPE_MIN = (1920, 1080)
VERTICAL_MIN = (1080, 1920)


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
        "draft", "scene", "visual", "section", "claim"
    }
    return " ".join(w for w in text.split() if len(w) > 2 and w not in ignored)


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


def similarity(hash_a, hash_b):
    return 1.0 - ((hash_a ^ hash_b).bit_count() / 256)


def read_script_files(draft):
    names = (
        "long_video_script_draft.md",
        "short_video_script_draft.md",
    )
    parts = []
    for name in names:
        path = draft / name
        if path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def find_previous_scripts(runs_root, current_draft):
    if not runs_root.is_dir():
        return []
    found = []
    names = {
        "long_video_script_draft.md",
        "short_video_script_draft.md",
    }
    for path in runs_root.rglob("*.md"):
        if path.name not in names:
            continue
        if current_draft == path.parent or current_draft in path.parents:
            continue
        try:
            found.append((
                path,
                normalize(path.read_text(encoding="utf-8", errors="replace"))
            ))
        except OSError:
            continue
    return found


def main():
    parser = argparse.ArgumentParser(
        description="Read-only Premium Originality Gate V1"
    )
    parser.add_argument("--draft", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--runs-root", default="production/runs")
    parser.add_argument("--visual-threshold", type=float, default=0.94)
    parser.add_argument("--script-threshold", type=float, default=0.30)
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
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
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

    for asset in assets:
        if not isinstance(asset, dict):
            continue

        asset_id = str(asset.get("asset_id", "UNKNOWN"))
        relative_path = str(asset.get("asset_path", ""))
        image_path = (manifest_path.parent / relative_path).resolve()
        errors = []
        details = {}

        # Ensure the manifest cannot make this checker read arbitrary files.
        try:
            image_path.relative_to(manifest_path.parent.resolve())
        except ValueError:
            errors.append("ASSET_PATH_ESCAPES_PACKAGE")
            image_path = None

        if image_path is None or not relative_path or not image_path.is_file():
            errors.append("ASSET_FILE_MISSING")
        else:
            digest = sha256(image_path)
            details["sha256"] = digest

            if digest in exact_hashes:
                errors.append("EXACT_DUPLICATE_OF_" + exact_hashes[digest])
            else:
                exact_hashes[digest] = asset_id

            try:
                with Image.open(image_path) as image:
                    width, height = image.size
                    image_format = image.format

                fmt = str(asset.get("format", "landscape")).lower()
                minimum = (
                    VERTICAL_MIN if fmt == "vertical" else LANDSCAPE_MIN
                )
                details["dimensions"] = [width, height]
                details["image_format"] = image_format
                details["required_minimum"] = list(minimum)

                if width < minimum[0] or height < minimum[1]:
                    errors.append(
                        "BELOW_PREMIUM_MINIMUM_"
                        + str(minimum[0]) + "x" + str(minimum[1])
                    )

                current_hash = average_hash(image_path)
                for other_id, other_hash in visual_hashes:
                    score = similarity(current_hash, other_hash)
                    if score >= args.visual_threshold:
                        errors.append(
                            f"VISUAL_SIMILAR_TO_{other_id}_SCORE_{score:.3f}"
                        )
                visual_hashes.append((asset_id, current_hash))

            except (UnidentifiedImageError, OSError, ValueError):
                errors.append("IMAGE_UNREADABLE")

        provenance = asset.get("provenance") or {}
        required_fields = (
            "provider",
            "model",
            "terms_reference",
            "terms_checked_at",
            "generation_prompt_used",
        )
        missing = [
            field for field in required_fields
            if not provenance.get(field)
        ]

        if provenance.get("source_type") != "ai_generated":
            errors.append("SOURCE_NOT_DECLARED_AI_GENERATED")
        if missing:
            errors.append("PROVENANCE_MISSING_" + "_".join(missing))
        if provenance.get("commercial_use_confirmed") is not True:
            errors.append("COMMERCIAL_USE_NOT_CONFIRMED")
        if provenance.get("rights_confirmation") is not True:
            errors.append("RIGHTS_NOT_CONFIRMED")

        direction = normalize(str(asset.get("visual_direction", "")))
        direction_shingles = shingles(direction, 3)

        for other_id, other_shingles in direction_history:
            score = jaccard(direction_shingles, other_shingles)
            if direction_shingles and score >= 0.75:
                errors.append(
                    f"REPEATED_VISUAL_DIRECTION_{other_id}_{score:.3f}"
                )

        direction_history.append((asset_id, direction_shingles))

        asset_results.append({
            "asset_id": asset_id,
            "asset_path": relative_path,
            "details": details,
            "errors": errors,
            "status": "FAIL" if errors else "PASS",
        })

        if errors:
            failed_assets.append(asset_id)

    # Script novelty is compared with previous drafts, not approved as factual.
    current_script = normalize(read_script_files(draft))
    current_grams = shingles(current_script, 5)
    script_comparisons = []
    script_holds = []

    if current_script:
        for old_path, old_text in find_previous_scripts(runs_root, draft):
            old_grams = shingles(old_text, 5)
            gram_score = jaccard(current_grams, old_grams)
            sequence_score = SequenceMatcher(
                None, current_script[:12000], old_text[:12000]
            ).ratio()

            script_comparisons.append({
                "file": str(old_path),
                "five_gram_jaccard": round(gram_score, 4),
                "sequence_similarity": round(sequence_score, 4),
            })

            if gram_score >= args.script_threshold or sequence_score >= 0.65:
                script_holds.append(
                    "POSSIBLE_SCRIPT_REUSE:" + str(old_path)
                )
    else:
        script_holds.append("SCRIPT_MISSING_OR_EMPTY")

    hold_reasons = list(script_holds)

    # This gate never grants production or upload authorization.
    gate_pass = not failed_assets and not hold_reasons
    status = (
        "PASS_ORIGINALITY_AND_PREMIUM_ASSET_GATE"
        if gate_pass else "AUTO_REGENERATE_OR_HOLD"
    )

    report = {
        "gate_version": VERSION,
        "status": status,
        "gate_pass": gate_pass,
        "read_only": True,
        "production_authorization": False,
        "youtube_upload_authorization": False,
        "public_upload_authorization": False,
        "manifest": str(manifest_path),
        "draft_folder": str(draft),
        "asset_count": len(asset_results),
        "failed_asset_ids": failed_assets,
        "hold_reasons": hold_reasons,
        "asset_results": asset_results,
        "script_comparisons": script_comparisons,
        "thresholds": {
            "landscape_minimum": list(LANDSCAPE_MIN),
            "vertical_minimum": list(VERTICAL_MIN),
            "visual_similarity": args.visual_threshold,
            "script_similarity": args.script_threshold,
        },
        "limitations": [
            "Perceptual hashes are similarity heuristics, not semantic AI detection.",
            "Script similarity is a heuristic and needs calibration.",
            "This gate does not fact-check narration or verify provider terms online.",
            "A PASS does not grant production or upload authorization.",
            "This module reports failures; it does not generate replacement assets.",
        ],
    }

    report_path = draft / "premium_originality_gate_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("=" * 58)
    print("PREMIUM ORIGINALITY GATE V1")
    print("=" * 58)
    print("STATUS:", status)
    print("ASSETS:", len(asset_results))
    print("FAILED ASSETS:", len(failed_assets))
    print("SCRIPT HOLDS:", len(hold_reasons))
    print("REPORT:", report_path)
    print("READ ONLY: True")
    print("PRODUCTION AUTHORIZATION: False")
    print("UPLOAD AUTHORIZATION: False")
    return 0 if gate_pass else 1


if __name__ == "__main__":
    sys.exit(main())
