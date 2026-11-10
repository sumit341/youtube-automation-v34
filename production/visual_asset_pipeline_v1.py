
from pathlib import Path
from datetime import datetime
import argparse
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / "production/runs/E1irX9cDX8U"


def latest_draft():
    folders = [
        p for p in (RUN_DIR / "drafts").iterdir()
        if p.is_dir()
        and (p / "creative_package.json").exists()
        and (p / "fact_review_report.json").exists()
    ]
    if not folders:
        raise RuntimeError("No complete creative package found.")
    return max(folders, key=lambda p: p.name)


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_task(asset_id, category, format_name, scene, prompt, min_width, min_height):
    return {
        "asset_id": asset_id,
        "category": category,
        "format": format_name,
        "scene_id": scene.get("scene_id", ""),
        "section": scene.get("section", ""),
        "claim_ids": scene.get("claim_ids", []),
        "narration_excerpt": scene.get("narration_excerpt", ""),
        "visual_direction": scene.get("visual_direction", ""),
        "generation_prompt": prompt,
        "minimum_dimensions": {
            "width": min_width,
            "height": min_height,
        },
        "asset_path": f"assets/{asset_id}.png",
        "asset_status": "NOT_CREATED",
        "provenance": {
            "source_type": "",
            "source_url": "",
            "creator": "",
            "license_name": "",
            "license_url": "",
            "attribution_required": None,
            "attribution_text": "",
            "provider": "",
            "model": "",
            "terms_reference": "",
            "terms_checked_at": "",
            "commercial_use_confirmed": False,
            "rights_confirmation": False,
            "generation_prompt_used": "",
            "acquired_at": "",
        },
        "quality": {
            "sha256": "",
            "width": None,
            "height": None,
            "format": "",
            "review_status": "PENDING",
            "review_notes": "",
        },
    }


def safe_asset_path(package_dir, relative_path):
    base = (package_dir / "assets").resolve()
    target = (package_dir / relative_path).resolve()

    if base not in target.parents:
        raise ValueError(f"Unsafe asset path: {relative_path}")

    return target


def provenance_complete(item):
    p = item["provenance"]
    source_type = p.get("source_type", "").strip().lower()

    if source_type == "stock":
        required = [
            p.get("source_url"),
            p.get("creator"),
            p.get("license_name"),
            p.get("license_url"),
        ]
        if not all(required):
            return False, "Stock source/license/creator details incomplete."
        if p.get("attribution_required") is None:
            return False, "Attribution requirement not recorded."
        if p.get("attribution_required") and not p.get("attribution_text"):
            return False, "Required attribution text missing."
        return True, "Stock provenance recorded."

    if source_type == "ai_generated":
        required = [
            p.get("provider"),
            p.get("model"),
            p.get("terms_reference"),
            p.get("terms_checked_at"),
            p.get("generation_prompt_used"),
        ]
        if not all(required):
            return False, "AI provider/model/terms/prompt details incomplete."
        if p.get("commercial_use_confirmed") is not True:
            return False, "Commercial-use terms not confirmed."
        return True, "AI generation provenance recorded; terms still need human review."

    if source_type == "original":
        if not p.get("creator") or p.get("rights_confirmation") is not True:
            return False, "Creator or rights confirmation missing."
        return True, "Original asset rights declared."

    return False, "Unknown source_type. Use stock, ai_generated or original."


def inspect_image(path):
    try:
        from PIL import Image
    except ImportError:
        return None, "Pillow is unavailable."

    try:
        with Image.open(path) as img:
            img.verify()

        with Image.open(path) as img:
            return {
                "width": img.width,
                "height": img.height,
                "format": img.format or "",
            }, "Image decoded successfully."

    except Exception as exc:
        return None, f"Image decode failed: {exc}"


def generate_package():
    draft = latest_draft()
    creative = json.loads(
        (draft / "creative_package.json").read_text(encoding="utf-8")
    )
    fact = json.loads(
        (draft / "fact_review_report.json").read_text(encoding="utf-8")
    )

    if fact.get("review_status") != "PENDING_HUMAN_REVIEW":
        raise RuntimeError("Fact review state changed. Inspect before continuing.")

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    package_dir = draft / f"visual_asset_package_{timestamp}"
    assets_dir = package_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=False)

    tasks = []

    for scene in creative["long_video"]["scenes"]:
        prompt = (
            "Create a premium realistic documentary visual. "
            + scene["visual_direction"]
            + " Narration context: "
            + scene["narration_excerpt"]
            + " No fake statistics, no fabricated study screenshots, "
              "no logos, no readable generated text, no medical diagnosis."
        )
        tasks.append(make_task(
            scene["scene_id"], "long_scene", "landscape",
            scene, prompt, 1280, 720
        ))

    for scene in creative["short_video"]["scenes"]:
        prompt = (
            "Create a premium vertical documentary visual, 9:16. "
            + scene["visual_direction"]
            + " Narration context: "
            + scene["narration_excerpt"]
            + " No fake statistics, no fabricated study screenshots, "
              "no logos, no readable generated text."
        )
        tasks.append(make_task(
            scene["scene_id"], "short_scene", "vertical",
            scene, prompt, 720, 1280
        ))

    for index, thumbnail in enumerate(
        creative["long_video"]["thumbnail_concepts"], 1
    ):
        scene = {
            "scene_id": f"TH{index:02d}",
            "section": thumbnail["concept"],
            "claim_ids": [],
            "narration_excerpt": "",
            "visual_direction": thumbnail["composition"],
        }
        tasks.append(make_task(
            f"TH{index:02d}", "thumbnail", "landscape",
            scene, thumbnail["image_prompt"], 1280, 720
        ))

    package = {
        "package_version": "1.0",
        "created_at": datetime.now().astimezone().isoformat(),
        "topic_id": "E1irX9cDX8U",
        "draft_folder": str(draft),
        "asset_package_folder": str(package_dir),
        "fact_review_status": "PENDING_HUMAN_REVIEW",
        "total_tasks": len(tasks),
        "assets": tasks,
        "approval": {
            "asset_provenance_approved": False,
            "asset_quality_approved": False,
            "visual_plan_approved": False,
            "production_approved": False,
            "render_authorized": False,
            "upload_authorized": False,
        },
        "policy": [
            "No asset is approved merely because a file exists.",
            "Record the actual source and license for every stock asset.",
            "Record provider, model and applicable terms for AI-generated assets.",
            "Do not assume all AI tools permit commercial use.",
            "Do not use assets with unknown or incompatible rights.",
            "Research visuals must not fabricate study screenshots or results.",
            "Human review is required before any asset is approved.",
        ],
    }

    (package_dir / "asset_manifest.json").write_text(
        json.dumps(package, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        "# Visual Asset Task List",
        "",
        f"- Topic: {package['topic_id']}",
        f"- Total asset tasks: {len(tasks)}",
        "- Asset creation: NOT STARTED",
        "- Asset approval: NOT GRANTED",
        "- Production approval: NOT GRANTED",
        "",
        "## Instructions",
        "",
        "Place each completed asset at its asset_path in this package.",
        "Fill in provenance fields in asset_manifest.json.",
        "Then run visual_asset_pipeline_v1.py --validate.",
        "",
    ]

    for task in tasks:
        lines += [
            f"## {task['asset_id']} — {task['category']}",
            f"- Format: {task['format']}",
            f"- Required minimum: {task['minimum_dimensions']['width']} x "
            f"{task['minimum_dimensions']['height']}",
            f"- File path: {task['asset_path']}",
            f"- Section: {task['section']}",
            f"- Claim IDs: {', '.join(task['claim_ids']) or 'None'}",
            f"- Visual direction: {task['visual_direction']}",
            f"- Prompt: {task['generation_prompt']}",
            "- Provenance: PENDING",
            "- Quality review: PENDING",
            "",
        ]

    (package_dir / "asset_tasks.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )

    print("VISUAL ASSET TASK PACKAGE CREATED")
    print("=" * 55)
    print("Draft:", draft)
    print("Package:", package_dir)
    print("Long scene assets:", len(creative["long_video"]["scenes"]))
    print("Short scene assets:", len(creative["short_video"]["scenes"]))
    print("Thumbnail assets:", len(creative["long_video"]["thumbnail_concepts"]))
    print("Total tasks:", len(tasks))
    print("Assets generated: 0")
    print("Asset approval: NOT GRANTED")
    print("Production approval: NOT GRANTED")
    print("Upload authorization: NOT GRANTED")


def validate_package():
    draft = latest_draft()
    packages = sorted(
        p for p in draft.glob("visual_asset_package_*")
        if p.is_dir() and (p / "asset_manifest.json").exists()
    )
    if not packages:
        raise RuntimeError("No visual asset package found.")

    package_dir = packages[-1]
    manifest_path = package_dir / "asset_manifest.json"
    package = json.loads(manifest_path.read_text(encoding="utf-8"))

    passed = 0
    failed = 0

    for item in package["assets"]:
        try:
            path = safe_asset_path(package_dir, item["asset_path"])
        except ValueError as exc:
            item["asset_status"] = "REJECTED"
            item["quality"]["review_status"] = "FAIL"
            item["quality"]["review_notes"] = str(exc)
            failed += 1
            print("FAIL", item["asset_id"], str(exc))
            continue

        if not path.is_file():
            item["asset_status"] = "NOT_CREATED"
            item["quality"]["review_status"] = "PENDING"
            item["quality"]["review_notes"] = "Asset file not found."
            failed += 1
            print("PENDING", item["asset_id"], "File not found.")
            continue

        info, message = inspect_image(path)
        if info is None:
            item["asset_status"] = "REJECTED"
            item["quality"]["review_status"] = "FAIL"
            item["quality"]["review_notes"] = message
            failed += 1
            print("FAIL", item["asset_id"], message)
            continue

        item["quality"].update(info)
        item["quality"]["sha256"] = sha256_file(path)

        minimum = item["minimum_dimensions"]
        dimensions_ok = (
            info["width"] >= minimum["width"]
            and info["height"] >= minimum["height"]
        )

        provenance_ok, provenance_message = provenance_complete(item)

        if not dimensions_ok:
            message = (
                f"Resolution too small: {info['width']}x{info['height']}; "
                f"required {minimum['width']}x{minimum['height']}."
            )
            item["asset_status"] = "REJECTED"
            item["quality"]["review_status"] = "FAIL"
            item["quality"]["review_notes"] = message
            failed += 1
            print("FAIL", item["asset_id"], message)
        elif not provenance_ok:
            item["asset_status"] = "PENDING_PROVENANCE"
            item["quality"]["review_status"] = "PENDING"
            item["quality"]["review_notes"] = provenance_message
            failed += 1
            print("PENDING", item["asset_id"], provenance_message)
        else:
            item["asset_status"] = "TECHNICAL_PASS_HUMAN_REVIEW_PENDING"
            item["quality"]["review_status"] = "PENDING_HUMAN_REVIEW"
            item["quality"]["review_notes"] = (
                "File and provenance fields passed basic checks. "
                "Visual suitability and rights still require human review."
            )
            passed += 1
            print("TECHNICAL PASS", item["asset_id"])

    package["last_validation_at"] = datetime.now().astimezone().isoformat()
    package["validation_summary"] = {
        "technical_pass": passed,
        "not_passed_or_pending": failed,
        "human_review_required": True,
    }
    package["approval"]["asset_provenance_approved"] = False
    package["approval"]["asset_quality_approved"] = False
    package["approval"]["visual_plan_approved"] = False
    package["approval"]["production_approved"] = False
    package["approval"]["render_authorized"] = False
    package["approval"]["upload_authorized"] = False

    manifest_path.write_text(
        json.dumps(package, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("=" * 55)
    print("Package:", package_dir)
    print("Technical pass:", passed)
    print("Pending / failed:", failed)
    print("Human review required: YES")
    print("Production approval: NOT GRANTED")
    print("Upload authorization: NOT GRANTED")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate files and provenance in the latest asset package.",
    )
    args = parser.parse_args()

    if args.validate:
        validate_package()
    else:
        generate_package()
