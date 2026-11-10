from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

VERSION = "1.0.0"
VOICE = "hi-IN-MadhurNeural"


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def clean_markdown(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[.*?\]\(.*?\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*_]{3,}\s*$", " ", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*\d+[.)]\s+", "", text, flags=re.M)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)
    text = re.sub(r"[*_`~]", "", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def word_count(text):
    return len(re.findall(r"\b[\w'-]+\b", text, flags=re.UNICODE))


def get_duration(path):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe not found. Install FFmpeg and add it to PATH.")

    result = subprocess.run(
        [
            ffprobe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json", str(path)
        ],
        capture_output=True, text=True, check=True
    )
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


async def generate_audio(text, output_path):
    import edge_tts

    communicate = edge_tts.Communicate(
        text=text,
        voice=VOICE,
        rate="+0%",
        volume="+0%",
        pitch="+0Hz"
    )
    await communicate.save(str(output_path))


def self_test():
    sample = clean_markdown("# Heading\n\n**Hello** world.\n\n- One\n- Two")
    assert "Heading" in sample
    assert "Hello" in sample
    assert word_count("one two three") == 3
    assert len(sha256_file(__file__)) == 64
    print("[PASS] Voiceover engine self-tests: 3 scenarios")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-id", default="E1irX9cDX8U")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    root = Path(__file__).resolve().parents[1]

    integrated_reports = list(
        (root / "reports" / "phase2_integrated_runs").glob(
            "*/phase2_integrated_report.json"
        )
    )
    if not integrated_reports:
        raise RuntimeError("Integrated gate report not found.")

    integrated_path = max(integrated_reports, key=lambda p: p.stat().st_mtime)
    integrated = read_json(integrated_path)

    if integrated.get("topic_id") != args.topic_id:
        raise RuntimeError("Integrated report topic ID mismatch.")

    if integrated.get("status") != "INTEGRATED_GATES_PASS_RENDER_PENDING":
        raise RuntimeError("Integrated gates have not passed. Voiceover held.")

    if integrated.get("production_approved") is not False:
        raise RuntimeError("Unexpected production approval state.")

    script_report_path = Path(integrated["script_report"])
    script_report = read_json(script_report_path)
    draft_dir = Path(script_report["draft_directory"]).resolve()

    if script_report.get("topic_id") != args.topic_id:
        raise RuntimeError("Script report topic mismatch.")

    scripts = {
        "long": draft_dir / "long_video_script_draft.md",
        "short": draft_dir / "short_video_script_draft.md"
    }

    for label, path in scripts.items():
        if not path.is_file():
            raise FileNotFoundError(f"{label} narration not found: {path}")

    texts = {}
    for label, path in scripts.items():
        raw = path.read_text(encoding="utf-8-sig")
        cleaned = clean_markdown(raw)
        count = word_count(cleaned)
        if count < 30:
            raise RuntimeError(f"{label} narration is unexpectedly short: {count} words")
        if len(cleaned) > 14000:
            raise RuntimeError(f"{label} narration exceeds safe single-request limit.")
        texts[label] = {
            "text": cleaned,
            "words": count,
            "source": path,
            "source_sha256": sha256_file(path)
        }

    try:
        import edge_tts  # noqa: F401
    except Exception as exc:
        raise RuntimeError(f"edge-tts import failed: {exc}")

    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe unavailable. FFmpeg installation/PATH required.")

    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    out_dir = draft_dir / f"voiceover_v1_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=False)

    audio_results = {}
    for label, item in texts.items():
        output = out_dir / f"{label}_voiceover.mp3"
        print(f"[GENERATING] {label}: {item['words']} words")
        asyncio.run(generate_audio(item["text"], output))

        if not output.is_file() or output.stat().st_size < 1000:
            raise RuntimeError(f"{label} audio file missing or unexpectedly small.")

        duration = get_duration(output)
        if duration <= 1:
            raise RuntimeError(f"{label} audio duration invalid.")

        expected_min, expected_max = (
            (240, 900) if label == "long" else (20, 90)
        )
        duration_status = "PASS" if expected_min <= duration <= expected_max else "HOLD"

        audio_results[label] = {
            "file": str(output),
            "sha256": sha256_file(output),
            "bytes": output.stat().st_size,
            "duration_seconds": round(duration, 2),
            "word_count": item["words"],
            "estimated_wpm": round(item["words"] / (duration / 60), 1),
            "source_script": str(item["source"]),
            "source_script_sha256": item["source_sha256"],
            "voice": VOICE,
            "engine": "Microsoft Edge TTS",
            "technical_status": "PASS",
            "duration_status": duration_status
        }

    all_pass = all(
        item["technical_status"] == "PASS"
        and item["duration_status"] == "PASS"
        for item in audio_results.values()
    )

    report = {
        "version": VERSION,
        "topic_id": args.topic_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "integrated_gate_report": str(integrated_path),
        "voice": VOICE,
        "engine": "Microsoft Edge TTS",
        "status": "VOICEOVER_TECHNICAL_PASS" if all_pass else "VOICEOVER_HOLD",
        "audio": audio_results,
        "capabilities": {
            "audio_file_integrity": True,
            "audio_duration_probe": True,
            "source_script_hash_traceability": True,
            "pronunciation_semantic_verification": False,
            "human_audio_review_required": False
        },
        "limitations": [
            "Technical audio checks do not prove correct pronunciation of every Roman Hinglish word.",
            "Edge TTS requires an internet connection and its service availability.",
            "This is a free fallback voice, not Sarvam Bulbul Shubh.",
            "No rendering, production approval, or upload authorization is granted."
        ],
        "production_approved": False,
        "render_authorized": False,
        "upload_authorized": False,
        "public_upload_authorized": False
    }

    report_path = out_dir / "voiceover_manifest.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print("=" * 60)
    print("AUTOMATED VOICEOVER ENGINE", VERSION)
    print("TOPIC:", args.topic_id)
    for label, item in audio_results.items():
        print(
            f"{label.upper()}: {item['duration_seconds']} sec | "
            f"{item['word_count']} words | {item['duration_status']}"
        )
        print("FILE:", item["file"])
    print("STATUS:", report["status"])
    print("VOICE:", VOICE)
    print("PRODUCTION APPROVED: False")
    print("RENDER AUTHORIZED: False")
    print("UPLOAD AUTHORIZED: False")
    print("MANIFEST:", report_path)
    print("=" * 60)

    return 0 if all_pass else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print("[HOLD]", str(exc), file=sys.stderr)
        sys.exit(2)
