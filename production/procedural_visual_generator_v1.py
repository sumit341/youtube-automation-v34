
from pathlib import Path
from datetime import datetime
import hashlib
import json
import math
import random

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / "production/runs/E1irX9cDX8U"


def latest_package():
    draft_dirs = [
        p for p in (RUN_DIR / "drafts").iterdir()
        if p.is_dir() and (p / "creative_package.json").exists()
    ]
    if not draft_dirs:
        raise RuntimeError("Creative package not found.")

    draft = max(draft_dirs, key=lambda p: p.name)
    packages = sorted(
        p for p in draft.glob("visual_asset_package_*")
        if p.is_dir() and (p / "asset_manifest.json").exists()
    )
    if not packages:
        raise RuntimeError("Visual asset task package not found.")

    return draft, packages[-1]


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def rgb_gradient(size, seed):
    width, height = size
    random.seed(seed)
    top = (8, 16, 34)
    bottom = (20, 43, 62)

    image = Image.new("RGB", size)
    pixels = image.load()

    for y in range(height):
        t = y / max(1, height - 1)
        color = tuple(
            int(top[i] * (1 - t) + bottom[i] * t)
            for i in range(3)
        )
        for x in range(width):
            glow = max(0, 1 - math.sqrt(
                ((x - width * 0.72) / width) ** 2
                + ((y - height * 0.28) / height) ** 2
            ) * 2.1)
            pixels[x, y] = tuple(
                min(255, int(color[i] + glow * (18, 24, 30)[i]))
                for i in range(3)
            )

    return image


def point(size, x, y):
    return int(size[0] * x), int(size[1] * y)


def ellipse(draw, size, box, fill, outline=None, width=1):
    x1, y1, x2, y2 = box
    draw.ellipse(
        (int(size[0] * x1), int(size[1] * y1),
         int(size[0] * x2), int(size[1] * y2)),
        fill=fill, outline=outline, width=width
    )


def line(draw, size, coords, fill, width=2):
    pts = [point(size, x, y) for x, y in coords]
    draw.line(pts, fill=fill, width=width)


def rounded(draw, size, box, radius, fill, outline=None, width=1):
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(
        (int(size[0] * x1), int(size[1] * y1),
         int(size[0] * x2), int(size[1] * y2)),
        radius=int(min(size) * radius),
        fill=fill, outline=outline, width=width
    )


def draw_base(size, seed):
    image = rgb_gradient(size, seed)
    draw = ImageDraw.Draw(image, "RGBA")
    w, h = size

    # Fine cinematic grid.
    step = max(28, w // 28)
    for x in range(0, w, step):
        draw.line((x, 0, x, h), fill=(130, 175, 200, 13), width=1)
    for y in range(0, h, step):
        draw.line((0, y, w, y), fill=(130, 175, 200, 10), width=1)

    # Soft abstract light sources.
    overlay = Image.new("RGBA", size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    cx, cy = int(w * 0.75), int(h * 0.22)
    radius = int(min(size) * 0.28)
    for r in range(radius, 0, -8):
        alpha = int(1 + 7 * (1 - r / radius))
        od.ellipse(
            (cx-r, cy-r, cx+r, cy+r),
            fill=(63, 150, 175, alpha)
        )
    overlay = overlay.filter(ImageFilter.GaussianBlur(24))
    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    return image


def draw_bedroom(draw, size):
    # Window and moon.
    rounded(draw, size, (0.68, 0.10, 0.91, 0.47), 0.015,
            (13, 30, 49, 255), (110, 160, 185, 180), 3)
    line(draw, size, [(0.795, 0.10), (0.795, 0.47)],
         (100, 145, 175, 180), 3)
    line(draw, size, [(0.68, 0.29), (0.91, 0.29)],
         (100, 145, 175, 180), 3)
    ellipse(draw, size, (0.78, 0.16, 0.85, 0.28),
            (228, 193, 135, 230))

    # Bed.
    rounded(draw, size, (0.10, 0.61, 0.87, 0.86), 0.025,
            (22, 37, 55, 255), (100, 132, 155, 180), 3)
    rounded(draw, size, (0.16, 0.57, 0.39, 0.70), 0.03,
            (45, 64, 83, 255))
    line(draw, size, [(0.10, 0.86), (0.10, 0.94)], (160, 130, 102, 255), 5)
    line(draw, size, [(0.87, 0.86), (0.87, 0.94)], (160, 130, 102, 255), 5)

    # Person silhouette, deliberately non-identifiable.
    ellipse(draw, size, (0.39, 0.46, 0.50, 0.62),
            (17, 24, 37, 255))
    line(draw, size, [(0.46, 0.60), (0.58, 0.72), (0.73, 0.72)],
         (17, 24, 37, 255), max(8, size[0] // 45))


def draw_thought_loop(draw, size):
    for i, box in enumerate([
        (0.10, 0.18, 0.39, 0.58),
        (0.31, 0.34, 0.61, 0.73),
        (0.55, 0.15, 0.85, 0.55),
    ]):
        rounded(draw, size, box, 0.035,
                (18, 42, 61, 210),
                (80 + i * 20, 175, 190, 190), 3)
        ellipse(draw, size, (
            box[0] + 0.08, box[1] + 0.08,
            box[0] + 0.19, box[1] + 0.19
        ), (226, 163, 103, 230))
    line(draw, size, [(0.38, 0.37), (0.48, 0.30), (0.57, 0.37)],
         (229, 170, 106, 230), 5)
    line(draw, size, [(0.57, 0.37), (0.52, 0.43)],
         (229, 170, 106, 230), 5)


def draw_research_desk(draw, size, seed):
    # Desk surface and research sheets.
    rounded(draw, size, (0.10, 0.56, 0.90, 0.86), 0.02,
            (31, 48, 61, 255), (115, 150, 165, 180), 3)
    for i in range(3):
        x = 0.18 + i * 0.22
        rounded(draw, size, (x, 0.29, x + 0.17, 0.61), 0.012,
                (218, 219, 207, 245))
        for j in range(4):
            yy = 0.36 + j * 0.045
            line(draw, size, [(x + 0.025, yy), (x + 0.14, yy)],
                 (80, 110, 125, 150), 2)

    # Abstract bars without numerical labels.
    base_y = 0.51
    for i, height in enumerate([0.12, 0.21, 0.15, 0.27, 0.19]):
        x = 0.68 + i * 0.045
        rounded(draw, size, (x, base_y-height, x+0.025, base_y),
                0.006, (72, 174, 184, 230))


def draw_phone(draw, size):
    rounded(draw, size, (0.36, 0.12, 0.66, 0.83), 0.035,
            (8, 14, 25, 255), (151, 177, 190, 255), 5)
    rounded(draw, size, (0.39, 0.18, 0.63, 0.76), 0.02,
            (27, 48, 65, 255))
    rounded(draw, size, (0.42, 0.27, 0.59, 0.38), 0.02,
            (68, 111, 132, 255))
    rounded(draw, size, (0.43, 0.44, 0.60, 0.54), 0.02,
            (48, 81, 102, 255))
    rounded(draw, size, (0.42, 0.60, 0.56, 0.68), 0.02,
            (68, 111, 132, 255))
    ellipse(draw, size, (0.48, 0.79, 0.54, 0.81),
            (150, 175, 185, 255))


def draw_emotion(draw, size):
    # Abstract day-night horizon and pulse-like curve.
    line(draw, size, [(0.08, 0.72), (0.92, 0.72)],
         (125, 165, 180, 170), 3)
    ellipse(draw, size, (0.15, 0.25, 0.38, 0.48),
            (229, 174, 110, 230))
    ellipse(draw, size, (0.66, 0.17, 0.83, 0.34),
            (180, 202, 214, 225))
    line(draw, size, [
        (0.10, 0.61), (0.23, 0.56), (0.34, 0.62),
        (0.45, 0.47), (0.55, 0.59), (0.68, 0.52),
        (0.82, 0.58), (0.92, 0.48)
    ], (90, 202, 194, 240), 5)


def draw_treatment(draw, size):
    # Calm consultation / structured routine aesthetic.
    rounded(draw, size, (0.12, 0.18, 0.88, 0.82), 0.025,
            (23, 43, 59, 255), (105, 153, 171, 190), 3)
    for i in range(3):
        y = 0.32 + i * 0.15
        rounded(draw, size, (0.22, y, 0.29, y+0.07), 0.01,
                (62, 174, 158, 240))
        line(draw, size, [(0.35, y+0.035), (0.75, y+0.035)],
             (171, 194, 197, 220), 3)
    ellipse(draw, size, (0.73, 0.62, 0.82, 0.71),
            (224, 166, 103, 230))


def draw_takeaway(draw, size):
    # Morning window and notebook.
    rounded(draw, size, (0.64, 0.10, 0.89, 0.53), 0.012,
            (40, 75, 91, 255), (130, 174, 184, 200), 3)
    ellipse(draw, size, (0.72, 0.17, 0.83, 0.34),
            (231, 184, 117, 240))
    rounded(draw, size, (0.12, 0.61, 0.56, 0.84), 0.02,
            (202, 197, 176, 255), (95, 120, 130, 220), 3)
    for y in [0.68, 0.74, 0.80]:
        line(draw, size, [(0.19, y), (0.49, y)],
             (85, 113, 126, 180), 2)


def draw_thumbnail(draw, size, concept):
    if concept == "Awake at 11:30 PM":
        draw_bedroom(draw, size)
        draw_thought_loop(draw, size)
    elif concept == "Mind vs. Sleep":
        draw_bedroom(draw, size)
        draw_emotion(draw, size)
    else:
        draw_thought_loop(draw, size)
        ellipse(draw, size, (0.38, 0.30, 0.62, 0.62),
                (35, 62, 79, 255), (220, 169, 110, 230), 5)


def render_asset(item, output_path):
    fmt = item["format"]
    size = (720, 1280) if fmt == "vertical" else (1280, 720)
    seed = sum(ord(c) for c in item["asset_id"] + item["section"])
    random.seed(seed)

    image = draw_base(size, seed)
    draw = ImageDraw.Draw(image, "RGBA")

    category = item["category"]
    heading = item.get("section", "").lower()

    if category == "thumbnail":
        draw_thumbnail(draw, size, item["section"])
    elif heading == "hook":
        draw_bedroom(draw, size)
    elif heading == "context":
        draw_thought_loop(draw, size)
    elif heading in {"study one", "study two"}:
        draw_research_desk(draw, size, seed)
    elif heading == "illustrative example":
        draw_phone(draw, size)
    elif heading == "sleep and emotion":
        draw_emotion(draw, size)
    elif heading in {"treatment evidence", "what cbt-i evidence says"}:
        draw_treatment(draw, size)
    elif heading in {"takeaway", "practical takeaway"}:
        draw_takeaway(draw, size)
    else:
        draw_thought_loop(draw, size)

    # Decorative focus rings, deterministic and text-free.
    for i in range(3):
        x = 0.12 + i * 0.10
        ellipse(draw, size, (x, 0.88, x+0.025, 0.88+0.025),
                (94, 191, 187, 170))

    image.convert("RGB").save(output_path, format="PNG", optimize=True)


def main():
    draft, package_dir = latest_package()
    manifest_path = package_dir / "asset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    created = 0

    for item in manifest["assets"]:
        relative = Path(item["asset_path"])
        output = (package_dir / relative).resolve()

        assets_root = (package_dir / "assets").resolve()
        if assets_root not in output.parents:
            raise RuntimeError(f"Unsafe output path: {relative}")

        if output.exists():
            print("SKIP existing:", item["asset_id"])
            continue

        output.parent.mkdir(parents=True, exist_ok=True)
        render_asset(item, output)

        with Image.open(output) as img:
            width, height = img.size
            image_format = img.format or "PNG"

        item["provenance"].update({
            "source_type": "original",
            "creator": "Locally generated procedural artwork",
            "rights_confirmation": True,
            "generation_prompt_used": item["generation_prompt"],
            "acquired_at": datetime.now().astimezone().isoformat(),
        })

        item["quality"].update({
            "sha256": sha256_file(output),
            "width": width,
            "height": height,
            "format": image_format,
            "review_status": "PENDING_HUMAN_REVIEW",
            "review_notes": (
                "Locally generated original 2D graphic. "
                "Visual suitability still requires human review."
            ),
        })

        item["asset_status"] = "CREATED_PENDING_REVIEW"
        created += 1
        print("CREATED", item["asset_id"], f"{width}x{height}")

    manifest["last_generation_at"] = datetime.now().astimezone().isoformat()
    manifest["generation_summary"] = {
        "new_files_created": created,
        "total_tasks": len(manifest["assets"]),
        "human_review_required": True,
    }

    for key in manifest["approval"]:
        manifest["approval"][key] = False

    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("=" * 55)
    print("LOCAL VISUAL GENERATION COMPLETE")
    print("New files created:", created)
    print("Total tasks:", len(manifest["assets"]))
    print("Human review: PENDING")
    print("Production approval: NOT GRANTED")
    print("Upload authorization: NOT GRANTED")


if __name__ == "__main__":
    main()
