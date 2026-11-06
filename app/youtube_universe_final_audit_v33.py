
import csv
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "research" / "youtube_universe_v33"

INPUTS = {
    "ranking": DATA / "latest_candidate_ranking_v33.csv",
    "performance": DATA / "latest_master_performance_v33.csv",
    "format": DATA / "latest_format_master_v33.csv",
    "quality": DATA / "latest_content_quality_master_v33.csv",
    "relevance": DATA / "latest_master_scored_videos_v33.csv",
}

DECISIONS_FILE = DATA / "human_review_decisions_v33.csv"

OUTPUTS = {
    "audit": DATA / "latest_final_audit_v33.csv",
    "approved": DATA / "latest_final_approved_v33.csv",
    "hold": DATA / "latest_final_hold_v33.csv",
    "rejected": DATA / "latest_final_rejected_v33.csv",
    "duplicates": DATA / "latest_duplicate_groups_v33.csv",
    "priority": DATA / "latest_research_priority_v33.csv",
    "pending": DATA / "latest_final_pending_v33.csv",
    "report": DATA / "latest_final_audit_report_v33.json",
}

VALID_DECISIONS = {"PENDING", "APPROVE", "REJECT", "HOLD"}


def read_csv(path):
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields=None):
    path.parent.mkdir(parents=True, exist_ok=True)

    if fields is None:
        fields = list(dict.fromkeys(
            key for row in rows for key in row.keys()
        ))

    if not fields:
        fields = ["status"]

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def get_video_id(row):
    for key in ("video_id", "videoId", "id"):
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    return ""


def normalize_title(title):
    title = str(title or "").lower()
    title = re.sub(r"https?://\S+", " ", title)
    title = re.sub(r"[^\w\s]", " ", title, flags=re.UNICODE)
    title = re.sub(r"\b(shorts?|viral|trending|official|4k)\b", " ", title)
    return " ".join(title.split())


def title_similarity(a, b):
    a = normalize_title(a)
    b = normalize_title(b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


def find_duplicates(rows):
    """
    Conservative title-based duplicate detection.
    This identifies possible duplicates, not confirmed copied videos.
    """
    items = []

    for row in rows:
        title = row.get("title", "")
        normalized = normalize_title(title)

        if len(normalized) >= 20:
            items.append({
                "video_id": row.get("video_id", ""),
                "title": title,
                "normalized": normalized,
            })

    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a = items[i]["normalized"]
            b = items[j]["normalized"]

            # Exact normalized title match.
            if a == b:
                union(i, j)
                continue

            # Similarity threshold avoids grouping weakly related titles.
            if len(a) >= 28 and len(b) >= 28:
                if a == b:
                    union(i, j)

    groups = {}

    for i, item in enumerate(items):
        root = find(i)
        groups.setdefault(root, []).append(item)

    duplicate_rows = []
    duplicate_lookup = {}

    group_number = 0

    for members in groups.values():
        if len(members) < 2:
            continue

        group_number += 1
        group_id = f"DUP_{group_number:03d}"

        for item in members:
            duplicate_lookup[item["video_id"]] = group_id
            duplicate_rows.append({
                "duplicate_group_id": group_id,
                "video_id": item["video_id"],
                "title": item["title"],
                "group_size": len(members),
                "verification_status": "POSSIBLE_DUPLICATE_REQUIRES_CHECK",
            })

    return duplicate_rows, duplicate_lookup


def load_decisions():
    decisions = {}

    for row in read_csv(DECISIONS_FILE):
        video_id = get_video_id(row)
        if not video_id:
            continue

        decision = str(row.get("decision", "PENDING")).strip().upper()

        if decision not in VALID_DECISIONS:
            raise ValueError(
                f"Invalid decision for {video_id}: {decision}"
            )

        decisions[video_id] = {
            "decision": decision,
            "reviewer_notes": row.get("reviewer_notes", ""),
            "decision_reason": row.get("decision_reason", ""),
        }

    return decisions


def main():
    print("=" * 65)
    print("YOUTUBE UNIVERSE V3.3")
    print("CONSOLIDATED FINAL AUDIT ENGINE")
    print("=" * 65)

    if not DATA.exists():
        raise FileNotFoundError(f"Data folder missing: {DATA}")

    if not INPUTS["ranking"].exists():
        raise FileNotFoundError(
            f"Required ranking file missing: {INPUTS['ranking']}"
        )

    sources = {}
    source_counts = {}

    for name, path in INPUTS.items():
        rows = read_csv(path)
        sources[name] = {}

        for row in rows:
            video_id = get_video_id(row)
            if video_id:
                sources[name][video_id] = row

        source_counts[name] = len(sources[name])

    ranking_rows = read_csv(INPUTS["ranking"])

    if not ranking_rows:
        raise RuntimeError("Ranking CSV is empty.")

    ranking_ids = [
        get_video_id(row)
        for row in ranking_rows
        if get_video_id(row)
    ]

    if len(ranking_ids) != len(set(ranking_ids)):
        raise RuntimeError(
            "Duplicate video_id values found in ranking input."
        )

    decisions = load_decisions()

    audit_rows = []

    for position, ranking_row in enumerate(ranking_rows, start=1):
        video_id = get_video_id(ranking_row)

        if not video_id:
            continue

        result = dict(ranking_row)
        result["video_id"] = video_id
        result["audit_rank_position"] = position

        for source_name in (
            "performance",
            "format",
            "quality",
            "relevance",
        ):
            source_row = sources[source_name].get(video_id)

            if source_row:
                for key, value in source_row.items():
                    if key in ("video_id", "videoId", "id"):
                        continue

                    result[f"{source_name}__{key}"] = value

        decision_data = decisions.get(video_id, {})

        decision = decision_data.get("decision", "PENDING")

        result["human_decision"] = decision
        result["reviewer_notes"] = decision_data.get(
            "reviewer_notes", ""
        )
        result["decision_reason"] = decision_data.get(
            "decision_reason", ""
        )

        result["ranking_data_available"] = "YES"
        result["performance_data_available"] = (
            "YES" if video_id in sources["performance"] else "NO"
        )
        result["format_data_available"] = (
            "YES" if video_id in sources["format"] else "NO"
        )
        result["quality_record_available"] = (
            "YES" if video_id in sources["quality"] else "NO"
        )
        result["relevance_data_available"] = (
            "YES" if video_id in sources["relevance"] else "NO"
        )

        quality_row = sources["quality"].get(video_id, {})

        quality_status_text = " ".join(
            str(value or "").upper()
            for key, value in quality_row.items()
            if any(term in key.lower() for term in (
                "transcript", "quality_status", "evaluation_status"
            ))
        )

        transcript_available = any(
            "AVAILABLE" in value
            for key, value in quality_row.items()
            if "transcript" in key.lower()
        )

        if transcript_available:
            result["content_quality_verification"] = "TRANSCRIPT_AVAILABLE_REQUIRES_SCORING"
        elif quality_row:
            result["content_quality_verification"] = "NOT_VERIFIED"
        else:
            result["content_quality_verification"] = "MISSING_QUALITY_RECORD"

        group_id = ""
        result["duplicate_group_id"] = group_id
        result["duplicate_check"] = "NOT_CHECKED"

        result["final_audit_status"] = "METADATA_AUDIT_ONLY"
        result["production_approval"] = "NO"

        if decision == "APPROVE":
            result["recommended_next_action"] = "RESEARCH_CANDIDATE"
        elif decision == "REJECT":
            result["recommended_next_action"] = "REJECTED_BY_REVIEWER"
        elif decision == "HOLD":
            result["recommended_next_action"] = "HOLD_FOR_REVIEW"
        else:
            result["recommended_next_action"] = "PENDING_HUMAN_REVIEW"

        audit_rows.append(result)

    duplicate_rows, duplicate_lookup = find_duplicates(audit_rows)

    for row in audit_rows:
        group_id = duplicate_lookup.get(row["video_id"], "")

        row["duplicate_group_id"] = group_id
        row["duplicate_check"] = (
            "POSSIBLE_DUPLICATE" if group_id else "NO_TITLE_MATCH_FOUND"
        )

        if group_id:
            row["recommended_next_action"] = (
                "CHECK_DUPLICATE_BEFORE_RESEARCH"
            )

    approved = [
        row for row in audit_rows
        if row["human_decision"] == "APPROVE"
    ]

    rejected = [
        row for row in audit_rows
        if row["human_decision"] == "REJECT"
    ]

    hold = [
        row for row in audit_rows
        if row["human_decision"] == "HOLD"
    ]

    pending = [
        row for row in audit_rows
        if row["human_decision"] == "PENDING"
    ]

    # Priority is based on the existing ranking order.
    # It does not imply factual verification or production approval.
    priority = []

    for row in audit_rows:
        item = dict(row)

        if row["duplicate_group_id"]:
            item["research_priority"] = "CHECK_DUPLICATE_FIRST"
        elif row["human_decision"] == "APPROVE":
            item["research_priority"] = "APPROVED_FOR_RESEARCH"
        elif row["human_decision"] == "HOLD":
            item["research_priority"] = "WAITING_FOR_REVIEW"
        elif row["human_decision"] == "REJECT":
            item["research_priority"] = "NOT_IN_RESEARCH_QUEUE"
        else:
            item["research_priority"] = "PENDING_REVIEW"

        priority.append(item)

    all_fields = list(dict.fromkeys(
        key for row in audit_rows for key in row.keys()
    ))

    priority_fields = list(dict.fromkeys(
        key for row in priority for key in row.keys()
    ))

    duplicate_fields = [
        "duplicate_group_id",
        "video_id",
        "title",
        "group_size",
        "verification_status",
    ]

    write_csv(OUTPUTS["audit"], audit_rows, all_fields)
    write_csv(OUTPUTS["approved"], approved, all_fields)
    write_csv(OUTPUTS["hold"], hold, all_fields)
    write_csv(OUTPUTS["rejected"], rejected, all_fields)
    write_csv(OUTPUTS["pending"], pending, all_fields)
    write_csv(OUTPUTS["priority"], priority, priority_fields)
    write_csv(
        OUTPUTS["duplicates"],
        duplicate_rows,
        duplicate_fields,
    )

    now = datetime.now(timezone.utc).isoformat()

    report = {
        "engine": "V33.1-CONSOLIDATED-AUDIT",
        "generated_at": now,
        "total_ranking_videos": len(audit_rows),
        "unique_video_ids": len(set(
            row["video_id"] for row in audit_rows
        )),
        "source_record_counts": source_counts,
        "human_decisions": {
            "APPROVE": len(approved),
            "REJECT": len(rejected),
            "HOLD": len(hold),
            "PENDING": len(pending),
        },
        "possible_duplicate_groups": len({
            row["duplicate_group_id"] for row in duplicate_rows
        }),
        "possible_duplicate_video_records": len(duplicate_rows),
        "transcript_limitation": (
            "Transcript availability is checked from the existing "
            "quality CSV. Missing transcripts mean content quality "
            "cannot be verified."
        ),
        "automatic_final_approval": False,
        "production_approval": False,
        "database_modified": False,
        "api_calls": 0,
        "outputs": {
            key: path.name for key, path in OUTPUTS.items()
        },
    }

    OUTPUTS["report"].write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("\nSOURCE RECORD COUNTS")
    for name, count in source_counts.items():
        print(f"{name}: {count}")

    print("\nFINAL AUDIT SUMMARY")
    print("Total videos:", len(audit_rows))
    print("APPROVE:", len(approved))
    print("REJECT:", len(rejected))
    print("HOLD:", len(hold))
    print("PENDING:", len(pending))
    print("Possible duplicate groups:", report["possible_duplicate_groups"])
    print("Possible duplicate records:", len(duplicate_rows))

    print("\nOUTPUT VERIFICATION")
    for path in OUTPUTS.values():
        valid = path.exists() and path.stat().st_size > 0
        print(("PASS" if valid else "FAIL"), path.name)

    print("\nDATABASE MODIFIED: NO")
    print("API CALLS: 0")
    print("AUTOMATIC FINAL APPROVAL: NO")
    print("STATUS: COMPLETED")


if __name__ == "__main__":
    main()
