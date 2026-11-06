
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OUTPUT_DIR = (
    ROOT / "data" / "research" / "youtube_universe_v33"
)

DB_PATH = OUTPUT_DIR / "youtube_universe.db"

ENGINE_VERSION = "V33.1-CONTENT-QUALITY-READINESS"

TRANSCRIPT_NAMES = {
    "transcript",
    "transcript_text",
    "full_transcript",
    "transcript_content",
    "video_transcript",
    "captions",
    "caption_text",
    "subtitle_text",
    "subtitles",
}


def write_csv(path, rows, fieldnames):
    with path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


def main():
    print("=" * 60)
    print("YOUTUBE UNIVERSE V3.3")
    print("CONTENT QUALITY ENGINE")
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

        table_names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' ORDER BY name"
            )
        ]

        if "videos" not in table_names:
            raise RuntimeError(
                "Required videos table not found"
            )

        columns = [
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(videos)"
            )
        ]

        records = connection.execute(
            "SELECT * FROM videos"
        ).fetchall()

        column_names = [
            item[0]
            for item in connection.execute(
                "SELECT * FROM videos LIMIT 0"
            ).description
        ]

    finally:
        connection.close()

    transcript_columns = [
        column for column in column_names
        if column.lower() in TRANSCRIPT_NAMES
        or (
            any(term in column.lower()
                for term in ["transcript", "caption", "subtitle"])
            and not any(term in column.lower()
                        for term in ["status", "id", "url"])
        )
    ]

    results = []
    transcript_missing = []
    transcript_available = []

    for record in records:
        video = dict(zip(column_names, record))

        video_id = video.get("video_id", "")
        title = video.get("title", "")

        transcript_text = ""

        for column in transcript_columns:
            value = video.get(column)

            if isinstance(value, str) and value.strip():
                transcript_text = value.strip()
                break

        word_count = (
            len(transcript_text.split())
            if transcript_text else 0
        )

        if not transcript_text:
            status = "NOT_EVALUATED"
            reason = (
                "Complete transcript not available "
                "in the videos table."
            )
            transcript_missing.append({
                "video_id": video_id,
                "title": title,
                "content_quality_status": status,
                "review_reason": reason,
            })
        else:
            status = "TRANSCRIPT_AVAILABLE_PENDING_REVIEW"
            reason = (
                "Transcript found. Human or validated "
                "content analysis is still required."
            )
            transcript_available.append({
                "video_id": video_id,
                "title": title,
                "transcript_word_count": word_count,
                "content_quality_status": status,
                "review_reason": reason,
            })

        results.append({
            "video_id": video_id,
            "title": title,
            "transcript_available": bool(transcript_text),
            "transcript_word_count": word_count,
            "hook_score": None,
            "storytelling_score": None,
            "psychological_depth_score": None,
            "originality_score": None,
            "practical_value_score": None,
            "clarity_score": None,
            "content_quality_score": None,
            "content_quality_status": status,
            "review_reason": reason,
        })

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    fields = [
        "video_id",
        "title",
        "transcript_available",
        "transcript_word_count",
        "hook_score",
        "storytelling_score",
        "psychological_depth_score",
        "originality_score",
        "practical_value_score",
        "clarity_score",
        "content_quality_score",
        "content_quality_status",
        "review_reason",
    ]

    master_path = OUTPUT_DIR / (
        f"content_quality_master_v33_{timestamp}.csv"
    )

    missing_path = OUTPUT_DIR / (
        f"content_quality_not_evaluated_v33_{timestamp}.csv"
    )

    available_path = OUTPUT_DIR / (
        f"content_quality_transcripts_available_v33_{timestamp}.csv"
    )

    write_csv(master_path, results, fields)

    write_csv(
        missing_path,
        transcript_missing,
        fields
    )

    write_csv(
        available_path,
        transcript_available,
        [
            "video_id",
            "title",
            "transcript_word_count",
            "content_quality_status",
            "review_reason",
        ]
    )

    latest_files = {
        "latest_content_quality_master_v33.csv": master_path,
        "latest_content_quality_not_evaluated_v33.csv": missing_path,
        "latest_content_quality_transcripts_available_v33.csv": (
            available_path
        ),
    }

    for latest_name, source in latest_files.items():
        (OUTPUT_DIR / latest_name).write_bytes(
            source.read_bytes()
        )

    report = {
        "engine": ENGINE_VERSION,
        "generated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "total_videos": len(results),
        "database_integrity": integrity,
        "database_read_only": True,
        "api_calls": 0,
        "transcript_columns_detected": transcript_columns,
        "transcript_available": len(transcript_available),
        "transcript_missing": len(transcript_missing),
        "content_quality_scored": 0,
        "content_quality_not_evaluated": len(
            transcript_missing
        ),
        "transcript_available_pending_review": len(
            transcript_available
        ),
        "quality_dimensions": {
            "hook": 20,
            "storytelling": 20,
            "psychological_depth": 20,
            "originality": 15,
            "practical_value": 15,
            "clarity": 10,
        },
        "scoring_policy": (
            "No content quality score is assigned without "
            "transcript-based validated evaluation."
        ),
        "limitations": [
            "A title or description is not a full transcript.",
            "Transcript presence alone does not prove quality.",
            "Originality requires comparison against other content.",
            "No AI model or external API is called by this engine.",
            "All quality scores remain blank until valid evaluation."
        ],
        "files": {
            "master": master_path.name,
            "not_evaluated": missing_path.name,
            "transcripts_available": available_path.name,
        }
    }

    report_path = (
        OUTPUT_DIR / "latest_content_quality_report_v33.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    print("\nCONTENT QUALITY SUMMARY")
    print("Total videos:", len(results))
    print("Transcript columns:", transcript_columns)
    print("Transcripts available:", len(transcript_available))
    print("Transcripts missing:", len(transcript_missing))
    print("Quality scores assigned: 0")
    print("Quality not evaluated:", len(transcript_missing))

    print("\nOUTPUT VERIFICATION")

    for name in list(latest_files) + [
        "latest_content_quality_report_v33.json"
    ]:
        path = OUTPUT_DIR / name
        valid = path.exists() and path.stat().st_size > 0
        print("PASS" if valid else "FAIL", name)

    print("\nDATABASE INTEGRITY:", integrity)
    print("API CALLS: 0")
    print("DATABASE MODIFIED: NO")
    print("STATUS: COMPLETED")


if __name__ == "__main__":
    main()
