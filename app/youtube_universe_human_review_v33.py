
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "data" / "research" / "youtube_universe_v33"

RANKING_FILE = OUTPUT_DIR / "latest_candidate_ranking_v33.csv"
DECISIONS_FILE = OUTPUT_DIR / "human_review_decisions_v33.csv"

ENGINE_VERSION = "V33.1-HUMAN-REVIEW"
VALID_DECISIONS = {"PENDING", "APPROVE", "REJECT", "HOLD"}

DECISION_FIELDS = [
    "video_id",
    "title",
    "decision",
    "reviewer_notes",
    "decision_reason",
    "decided_at",
]


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path, rows, fieldnames):
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def clean_decision(value):
    value = (value or "PENDING").strip().upper()
    if value not in VALID_DECISIONS:
        raise ValueError(
            f"Invalid decision '{value}'. "
            "Use PENDING, APPROVE, REJECT, or HOLD."
        )
    return value


def main():
    print("=" * 60)
    print("YOUTUBE UNIVERSE V3.3")
    print("HUMAN REVIEW ENGINE")
    print("=" * 60)

    if not RANKING_FILE.exists():
        raise FileNotFoundError(
            f"Ranking file not found: {RANKING_FILE}"
        )

    ranking_rows = read_csv(RANKING_FILE)

    if not ranking_rows:
        raise RuntimeError("Ranking file has no video records.")

    if "video_id" not in ranking_rows[0]:
        raise RuntimeError(
            "Ranking CSV must contain a video_id column."
        )

    # Read previously saved decisions without overwriting them.
    existing = {}

    if DECISIONS_FILE.exists():
        for item in read_csv(DECISIONS_FILE):
            video_id = (item.get("video_id") or "").strip()
            if not video_id:
                continue

            decision = clean_decision(item.get("decision"))

            existing[video_id] = {
                "video_id": video_id,
                "title": item.get("title", ""),
                "decision": decision,
                "reviewer_notes": item.get("reviewer_notes", ""),
                "decision_reason": item.get("decision_reason", ""),
                "decided_at": item.get("decided_at", ""),
            }

    now = datetime.now(timezone.utc).isoformat()
    decision_rows = []
    queue_rows = []

    for video in ranking_rows:
        video_id = (video.get("video_id") or "").strip()

        if not video_id:
            continue

        saved = existing.get(video_id)

        if saved:
            decision_record = dict(saved)
            # Keep title current, but preserve the reviewer's decision.
            decision_record["title"] = video.get("title", saved["title"])
        else:
            decision_record = {
                "video_id": video_id,
                "title": video.get("title", ""),
                "decision": "PENDING",
                "reviewer_notes": "",
                "decision_reason": "",
                "decided_at": "",
            }

        decision = clean_decision(decision_record["decision"])
        decision_record["decision"] = decision

        if decision == "PENDING":
            decision_record["decided_at"] = ""
        elif not decision_record["decided_at"]:
            decision_record["decided_at"] = now

        decision_rows.append(decision_record)

        combined = dict(video)
        combined["review_decision"] = decision
        combined["reviewer_notes"] = decision_record["reviewer_notes"]
        combined["decision_reason"] = decision_record["decision_reason"]
        combined["review_decided_at"] = decision_record["decided_at"]
        combined["review_instruction"] = (
            "Manual decision required"
            if decision == "PENDING"
            else "Human decision recorded"
        )
        queue_rows.append(combined)

    # Persist the decision register. This is the editable source of truth.
    write_csv(DECISIONS_FILE, decision_rows, DECISION_FIELDS)

    queue_fields = list(dict.fromkeys(
        key for row in queue_rows for key in row.keys()
    ))

    write_csv(
        OUTPUT_DIR / "latest_human_review_queue_v33.csv",
        queue_rows,
        queue_fields,
    )

    groups = {
        "APPROVE": [],
        "REJECT": [],
        "HOLD": [],
        "PENDING": [],
    }

    for row in queue_rows:
        groups[row["review_decision"]].append(row)

    output_names = {
        "APPROVE": "latest_approved_topics_v33.csv",
        "REJECT": "latest_rejected_topics_v33.csv",
        "HOLD": "latest_hold_topics_v33.csv",
        "PENDING": "latest_pending_review_v33.csv",
    }

    for decision, filename in output_names.items():
        write_csv(
            OUTPUT_DIR / filename,
            groups[decision],
            queue_fields,
        )

    # Audit records summarize the current decision state.
    audit_rows = []
    for item in decision_rows:
        audit_rows.append({
            "video_id": item["video_id"],
            "title": item["title"],
            "decision": item["decision"],
            "reviewer_notes": item["reviewer_notes"],
            "decision_reason": item["decision_reason"],
            "decided_at": item["decided_at"],
        })

    write_csv(
        OUTPUT_DIR / "latest_human_review_audit_v33.csv",
        audit_rows,
        DECISION_FIELDS,
    )

    summary = {
        "engine": ENGINE_VERSION,
        "generated_at": now,
        "total_videos": len(queue_rows),
        "decisions": {
            decision: len(items)
            for decision, items in groups.items()
        },
        "ranking_is_provisional": True,
        "automatic_approval": False,
        "decision_source": DECISIONS_FILE.name,
        "outputs": [
            "latest_human_review_queue_v33.csv",
            "latest_approved_topics_v33.csv",
            "latest_rejected_topics_v33.csv",
            "latest_hold_topics_v33.csv",
            "latest_pending_review_v33.csv",
            "latest_human_review_audit_v33.csv",
        ],
        "rules": [
            "All new videos begin as PENDING.",
            "Only an explicit APPROVE decision enters the approved export.",
            "REJECT and HOLD are never exported as approved.",
            "Existing decisions and reviewer notes are preserved.",
            "Ranking remains provisional until content quality is evaluated.",
            "This engine does not modify the research database.",
            "No external API calls are made.",
        ],
    }

    report_path = OUTPUT_DIR / "latest_human_review_report_v33.json"
    report_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\nREVIEW SUMMARY")
    print("Total videos:", len(queue_rows))
    for decision in ("APPROVE", "REJECT", "HOLD", "PENDING"):
        print(f"{decision}: {len(groups[decision])}")

    print("\nOUTPUT VERIFICATION")
    required = [
        DECISIONS_FILE,
        OUTPUT_DIR / "latest_human_review_queue_v33.csv",
        OUTPUT_DIR / "latest_approved_topics_v33.csv",
        OUTPUT_DIR / "latest_rejected_topics_v33.csv",
        OUTPUT_DIR / "latest_hold_topics_v33.csv",
        OUTPUT_DIR / "latest_pending_review_v33.csv",
        OUTPUT_DIR / "latest_human_review_audit_v33.csv",
        report_path,
    ]

    for path in required:
        valid = path.exists() and path.stat().st_size > 0
        print("PASS" if valid else "FAIL", path.name)

    print("\nAUTOMATIC APPROVAL: NO")
    print("DATABASE MODIFIED: NO")
    print("API CALLS: 0")
    print("STATUS: COMPLETED")


if __name__ == "__main__":
    main()
