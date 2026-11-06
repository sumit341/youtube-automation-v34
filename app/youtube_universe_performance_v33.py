
import csv
import json
import math
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from youtube_universe_scoring_v33 import (
    load_videos,
    score_videos,
    write_csv,
)

ROOT = Path(__file__).resolve().parent.parent

DB_PATH = (
    ROOT / "data" / "research"
    / "youtube_universe_v33" / "youtube_universe.db"
)

OUTPUT_DIR = DB_PATH.parent

ENGINE_VERSION = "V33.2-FIXED-PERFORMANCE"


def valid_number(value):
    if value is None:
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(number) or number < 0:
        return None

    return number


def calculate_performance(views, views_per_day, likes, comments):
    views = valid_number(views)
    views_per_day = valid_number(views_per_day)
    likes = valid_number(likes)
    comments = valid_number(comments)

    required = {
        "views": views,
        "views_per_day": views_per_day,
        "likes": likes,
        "comments": comments,
    }

    missing = [
        name for name, value in required.items()
        if value is None
    ]

    if missing:
        return {
            "performance_score": None,
            "performance_status": "NOT_EVALUATED",
            "performance_confidence": "LOW",
            "velocity_score": None,
            "engagement_score": None,
            "total_views_score": None,
            "engagement_rate_calculated": None,
            "performance_missing_fields": missing,
        }

    if views == 0:
        engagement_rate = 0.0
    else:
        engagement_rate = (
            (likes + comments) / views
        ) * 100

    velocity_score = min(
        50.0,
        10.0 * math.log10(1.0 + views_per_day)
    )

    engagement_score = min(
        35.0,
        7.0 * engagement_rate
    )

    total_views_score = min(
        15.0,
        3.0 * math.log10(1.0 + views)
    )

    total_score = round(
        velocity_score
        + engagement_score
        + total_views_score,
        2
    )

    if total_score >= 80:
        status = "PERFORMANCE_OUTLIER"
    else:
        status = "NORMAL_PERFORMANCE"

    return {
        "performance_score": total_score,
        "performance_status": status,
        "performance_confidence": "MEDIUM",
        "velocity_score": round(velocity_score, 2),
        "engagement_score": round(engagement_score, 2),
        "total_views_score": round(total_views_score, 2),
        "engagement_rate_calculated": round(
            engagement_rate, 4
        ),
        "performance_missing_fields": [],
    }


def evaluate_video(video):
    result = dict(video)

    performance = calculate_performance(
        result.get("views"),
        result.get("views_per_day"),
        result.get("likes"),
        result.get("comments"),
    )

    result.update(performance)

    # Low-confidence relevance must be manually reviewed.
    if result.get("relevance_confidence") == "LOW":
        result["relevance_status"] = "HUMAN_REVIEW"
        result["relevance_review_reason"] = (
            "Low-confidence metadata relevance; "
            "human verification required."
        )
    else:
        result["relevance_review_reason"] = ""

    # Performance and relevance remain separate decisions.
    if result.get("performance_status") == "NOT_EVALUATED":
        result["final_review_flag"] = "HUMAN_REVIEW"
    elif result.get("relevance_status") == "HUMAN_REVIEW":
        result["final_review_flag"] = "HUMAN_REVIEW"
    else:
        result["final_review_flag"] = "SCORING_COMPLETE"

    return result


def main():
    print("=" * 60)
    print("YOUTUBE UNIVERSE V3.3")
    print("FIXED FORMULA PERFORMANCE ENGINE")
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
            raise RuntimeError(
                "Database integrity check failed"
            )

        videos = load_videos(connection)

    finally:
        connection.close()

    print("DATABASE INTEGRITY:", integrity)
    print("INPUT VIDEOS:", len(videos))

    # Recalculate relevance using the V3.3 engine.
    relevance_scored = score_videos(videos)

    # Add performance and confidence correction.
    scored = [
        evaluate_video(video)
        for video in relevance_scored
    ]

    outliers = [
        v for v in scored
        if v["performance_status"] == "PERFORMANCE_OUTLIER"
    ]

    not_evaluated = [
        v for v in scored
        if v["performance_status"] == "NOT_EVALUATED"
    ]

    human_review = [
        v for v in scored
        if v["final_review_flag"] == "HUMAN_REVIEW"
    ]

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    def output_file(name):
        return OUTPUT_DIR / f"{name}_{timestamp}.csv"

    master_path = output_file(
        "master_scored_v33"
    )

    outlier_path = output_file(
        "performance_outliers_v33"
    )

    review_path = output_file(
        "human_review_v33"
    )

    not_evaluated_path = output_file(
        "performance_not_evaluated_v33"
    )

    write_csv(master_path, scored)
    write_csv(outlier_path, outliers)
    write_csv(review_path, human_review)
    write_csv(not_evaluated_path, not_evaluated)

    relevance_counts = Counter(
        v["relevance_status"] for v in scored
    )

    performance_counts = Counter(
        v["performance_status"] for v in scored
    )

    report = {
        "engine": "YouTube Universe Scanner V3.3",
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),

        "database_read_only": True,
        "api_calls": 0,
        "database_integrity": integrity,

        "total_videos": len(scored),

        "performance_summary": {
            "outliers": len(outliers),
            "not_evaluated": len(not_evaluated),
            "normal": performance_counts.get(
                "NORMAL_PERFORMANCE", 0
            )
        },

        "relevance_summary": dict(relevance_counts),

        "human_review_count": len(human_review),

        "performance_formula": {
            "velocity": "min(50, 10*log10(1+views_per_day))",
            "engagement": "min(35, 7*engagement_rate_percent)",
            "total_views": "min(15, 3*log10(1+views))",
            "engagement_rate": (
                "(likes+comments)/views*100"
            )
        },

        "limitations": [
            "Views per day is an existing metric proxy, not true growth velocity.",
            "Public metrics do not reveal audience retention.",
            "Performance score is not viral probability.",
            "Fixed formula is not cohort-normalized.",
            "Missing required metrics are not treated as zero.",
            "Low-confidence relevance is routed to HUMAN_REVIEW.",
            "Metadata relevance is not transcript verification."
        ],

        "files": {
            "master": master_path.name,
            "outliers": outlier_path.name,
            "human_review": review_path.name,
            "not_evaluated": not_evaluated_path.name
        }
    }

    report_path = (
        OUTPUT_DIR
        / f"latest_performance_report_v33.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    latest_files = {
        "latest_master_performance_v33.csv": master_path,
        "latest_performance_outliers_v33.csv": outlier_path,
        "latest_human_review_v33.csv": review_path,
        "latest_performance_not_evaluated_v33.csv": (
            not_evaluated_path
        )
    }

    for latest_name, source in latest_files.items():
        (OUTPUT_DIR / latest_name).write_bytes(
            source.read_bytes()
        )

    print("\nPERFORMANCE SUMMARY")
    print("Total:", len(scored))
    print("Outliers:", len(outliers))
    print("Normal:", performance_counts.get(
        "NORMAL_PERFORMANCE", 0
    ))
    print("Not evaluated:", len(not_evaluated))

    print("\nRELEVANCE SUMMARY")
    for status, count in relevance_counts.items():
        print(status, ":", count)

    print("\nHUMAN REVIEW:", len(human_review))

    print("\nOUTPUT VERIFICATION")
    for name in list(latest_files) + [
        "latest_performance_report_v33.json"
    ]:
        path = OUTPUT_DIR / name
        print(
            "PASS" if path.exists() and path.stat().st_size > 0
            else "FAIL",
            name
        )

    print("\nAPI CALLS: 0")
    print("DATABASE MODIFIED: NO")
    print("STATUS: COMPLETED")


if __name__ == "__main__":
    main()
