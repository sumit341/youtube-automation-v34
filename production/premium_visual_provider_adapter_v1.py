
#!/usr/bin/env python3
"""
Premium Visual Provider Adapter V1

OpenAI-compatible image-generation endpoint adapter.
- Dry-run by default.
- Explicit --generate required for API calls.
- Default generation limit: one asset.
- Never edits source manifests or existing assets.
- Saves versioned outputs and a separate provenance report.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, UnidentifiedImageError


VERSION = "1.0.0"

COMPOSITIONS = [
    "Use a wide establishing shot, with the subject positioned on the left third.",
    "Use an intimate close-up, with foreground depth and a different camera angle.",
    "Use a medium shot with layered foreground, subject and background elements.",
    "Use a high-angle cinematic composition with strong environmental storytelling.",
    "Use a low-angle composition with natural perspective and realistic lighting.",
    "Use a distant environmental shot with the subject small in the frame.",
    "Use an over-the-shoulder composition with a distinctive foreground element.",
    "Use a profile composition with practical environmental light sources.",
]


def env(name, default=""):
    return os.environ.get(name, default).strip()


def safe_id(value):
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", str(value))
    return value[:80] or "asset"


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_prompt(asset):
    asset_id = str(asset.get("asset_id", "UNKNOWN"))
    direction = str(asset.get("visual_direction", "")).strip()
    narration = str(asset.get("narration_excerpt", "")).strip()
    category = str(asset.get("category", "")).strip()
    section = str(asset.get("section", "")).strip()

    index = int(
        hashlib.sha256(asset_id.encode("utf-8")).hexdigest()[:8],
        16,
    ) % len(COMPOSITIONS)

    composition = COMPOSITIONS[index]

    return f"""
Create one premium, photorealistic documentary frame.

SCENE:
{direction}

NARRATION CONTEXT:
{narration}

PRODUCTION CONTEXT:
Asset ID: {asset_id}
Category: {category}
Section: {section}

COMPOSITION:
{composition}

ORIGINALITY REQUIREMENTS:
Create a genuinely distinct composition for this scene.
Do not reuse a generic template, identical camera framing,
identical subject placement, or repeated background layout.
Use scene-specific objects, lighting, depth and perspective.
The scene must communicate the narration naturally.

VISUAL QUALITY:
Professional documentary cinematography.
Physically plausible lighting and materials.
Natural human anatomy and expressions.
Detailed realistic environment.
Restrained color grading and believable depth.
No cartoon illustration or flat procedural artwork.

SAFETY AND ACCURACY:
No fabricated statistics.
No fake study screenshots.
No logos or watermarks.
No readable generated text.
No medical diagnosis.
No exaggerated distress.
Do not depict a real identifiable person.
""".strip()


def expected_size(asset):
    fmt = str(asset.get("format", "landscape")).lower()

    if fmt == "vertical":
        return env("VISUAL_VERTICAL_SIZE", "1080x1920")

    return env("VISUAL_LANDSCAPE_SIZE", "1920x1080")


def parse_size(value):
    match = re.fullmatch(r"(\d{3,5})x(\d{3,5})", value)

    if not match:
        raise ValueError(
            f"Invalid image size: {value}. Expected WIDTHxHEIGHT."
        )

    return int(match.group(1)), int(match.group(2))


def validate_image(data, asset, output_path):
    minimum = (
        (1080, 1920)
        if str(asset.get("format", "")).lower() == "vertical"
        else (1920, 1080)
    )

    output_path.write_bytes(data)

    try:
        with Image.open(output_path) as image:
            image.verify()

        with Image.open(output_path) as image:
            width, height = image.size
            image_format = image.format

    except (UnidentifiedImageError, OSError):
        raise ValueError("Provider response is not a valid image.")

    if width < minimum[0] or height < minimum[1]:
        raise ValueError(
            f"Resolution rejected: {width}x{height}; "
            f"minimum is {minimum[0]}x{minimum[1]}."
        )

    if image_format not in ("PNG", "JPEG", "WEBP"):
        raise ValueError(
            f"Unsupported image format: {image_format}"
        )

    return {
        "width": width,
        "height": height,
        "format": image_format,
        "sha256": sha256_file(output_path),
    }


def provider_request(prompt, size):
    endpoint = env("VISUAL_PROVIDER_ENDPOINT")
    api_key = env("VISUAL_PROVIDER_API_KEY")
    model = env("VISUAL_PROVIDER_MODEL")

    if not endpoint or not api_key or not model:
        raise RuntimeError(
            "Provider not configured. Set "
            "VISUAL_PROVIDER_ENDPOINT, "
            "VISUAL_PROVIDER_API_KEY and "
            "VISUAL_PROVIDER_MODEL."
        )

    parsed = urlparse(endpoint)

    if parsed.scheme != "https":
        raise RuntimeError(
            "Provider endpoint must use HTTPS."
        )

    payload = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "n": 1,
        "response_format": "b64_json",
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # No automatic retries: an ambiguous response may already
    # have triggered a billable generation.
    response = requests.post(
        endpoint,
        headers=headers,
        json=payload,
        timeout=(20, 240),
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Provider HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    result = response.json()
    data = result.get("data")

    if not isinstance(data, list) or not data:
        raise RuntimeError(
            "Provider response has no data array."
        )

    first = data[0]

    if first.get("b64_json"):
        return base64.b64decode(first["b64_json"])

    if first.get("url"):
        image_response = requests.get(
            first["url"],
            timeout=(20, 120),
        )
        image_response.raise_for_status()
        return image_response.content

    raise RuntimeError(
        "Provider response has neither b64_json nor url."
    )


def load_manifest(path):
    data = json.loads(
        path.read_text(encoding="utf-8")
    )

    if not isinstance(data.get("assets"), list):
        raise ValueError("Manifest assets must be a list.")

    return data


def main():
    parser = argparse.ArgumentParser(
        description="Premium Visual Provider Adapter V1"
    )

    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-root")
    parser.add_argument("--generate", action="store_true")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument(
        "--asset-id",
        help="Generate only the selected asset ID.",
    )

    args = parser.parse_args()

    if args.limit < 1:
        print("ERROR: --limit must be at least 1.")
        return 2

    manifest_path = Path(args.manifest).resolve()

    if not manifest_path.is_file():
        print("ERROR: Manifest not found.")
        return 2

    try:
        manifest = load_manifest(manifest_path)
    except Exception as exc:
        print("ERROR: Manifest read failed:", exc)
        return 2

    topic_id = str(manifest.get("topic_id", "unknown"))
    draft_folder = manifest_path.parent.parent

    if args.output_root:
        output_base = Path(args.output_root).resolve()
    else:
        output_base = draft_folder / "visual_provider_runs"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_base / f"provider_run_{timestamp}"
    assets_dir = run_dir / "assets"

    selected = []

    for asset in manifest["assets"]:
        if not isinstance(asset, dict):
            continue

        asset_id = str(asset.get("asset_id", ""))

        if args.asset_id and asset_id != args.asset_id:
            continue

        selected.append(asset)

    if args.asset_id and not selected:
        print("ERROR: Requested asset ID not found.")
        return 2

    selected = selected[:args.limit]

    if not selected:
        print("ERROR: No assets selected.")
        return 2

    print("=" * 64)
    print("PREMIUM VISUAL PROVIDER ADAPTER V1")
    print("=" * 64)
    print("MODE:", "LIVE GENERATION" if args.generate else "DRY RUN")
    print("TOPIC:", topic_id)
    print("SELECTED ASSETS:", len(selected))
    print("SOURCE MANIFEST:", manifest_path)
    print("OUTPUT:", run_dir)

    plan = []

    for asset in selected:
        asset_id = str(asset.get("asset_id", "UNKNOWN"))
        size = expected_size(asset)
        width, height = parse_size(size)
        minimum = (
            (1080, 1920)
            if str(asset.get("format", "")).lower() == "vertical"
            else (1920, 1080)
        )

        plan.append({
            "asset_id": asset_id,
            "format": asset.get("format"),
            "requested_size": size,
            "requested_size_meets_minimum": (
                width >= minimum[0] and height >= minimum[1]
            ),
            "prompt": make_prompt(asset),
        })

    if not args.generate:
        print("\nDRY-RUN PLAN:")

        for item in plan:
            print(
                item["asset_id"],
                "|", item["requested_size"],
                "| minimum request valid:",
                item["requested_size_meets_minimum"],
            )

        print("\nNo API request was sent.")
        print("No source files were modified.")
        print("Run again with --generate to authorize API calls.")
        return 0

    endpoint = env("VISUAL_PROVIDER_ENDPOINT")
    model = env("VISUAL_PROVIDER_MODEL")
    terms_url = env("VISUAL_PROVIDER_TERMS_URL")
    terms_checked_at = env("VISUAL_PROVIDER_TERMS_CHECKED_AT")
    commercial_confirmed = (
        env("VISUAL_PROVIDER_COMMERCIAL_USE_CONFIRMED").lower()
        == "true"
    )

    if not endpoint or not model or not env("VISUAL_PROVIDER_API_KEY"):
        print("ERROR: Provider configuration is incomplete.")
        return 2

    assets_dir.mkdir(parents=True, exist_ok=True)

    results = []

    for asset, item in zip(selected, plan):
        asset_id = item["asset_id"]
        output_path = (
            assets_dir / f"{safe_id(asset_id)}.png"
        )

        result = {
            "asset_id": asset_id,
            "status": "HOLD",
            "output_path": str(output_path),
            "provider": urlparse(endpoint).netloc,
            "model": model,
            "requested_size": item["requested_size"],
            "prompt": item["prompt"],
            "commercial_use_confirmed_by_configuration": (
                commercial_confirmed
            ),
            "terms_url": terms_url,
            "terms_checked_at": terms_checked_at,
            "production_authorization": False,
            "upload_authorization": False,
        }

        try:
            if not item["requested_size_meets_minimum"]:
                raise ValueError(
                    "Requested size does not meet premium minimum."
                )

            image_data = provider_request(
                item["prompt"],
                item["requested_size"],
            )

            result["image"] = validate_image(
                image_data,
                asset,
                output_path,
            )

            if not terms_url or not terms_checked_at:
                result["status"] = "GENERATED_RIGHTS_HOLD"
                result["rights_reason"] = (
                    "Provider terms reference or checked date missing."
                )
            elif not commercial_confirmed:
                result["status"] = "GENERATED_RIGHTS_HOLD"
                result["rights_reason"] = (
                    "Commercial use has not been attested."
                )
            else:
                result["status"] = "GENERATED_NEEDS_SEPARATE_QA"
                result["rights_reason"] = (
                    "Configuration attestation recorded; "
                    "terms are not independently verified by this adapter."
                )

        except Exception as exc:
            result["status"] = "GENERATION_FAILED_OR_REJECTED"
            result["error"] = str(exc)

        results.append(result)

        print(
            asset_id,
            "=>",
            result["status"],
        )

    report = {
        "adapter_version": VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "topic_id": topic_id,
        "source_manifest": str(manifest_path),
        "source_manifest_sha256": sha256_file(manifest_path),
        "provider_host": urlparse(endpoint).netloc,
        "model": model,
        "results": results,
        "production_authorization": False,
        "render_authorization": False,
        "upload_authorization": False,
        "source_manifest_modified": False,
        "source_assets_modified": False,
        "notes": [
            "This adapter supports an OpenAI-compatible image generation endpoint.",
            "Provider-specific APIs may require a dedicated adapter.",
            "Terms configuration is an operator attestation, not independent legal verification.",
            "Generated assets require a separate quality and rights gate.",
            "Rejected or low-resolution outputs are not production approved.",
            "No automatic retries are performed to avoid duplicate billable requests.",
        ],
    }

    report_path = run_dir / "provider_generation_report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\nREPORT:", report_path)
    print("SOURCE MANIFEST MODIFIED: False")
    print("SOURCE ASSETS MODIFIED: False")
    print("PRODUCTION AUTHORIZATION: False")
    print("UPLOAD AUTHORIZATION: False")

    return 0


if __name__ == "__main__":
    sys.exit(main())
