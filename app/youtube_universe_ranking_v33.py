
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "research" / "youtube_universe_v33"
DB = OUT / "youtube_universe.db"

ENGINE = "V33.1-PROVISIONAL-CANDIDATE-RANKING"


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(
            f"Required input missing: {path.name}"
        )

    with path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as file:
        return list(csv.DictReader(file))


def numeric(value):
    if value is None or str(value).strip() == "":
        return None

    try:
        result = float(value)
        if result < 0:
            return None
        return result
    except (ValueError, TypeError):
        return None


def write_csv(path, rows, fields):
    with path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
            extrasaction="ignore"
        )
        writer.writeheader()

        for row in rows:
            writer.writerow(row)


def main():
    print("=" * 60)
    print("YOUTUBE UNIVERSE V3.3")
    print("FINAL CANDIDATE RANKING ENGINE")
    print("=" * 60)

    performance_rows = read_csv(
        OUT / "latest_master_performance_v33.csv"
    )

    format_rows = read_csv(
        OUT / "latest_format_master_v33.csv"
    )

    quality_rows = read_csv(
        OUT / "latest_content_quality_master_v33.csv"
    )

    performance = {
        row["video_id"]: row
        for row in performance_rows
        if row.get("video_id")
    }

    formats = {
        row["video_id"]: row
        for row in format_rows
        if row.get("video_id")
    }

    quality = {
        row["video_id"]: row
        for row in quality_rows
        if row.get("video_id")
    }

    ids = sorted(
        set(performance) | set(formats) | set(quality)
    )

    results = []

    for video_id in ids:
        p = performance.get(video_id, {})
        f = formats.get(video_id, {})
        q = quality.get(video_id, {})

        relevance = numeric(p.get("relevance_score"))
        performance_score = numeric(
            p.get("performance_score")
        )
        format_score = numeric(
            f.get("best_format_score")
        )

        available = {
            "relevance": relevance,
            "performance": performance_score,
            "format": format_score,
        }

        missing = [
            name for name, value in available.items()
            if value is None
        ]

        if missing:
            ranking_score = None
            ranking_status = "NOT_EVALUATED"
        else:
            ranking_score = round(
                relevance * 0.35
                + performance_score * 0.35
                + format_score * 0.30,
                2
            )

            if ranking_score >= 75:
                ranking_status = "TOP_CANDIDATE"
            elif ranking_score >= 55:
                ranking_status = "REVIEW_CANDIDATE"
            else:
                ranking_status = "LOW_PRIORITY"

        relevance_status = p.get(
            "relevance_status", "UNKNOWN"
        )

        performance_status = p.get(
            "performance_status", "UNKNOWN"
        )

        recommended_format = f.get(
            "recommended_format", "UNKNOWN"
        )

        quality_status = q.get(
            "content_quality_status", "NOT_AVAILABLE"
        )

        review_reasons = []

        if relevance_status == "HUMAN_REVIEW":
            review_reasons.append(
                "Relevance confidence requires human review"
            )

        if missing:
            review_reasons.append(
                "Missing ranking metrics: " + ", ".join(missing)
            )

        if quality_status in (
            "NOT_EVALUATED",
            "TRANSCRIPT_AVAILABLE_PENDING_REVIEW",
            "NOT_AVAILABLE",
        ):
            review_reasons.append(
                "Content quality verification pending"
            )

        if performance_status == "NOT_EVALUATED":
            review_reasons.append(
                "Performance metrics unavailable"
            )

        results.append({
            "video_id": video_id,
            "title": p.get("title") or f.get("title") or q.get("title"),
            "relevance_score": relevance,
            "performance_score": performance_score,
            "format_score": format_score,
            "ranking_score": ranking_score,
            "ranking_status": ranking_status,
            "relevance_status": relevance_status,
            "performance_status": performance_status,
            "recommended_format": recommended_format,
            "content_quality_status": quality_status,
            "content_quality_score": None,
            "quality_weight_included": False,
            "review_required": bool(review_reasons),
            "review_reasons": " | ".join(review_reasons),
        })

    results.sort(
        key=lambda row: (
            row["ranking_score"] is not None,
            row["ranking_score"] or -1
        ),
        reverse=True
    )

    for index, row in enumerate(results, start=1):
        row["rank"] = index

    top = [
        row for row in results
        if row["ranking_status"] == "TOP_CANDIDATE"
    ]

    review = [
        row for row in results
        if row["ranking_status"] == "REVIEW_CANDIDATE"
    ]

    low = [
        row for row in results
        if row["ranking_status"] == "LOW_PRIORITY"
    ]

    not_evaluated = [
        row for row in results
        if row["ranking_status"] == "NOT_EVALUATED"
    ]

    human_review = [
        row for row in results
        if row["review_required"]
    ]

    fields = [
        "rank",
        "video_id",
        "title",
        "relevance_score",
        "performance_score",
        "format_score",
        "ranking_score",
        "ranking_status",
        "relevance_status",
        "performance_status",
        "recommended_format",
        "content_quality_status",
        "content_quality_score",
        "quality_weight_included",
        "review_required",
        "review_reasons",
    ]

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    files = {
        "master": (
            f"candidate_ranking_master_v33_{timestamp}.csv",
            results
        ),
        "top": (
            f"top_candidates_v33_{timestamp}.csv",
            top
        ),
        "review": (
            f"ranking_review_candidates_v33_{timestamp}.csv",
            review
        ),
        "low": (
            f"low_priority_candidates_v33_{timestamp}.csv",
            low
        ),
        "not_evaluated": (
            f"ranking_not_evaluated_v33_{timestamp}.csv",
            not_evaluated
        ),
        "human_review": (
            f"ranking_human_review_v33_{timestamp}.csv",
            human_review
        ),
    }

    for _, (filename, rows) in files.items():
        write_csv(OUT / filename, rows, fields)

    latest = {
        "latest_candidate_ranking_v33.csv": results,
        "latest_top_candidates_v33.csv": top,
        "latest_ranking_review_v33.csv": review,
        "latest_low_priority_candidates_v33.csv": low,
        "latest_ranking_not_evaluated_v33.csv": not_evaluated,
        "latest_ranking_human_review_v33.csv": human_review,
    }

    for filename, rows in latest.items():
        write_csv(OUT / filename, rows, fields)

    connection = sqlite3.connect(
        f"file:{DB.as_posix()}?mode=ro",
        uri=True
    )

    try:
        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        database_count = connection.execute(
            "SELECT COUNT(*) FROM videos"
        ).fetchone()[0]
    finally:
        connection.close()

    report = {
        "engine": ENGINE,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "total_videos": len(results),
        "input_counts": {
            "performance": len(performance_rows),
            "format": len(format_rows),
            "quality": len(quality_rows),
        },
        "ranking_formula": {
            "relevance": 0.35,
            "performance": 0.35,
            "format": 0.30,
            "content_quality": "PENDING; excluded",
        },
        "thresholds": {
            "top_candidate": 75,
            "review_candidate": 55,
            "low_priority": "below 55",
        },
        "summary": {
            "top_candidates": len(top),
            "review_candidates": len(review),
            "low_priority": len(low),
            "not_evaluated": len(not_evaluated),
            "human_review_required": len(human_review),
        },
        "content_quality_scored": 0,
        "ranking_is_provisional": True,
        "database_integrity": integrity,
        "database_video_count": database_count,
        "database_modified": False,
        "api_calls": 0,
        "files": {
            key: filename
            for key, (filename, _) in files.items()
        },
        "limitations": [
            "Ranking is provisional until content quality is evaluated.",
            "Content quality has no weight in this ranking.",
            "Ranking score is a shortlist priority index, not a success probability.",
            "Human review flags are retained separately from ranking tiers.",
        ],
    }

    (OUT / "latest_candidate_ranking_report_v33.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print("\nRANKING SUMMARY")
    print("Total videos:", len(results))
    print("Top candidates:", len(top))
    print("Review candidates:", len(review))
    print("Low priority:", len(low))
    print("Not evaluated:", len(not_evaluated))
    print("Human review required:", len(human_review))

    print("\nINPUT COUNTS")
    print("Performance:", len(performance_rows))
    print("Format:", len(format_rows))
    print("Content quality:", len(quality_rows))

    print("\nOUTPUT VERIFICATION")

    for filename in list(latest) + [
        "latest_candidate_ranking_report_v33.json"
    ]:
        path = OUT / filename
        valid = path.exists() and path.stat().st_size > 0
        print("PASS" if valid else "FAIL", filename)

    print("\nDATABASE INTEGRITY:", integrity)
    print("DATABASE VIDEOS:", database_count)
    print("API CALLS: 0")
    print("DATABASE MODIFIED: NO")
    print("STATUS: COMPLETED")


if __name__ == "__main__":
    main()
