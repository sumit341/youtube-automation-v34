
import csv
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from youtube_universe_scoring_v33 import load_videos, score_videos


ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "data" / "research" / "youtube_universe_v33"
DB_PATH = OUTPUT_DIR / "youtube_universe.db"
PERFORMANCE_FILE = OUTPUT_DIR / "latest_master_performance_v33.csv"

ENGINE_VERSION = "V33.3-FORMAT-SUITABILITY"

FORMATS = {
    "SHORTS_CANDIDATE": {
        "minimum": 0,
        "maximum": 180,
        "ideal_min": 20,
        "ideal_max": 90,
    },
    "SHORT_FORM": {
        "minimum": 60,
        "maximum": 300,
        "ideal_min": 90,
        "ideal_max": 240,
    },
    "MEDIUM_FORM": {
        "minimum": 300,
        "maximum": 900,
        "ideal_min": 360,
        "ideal_max": 720,
    },
    "DOCUMENTARY": {
        "minimum": 480,
        "maximum": 3600,
        "ideal_min": 900,
        "ideal_max": 2400,
    },
    "VERY_LONG_FORM": {
        "minimum": 3600,
        "maximum": None,
        "ideal_min": 3600,
        "ideal_max": None,
    },
}


def number(value):
    if value is None or value == "":
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def duration_score(seconds, config):
    if seconds is None:
        return None

    low = config["minimum"]
    high = config["maximum"]
    ideal_low = config["ideal_min"]
    ideal_high = config["ideal_max"]

    if high is None:
        if seconds < low:
            return max(0.0, 100.0 - ((low - seconds) / low * 100))
        return 100.0

    if ideal_low <= seconds <= ideal_high:
        return 100.0

    if low <= seconds < ideal_low:
        span = max(ideal_low - low, 1)
        return round(70 + 30 * (seconds - low) / span, 2)

    if ideal_high < seconds <= high:
        span = max(high - ideal_high, 1)
        return round(100 - 30 * (seconds - ideal_high) / span, 2)

    if seconds < low:
        return max(0.0, round(70 * seconds / max(low, 1), 2))

    return 0.0


def topic_score(format_name, title, description, category):
    text = f"{title or ''} {description or ''}".lower()
    category = (category or "").lower()

    rules = {
        "SHORTS_CANDIDATE": [
            "psychology", "secret", "mistake", "habit", "brain",
            "truth", "why", "fear", "money", "mind", "behavior",
            "behaviour", "social", "success", "confidence"
        ],
        "SHORT_FORM": [
            "explained", "why", "how", "psychology", "money",
            "habit", "behavior", "behaviour", "lesson", "tips",
            "mistakes", "comparison"
        ],
        "MEDIUM_FORM": [
            "explained", "why", "how", "reasons", "science",
            "psychology", "money", "behavior", "behaviour",
            "strategy", "decision", "success"
        ],
        "DOCUMENTARY": [
            "documentary", "story", "history", "case study",
            "rise", "fall", "system", "society", "power",
            "psychology", "economy", "investigation", "journey"
        ],
        "VERY_LONG_FORM": [
            "full", "complete", "compilation", "audiobook",
            "full story", "deep dive", "long", "entire",
            "documentary", "extended"
        ],
    }

    keywords = rules[format_name]
    matches = sum(1 for word in keywords if word in text)

    if matches == 0:
        score = 45.0
    elif matches == 1:
        score = 65.0
    elif matches == 2:
        score = 78.0
    elif matches == 3:
        score = 88.0
    else:
        score = 95.0

    if category:
        if any(term in category for term in [
            "psychology", "money", "success", "power"
        ]):
            score = min(100.0, score + 5.0)

    return round(score, 2)


def load_performance():
    if not PERFORMANCE_FILE.exists():
        return {}

    records = {}

    with PERFORMANCE_FILE.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        for row in csv.DictReader(file):
            video_id = row.get("video_id")
            if video_id:
                records[video_id] = row

    return records


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields = list(dict.fromkeys(
        key for row in rows for key in row.keys()
    ))

    with path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(
            file, fieldnames=fields, extrasaction="ignore"
        )
        writer.writeheader()

        for row in rows:
            clean = {}
            for key, value in row.items():
                if isinstance(value, (dict, list)):
                    clean[key] = json.dumps(
                        value, ensure_ascii=False
                    )
                else:
                    clean[key] = value
            writer.writerow(clean)


def main():
    print("=" * 60)
    print("YOUTUBE UNIVERSE V3.3")
    print("FORMAT SUITABILITY ENGINE")
    print("=" * 60)

    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)

    connection = sqlite3.connect(
        f"file:{DB_PATH.as_posix()}?mode=ro",
        uri=True
    )

    try:
        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if integrity != "ok":
            raise RuntimeError("Database integrity check failed")

        raw_videos = load_videos(connection)
    finally:
        connection.close()

    videos = score_videos(raw_videos)
    performance = load_performance()

    print("DATABASE INTEGRITY:", integrity)
    print("INPUT VIDEOS:", len(videos))
    print("PERFORMANCE DATA:", len(performance))

    all_results = []
    format_results = {name: [] for name in FORMATS}

    for video in videos:
        video_id = video.get("video_id")
        title = video.get("title", "")
        description = video.get("description", "")
        category = video.get("category_matches", "")

        if isinstance(category, list):
            category_text = " ".join(str(x) for x in category)
        else:
            category_text = str(category or "")

        seconds = number(video.get("duration_seconds"))

        performance_row = performance.get(video_id, {})
        performance_score = number(
            performance_row.get("performance_score")
        )

        row = dict(video)
        row["duration_seconds"] = seconds
        row["youtube_shorts_eligibility"] = "NOT_VERIFIED"

        format_scores = {}

        for format_name, config in FORMATS.items():
            d_score = duration_score(seconds, config)
            t_score = topic_score(
                format_name, title, description, category_text
            )

            if d_score is None or performance_score is None:
                final_score = None
                status = "NOT_EVALUATED"
            else:
                p_score = max(
                    0.0, min(100.0, performance_score)
                )

                final_score = round(
                    d_score * 0.60
                    + t_score * 0.25
                    + p_score * 0.15,
                    2
                )

                status = (
                    "FORMAT_CANDIDATE"
                    if final_score >= 75
                    else "NOT_SHORTLISTED"
                )

            format_record = {
                "video_id": video_id,
                "title": title,
                "duration_seconds": seconds,
                "format": format_name,
                "duration_score": d_score,
                "topic_score": t_score,
                "performance_score": performance_score,
                "format_suitability_score": final_score,
                "format_status": status,
                "youtube_shorts_eligibility": "NOT_VERIFIED",
            }

            format_results[format_name].append(format_record)
            format_scores[format_name] = final_score

        evaluated = {
            name: score
            for name, score in format_scores.items()
            if score is not None
        }

        if evaluated:
            best_format = max(
                evaluated, key=evaluated.get
            )
            best_score = evaluated[best_format]
        else:
            best_format = "NOT_EVALUATED"
            best_score = None

        row["format_scores"] = format_scores
        row["recommended_format"] = best_format
        row["best_format_score"] = best_score

        row["format_review_flag"] = (
            "HUMAN_REVIEW"
            if best_score is None
            else "FORMAT_EVALUATED"
        )

        all_results.append(row)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    master_path = OUTPUT_DIR / (
        f"format_master_v33_{timestamp}.csv"
    )
    write_csv(master_path, all_results)

    summary = {}

    for format_name, records in format_results.items():
        candidates = [
            r for r in records
            if r["format_status"] == "FORMAT_CANDIDATE"
        ]

        path = OUTPUT_DIR / (
            f"{format_name.lower()}_v33_{timestamp}.csv"
        )
        write_csv(path, candidates)

        summary[format_name] = {
            "evaluated": sum(
                r["format_status"] != "NOT_EVALUATED"
                for r in records
            ),
            "candidates": len(candidates),
            "not_shortlisted": sum(
                r["format_status"] == "NOT_SHORTLISTED"
                for r in records
            ),
            "not_evaluated": sum(
                r["format_status"] == "NOT_EVALUATED"
                for r in records
            ),
            "file": path.name,
        }

    review = [
        row for row in all_results
        if row["format_review_flag"] == "HUMAN_REVIEW"
    ]

    review_path = OUTPUT_DIR / (
        f"format_human_review_v33_{timestamp}.csv"
    )
    write_csv(review_path, review)

    report = {
        "engine": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_videos": len(all_results),
        "database_integrity": integrity,
        "database_read_only": True,
        "api_calls": 0,
        "formula": {
            "duration": 0.60,
            "topic": 0.25,
            "performance": 0.15,
            "candidate_threshold": 75,
        },
        "format_summary": summary,
        "human_review_count": len(review),
        "shorts_eligibility": (
            "NOT_VERIFIED: aspect ratio and current eligibility "
            "requirements are not present in this dataset."
        ),
        "limitations": [
            "Topic suitability uses title and description metadata.",
            "Duration bands are editorial heuristics, not platform rules.",
            "Performance score is based on public metrics.",
            "A candidate label is not a final production decision.",
            "Official Shorts eligibility is not verified.",
        ],
        "master_file": master_path.name,
        "human_review_file": review_path.name,
    }

    report_path = OUTPUT_DIR / "latest_format_report_v33.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    latest_master = OUTPUT_DIR / "latest_format_master_v33.csv"
    latest_master.write_bytes(master_path.read_bytes())

    latest_review = OUTPUT_DIR / "latest_format_human_review_v33.csv"
    latest_review.write_bytes(review_path.read_bytes())

    print("\nFORMAT SUMMARY")
    for name, data in summary.items():
        print(
            name,
            "| Candidates:", data["candidates"],
            "| Not shortlisted:", data["not_shortlisted"],
            "| Not evaluated:", data["not_evaluated"]
        )

    print("\nHUMAN REVIEW:", len(review))
    print("\nOUTPUT VERIFICATION")

    required_files = [
        latest_master,
        latest_review,
        report_path,
    ]

    required_files.extend(
        OUTPUT_DIR / data["file"]
        for data in summary.values()
    )

    for path in required_files:
        ok = path.exists() and path.stat().st_size > 0
        print("PASS" if ok else "FAIL", path.name)

    print("\nAPI CALLS: 0")
    print("DATABASE MODIFIED: NO")
    print("STATUS: COMPLETED")


if __name__ == "__main__":
    main()
