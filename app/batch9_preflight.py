
import csv
import collections
import json
from pathlib import Path

BASE = Path("data/research/youtube_universe_v33")

FILES = [
    "latest_candidate_ranking_v33.csv",
    "latest_human_review_queue_v33.csv",
    "latest_human_review_audit_v33.csv",
    "latest_research_workbench_queue_v33.csv",
    "latest_final_audit_v33.csv",
    "latest_final_approved_v33.csv",
    "latest_final_pending_v33.csv",
    "research_review_decisions_v33.csv",
]

print("=" * 65)
print("BATCH 9 - CANONICAL DATA INTEGRITY CHECK")
print("=" * 65)

data = {}

for name in FILES:
    path = BASE / name

    if not path.exists():
        print("\nMISSING:", name)
        continue

    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    data[name] = rows

    ids = [
        row.get("video_id", "").strip()
        for row in rows
        if row.get("video_id", "").strip()
    ]

    duplicates = {
        key: count
        for key, count in collections.Counter(ids).items()
        if count > 1
    }

    print("\nFILE:", name)
    print("ROWS:", len(rows))
    print("UNIQUE IDS:", len(set(ids)))
    print("DUPLICATE IDS:", len(duplicates))

    for field in [
        "ranking_status",
        "decision",
        "human_decision",
        "topic_decision",
        "workspace_status",
        "research_decision",
        "final_audit_status",
        "production_approval",
        "recommended_next_action",
    ]:
        values = collections.Counter(
            (row.get(field) or "").strip()
            for row in rows
        )
        if values:
            print(field, dict(values))

print("\n--- ID CONSISTENCY ---")

ranking = data.get("latest_candidate_ranking_v33.csv", [])
base_ids = {
    row.get("video_id", "").strip()
    for row in ranking
    if row.get("video_id", "").strip()
}

print("RANKING UNIQUE IDS:", len(base_ids))

for name, rows in data.items():
    if name == "latest_final_audit_v33.csv":
        continue

    ids = {
        row.get("video_id", "").strip()
        for row in rows
        if row.get("video_id", "").strip()
    }

    if ids:
        print(
            name,
            "| missing from ranking:", len(ids - base_ids),
            "| ranking IDs missing here:", len(base_ids - ids),
        )

print("\n--- AUDIT REPORT ---")

report_path = BASE / "latest_final_audit_report_v33.json"

if report_path.exists():
    report = json.loads(report_path.read_text(encoding="utf-8"))

    keys = [
        "total_ranking_videos",
        "unique_video_ids",
        "human_decisions",
        "possible_duplicate_groups",
        "possible_duplicate_video_records",
        "automatic_final_approval",
        "production_approval",
        "database_modified",
        "api_calls",
    ]

    for key in keys:
        print(key, ":", report.get(key))

print("\nINSPECTION COMPLETE")
