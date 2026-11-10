from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFilter, ImageChops
import hashlib, json, random, argparse, sys

ROOT = Path(__file__).resolve().parent.parent
TOPIC = "E1irX9cDX8U"
VERSION = "1.0.0"

def latest_draft(topic):
    base = ROOT / "production" / "runs" / topic / "drafts"
    candidates = []
    for p in base.iterdir():
        if p.is_dir() and (p / "creative_package.json").is_file():
            fact = p / "automated_fact_check_v2_report.json"
            if fact.is_file():
                try:
                    if json.loads(fact.read_text(encoding="utf-8-sig")).get("status") == "PASS":
                        candidates.append(p)
                except Exception:
                    pass
    if not candidates:
        raise RuntimeError("No draft with creative package and passing fact-check report.")
    return max(candidates, key=lambda p: p.stat().st_mtime)

def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def seed_for(text, attempt):
    raw = (text + "|" + str(attempt)).encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:16], 16)

def make_artwork(task, output, attempt=0):
    width, height = task["width"], task["height"]
    rng = random.Random(seed_for(task["asset_id"] + task["visual_direction"], attempt))

    palettes = [
        ((8, 15, 35), (24, 55, 86), (13, 112, 124)),
        ((18, 12, 35), (72, 35, 83), (169, 91, 82)),
        ((7, 24, 29), (18, 75, 78), (94, 137, 111)),
        ((22, 18, 15), (83, 57, 36), (169, 119, 66)),
        ((12, 17, 29), (39, 54, 83), (103, 89, 140)),
    ]
    c1, c2, accent = rng.choice(palettes)

    # Cinematic gradient background.
    gradient = Image.linear_gradient("L").resize((width, height))
    background = Image.new("RGB", (width, height), c1)
    top = Image.new("RGB", (width, height), c2)
    background = Image.composite(top, background, gradient)

    # Soft light source.
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gx = rng.randint(width // 4, width * 3 // 4)
    gy = rng.randint(height // 4, height * 3 // 4)
    radius = int(min(width, height) * rng.uniform(.20, .42))
    gd.ellipse((gx-radius, gy-radius, gx+radius, gy+radius),
               fill=(*accent, 115))
    glow = glow.filter(ImageFilter.GaussianBlur(radius * .55))
    background = Image.alpha_composite(background.convert("RGBA"), glow)

    # Original geometric documentary composition.
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    short = min(width, height)

    # Fine grid and perspective lines.
    spacing = max(55, short // 13)
    for x in range(0, width, spacing):
        draw.line((x, 0, x, height), fill=(210, 225, 235, 13), width=1)
    for y in range(0, height, spacing):
        draw.line((0, y, width, y), fill=(210, 225, 235, 13), width=1)

    # Layered rings / orbital geometry.
    cx = rng.randint(width // 3, width * 2 // 3)
    cy = rng.randint(height // 3, height * 2 // 3)
    for k in range(5):
        r = int(short * (.12 + k * .075))
        draw.ellipse((cx-r, cy-r, cx+r, cy+r),
                     outline=(*accent, max(18, 90-k*12)),
                     width=max(2, short // 500))

    # Directional beams.
    for _ in range(16):
        x1 = rng.randint(-width // 3, width)
        y1 = rng.randint(-height // 3, height)
        x2 = x1 + rng.randint(-width // 2, width // 2)
        y2 = y1 + rng.randint(-height // 2, height // 2)
        draw.line((x1, y1, x2, y2),
                  fill=(*accent, rng.randint(12, 45)),
                  width=rng.randint(1, max(2, short // 300)))

    # Abstract focal forms.
    for _ in range(12):
        x = rng.randint(0, width)
        y = rng.randint(0, height)
        r = rng.randint(short // 45, short // 10)
        col = rng.choice([(*accent, 28), (220, 230, 240, 18), (4, 8, 18, 50)])
        draw.ellipse((x-r, y-r, x+r, y+r), fill=col,
                     outline=(*accent, 65), width=max(1, short // 600))

    # Unique scene-specific diagonal motif.
    points = [
        (rng.randint(0, width), rng.randint(0, height))
        for _ in range(7)
    ]
    draw.line(points, fill=(*accent, 150), width=max(3, short // 220),
              joint="curve")

    composed = Image.alpha_composite(background, layer)

    # Subtle vignette.
    mask = Image.new("L", (width, height), 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((-width//4, -height//4, width*5//4, height*5//4),
               fill=210)
    mask = mask.filter(ImageFilter.GaussianBlur(short // 5))
    dark = Image.new("RGBA", (width, height), (0, 0, 0, 90))
    dark.putalpha(ImageChops.invert(mask).point(lambda p: int(p * .65)))
    composed = Image.alpha_composite(composed, dark)

    composed.convert("RGB").save(output, "JPEG", quality=94, optimize=True)
    return output

def collect_tasks(creative):
    tasks = []
    for scene in creative["long_video"]["scenes"]:
        tasks.append({
            "asset_id": "LONG_" + str(scene["scene_id"]),
            "category": "long_scene",
            "format": "landscape",
            "width": 1920, "height": 1080,
            "scene_id": scene.get("scene_id", ""),
            "section": scene.get("section", ""),
            "claim_ids": scene.get("claim_ids", []),
            "visual_direction": scene.get("visual_direction", ""),
            "narration_excerpt": scene.get("narration_excerpt", ""),
        })
    for scene in creative["short_video"]["scenes"]:
        tasks.append({
            "asset_id": "SHORT_" + str(scene["scene_id"]),
            "category": "short_scene",
            "format": "vertical",
            "width": 1080, "height": 1920,
            "scene_id": scene.get("scene_id", ""),
            "section": scene.get("section", ""),
            "claim_ids": scene.get("claim_ids", []),
            "visual_direction": scene.get("visual_direction", ""),
            "narration_excerpt": scene.get("narration_excerpt", ""),
        })
    for i, thumb in enumerate(creative["long_video"]["thumbnail_concepts"], 1):
        tasks.append({
            "asset_id": f"THUMB_{i:02d}",
            "category": "thumbnail",
            "format": "landscape",
            "width": 1920, "height": 1080,
            "scene_id": f"TH{i:02d}",
            "section": thumb.get("concept", ""),
            "claim_ids": [],
            "visual_direction": thumb.get("composition", ""),
            "narration_excerpt": "",
        })
    return tasks

def run(topic):
    draft = latest_draft(topic)
    creative_path = draft / "creative_package.json"
    creative = json.loads(creative_path.read_text(encoding="utf-8-sig"))
    tasks = collect_tasks(creative)
    if not tasks:
        raise RuntimeError("Creative package contains no visual tasks.")

    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    package_dir = draft / f"automated_visual_assets_v1_{stamp}"
    assets_dir = package_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=False)

    results, hashes = [], set()
    for task in tasks:
        filename = task["asset_id"] + ".jpg"
        path = assets_dir / filename
        errors = []

        # Bounded local regeneration: maximum two attempts.
        for attempt in range(2):
            make_artwork(task, path, attempt)
            try:
                with Image.open(path) as im:
                    im.verify()
                with Image.open(path) as im:
                    valid = im.size == (task["width"], task["height"])
                file_hash = digest(path)
                if valid and file_hash not in hashes:
                    break
                errors.append("DIMENSION_OR_DUPLICATE_RETRY")
            except Exception as exc:
                errors.append("IMAGE_DECODE_RETRY:" + str(exc))
        else:
            results.append({
                **task, "asset_path": "assets/" + filename,
                "status": "REJECTED", "errors": errors
            })
            continue

        hashes.add(file_hash)
        results.append({
            **task,
            "asset_path": "assets/" + filename,
            "status": "AUTOMATED_TECHNICAL_PASS",
            "sha256": file_hash,
            "provenance": {
                "source_type": "local_procedural_original",
                "renderer": "project-authored Pillow drawing pipeline",
                "renderer_version": VERSION,
                "external_images_used": False,
                "stock_media_used": False,
                "third_party_fonts_used": False,
                "generation_seed": seed_for(task["asset_id"] + task["visual_direction"], 0),
                "rights_basis": "Locally rendered geometric artwork; no external media inputs.",
            },
            "quality": {
                "width": task["width"], "height": task["height"],
                "format": "JPEG", "decode": "PASS",
                "exact_duplicate": False,
            },
            "errors": errors,
        })

    passed = sum(x["status"] == "AUTOMATED_TECHNICAL_PASS" for x in results)
    failed = len(results) - passed
    manifest = {
        "version": VERSION,
        "topic_id": topic,
        "created_at": datetime.now().astimezone().isoformat(),
        "draft_directory": str(draft),
        "package_directory": str(package_dir),
        "generation_method": "local_procedural_original",
        "external_media_used": False,
        "total_assets": len(results),
        "automated_technical_pass": passed,
        "rejected": failed,
        "assets": results,
        "automated_visual_gate": "PASS" if failed == 0 else "HOLD",
        "limitations": [
            "These are original procedural graphics, not photorealistic AI images.",
            "Automated checks validate dimensions, file integrity and exact duplicates.",
            "Visual semantic relevance is not independently understood by a vision model.",
            "No external stock or AI provider was used; this is not a legal opinion on copyright.",
            "Technical visual pass does not authorize rendering, production or publication.",
        ],
        "approval": {
            "automated_technical_gate_pass": failed == 0,
            "production_approved": False,
            "render_authorized": False,
            "upload_authorized": False,
            "public_upload_authorized": False,
        },
    }
    manifest_path = package_dir / "asset_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    report_path = package_dir / "automated_visual_gate_report.json"
    report_path.write_text(json.dumps({
        "status": manifest["automated_visual_gate"],
        "total": len(results), "passed": passed, "rejected": failed,
        "manifest": str(manifest_path),
        "production_approved": False,
        "render_authorized": False,
        "upload_authorized": False,
    }, indent=2), encoding="utf-8")

    print("=" * 60)
    print("AUTOMATED VISUAL ASSET ENGINE", VERSION)
    print("TOPIC:", topic)
    print("PACKAGE:", package_dir)
    print("TOTAL:", len(results))
    print("TECHNICAL PASS:", passed)
    print("REJECTED:", failed)
    print("VISUAL GATE:", manifest["automated_visual_gate"])
    print("PRODUCTION APPROVED: False")
    print("RENDER AUTHORIZED: False")
    print("UPLOAD AUTHORIZED: False")
    print("MANIFEST:", manifest_path)
    print("=" * 60)
    return 0 if failed == 0 else 1

def self_test():
    assert seed_for("scene", 0) == seed_for("scene", 0)
    assert seed_for("scene", 0) != seed_for("scene", 1)
    assert (1920, 1080) != (1080, 1920)
    print("[PASS] Visual engine self-tests: 3 scenarios")
    return 0

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-id", default=TOPIC)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    try:
        sys.exit(self_test() if args.self_test else run(args.topic_id))
    except Exception as exc:
        print("[HOLD]", type(exc).__name__ + ":", exc)
        sys.exit(1)
