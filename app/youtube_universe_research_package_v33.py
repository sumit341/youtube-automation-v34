
from pathlib import Path
from datetime import datetime
import csv
import json
import re
import sys

BASE = Path("data/research/youtube_universe_v33")
AUDIT_FILE = BASE / "latest_final_audit_v33.csv"
DECISIONS_FILE = BASE / "human_review_decisions_v33.csv"
RANKING_FILE = BASE / "latest_candidate_ranking_v33.csv"
FORMAT_FILE = BASE / "latest_format_master_v33.csv"
PERFORMANCE_FILE = BASE / "latest_master_performance_v33.csv"
QUALITY_FILE = BASE / "latest_content_quality_master_v33.csv"
RELEVANCE_FILE = BASE / "latest_master_scored_videos_v33.csv"

PACKAGE_DIR = BASE / "research_packages_v33"
QUEUE_FILE = BASE / "latest_research_package_queue_v33.csv"
REPORT_FILE = BASE / "latest_research_package_report_v33.json"

TIMESTAMP = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Required input missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def first_value(row, *keys, default="NOT_AVAILABLE"):
    for key in keys:
        value = clean(row.get(key, ""))
        if value:
            return value
    return default


def safe_filename(value):
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", clean(value))
    return value[:80] or "unknown_video"


def write_csv(path, rows, fieldnames):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def make_package(row, decision):
    video_id = first_value(row, "video_id", default="UNKNOWN")
    title = first_value(row, "title", default="Untitled topic")
    description = first_value(row, "description", default="Description unavailable")
    video_url = first_value(
        row, "video_url",
        default=f"https://www.youtube.com/watch?v={video_id}"
    )

    relevance = first_value(row, "relevance_score", "score", default="NOT_EVALUATED")
    performance = first_value(row, "performance_score", default="NOT_EVALUATED")
    format_score = first_value(row, "format_score", "best_format_score",
                               default="NOT_EVALUATED")
    quality_status = first_value(
        row, "content_quality_status", default="NOT_EVALUATED"
    )
    quality_score = first_value(
        row, "content_quality_score", default="NOT_EVALUATED"
    )
    recommended_format = first_value(
        row, "recommended_format", default="HUMAN_SELECTION_REQUIRED"
    )
    ranking_status = first_value(
        row, "ranking_status", default="NOT_AVAILABLE"
    )

    reviewer_notes = clean(decision.get("reviewer_notes", ""))
    decision_reason = clean(decision.get("decision_reason", ""))
    decided_at = clean(decision.get("decided_at", ""))

    return f"""# Research Package — {title}

## 1. Package status

- Package ID: `RP_{video_id}_{TIMESTAMP}`
- Video ID: `{video_id}`
- Approval status: `APPROVE`
- Research status: `NOT_RESEARCHED`
- Fact verification: `NOT_STARTED`
- Production status: `NOT_APPROVED`
- Generated at: `{datetime.now().astimezone().isoformat(timespec="seconds")}`

## 2. Original video reference

- Title: {title}
- Video URL: {video_url}
- Original description:

{description}

## 3. Existing research signals

| Metric | Available value |
|---|---|
| Relevance score | {relevance} |
| Performance score | {performance} |
| Format score | {format_score} |
| Recommended format | {recommended_format} |
| Ranking status | {ranking_status} |
| Content quality status | {quality_status} |
| Content quality score | {quality_score} |

Important: These are existing metadata-derived signals. They are not proof of factual accuracy, audience retention, or future performance. Content quality remains unevaluated unless transcript-based evaluation has actually been completed.

## 4. Topic understanding

**Working topic:** {title}

**Initial angle:** Identify the specific human psychology, money psychology, power dynamics, or success-related idea behind this topic.

**Research objective:** Establish what the topic actually claims, what reliable evidence supports it, where evidence is uncertain, and what practical insight viewers can take away.

## 5. Research questions

1. What is the precise central claim of this topic?
2. Which established psychological concepts are relevant?
3. What peer-reviewed studies or credible primary sources examine this subject?
4. What are the limitations, disagreements, or alternative explanations?
5. Does the claim apply broadly, or only in a particular context?
6. What real-world example can explain the concept without exaggeration?
7. What practical lesson can viewers safely apply?

## 6. Fact-check checklist

| Check | Status |
|---|---|
| Central claim identified | NOT_STARTED |
| Primary research located | NOT_STARTED |
| Peer-reviewed evidence checked | NOT_STARTED |
| Source credibility assessed | NOT_STARTED |
| Study limitations recorded | NOT_STARTED |
| Conflicting evidence checked | NOT_STARTED |
| Statistics independently verified | NOT_STARTED |
| Final factual review | NOT_STARTED |

No claim is verified by this generator. Every factual statement must be checked against its original source before script approval.

## 7. Source register

Add sources only after actually opening and reviewing them.

| Source title | Author / organization | URL / DOI | Source type | Claim supported | Verification |
|---|---|---|---|---|---|
| TO_BE_RESEARCHED | TO_BE_RESEARCHED | TO_BE_RESEARCHED | TO_BE_RESEARCHED | TO_BE_RESEARCHED | NOT_VERIFIED |

Preferred source order:
1. Original peer-reviewed research papers.
2. Academic books and university publications.
3. Government or recognized institutional sources.
4. Credible expert commentary for context.

Avoid treating social posts, unattributed statistics, or other YouTube videos as primary evidence.

## 8. Audience and storytelling opportunity

- Audience problem: What everyday confusion, decision, fear, or behavior does this topic explain?
- Emotional connection: What relatable situation can introduce the idea?
- Curiosity gap: What surprising but evidence-supported question can keep viewers interested?
- Practical value: What can viewers understand or do differently?
- Originality requirement: Do not copy the reference video's script, structure, or distinctive expression.

## 9. Format and script brief

- Suggested format: {recommended_format}
- Final format: HUMAN_REVIEW_REQUIRED
- Language: Conversational Roman Hinglish
- Tone: Clear, realistic, documentary-style narration
- Opening: Start with a relatable situation or a focused question.
- Main body: Explain the concept, evidence, limitations, and example.
- Ending: Give a practical takeaway without making exaggerated promises.

## 10. Script-writing brief

Write a fresh script only after research is completed.

Required script elements:
1. Hook
2. Context and central question
3. Concept explanation
4. Evidence-backed examples
5. Counterpoint or limitation
6. Practical takeaway
7. Strong closing

Every factual claim in the script must map to an entry in the source register.

## 11. Human approval record

- Decision: APPROVE
- Decision reason: {decision_reason or "Not provided"}
- Reviewer notes: {reviewer_notes or "Not provided"}
- Decision timestamp: {decided_at or "Not provided"}

## 12. Final readiness gates

- Topic approved: PASS
- Research completed: NOT_STARTED
- Sources verified: NOT_STARTED
- Claims fact-checked: NOT_STARTED
- Script reviewed: NOT_STARTED
- Production approval: BLOCKED

**Final status: RESEARCH PACKAGE DRAFT — NOT PRODUCTION APPROVED**
"""


def main():
    print("=" * 65)
    print("YOUTUBE UNIVERSE V3.3")
    print("RESEARCH PACKAGE GENERATOR")
    print("=" * 65)

    audit_rows = read_csv(AUDIT_FILE)
    decision_rows = read_csv(DECISIONS_FILE)

    # Load supporting module outputs for input verification.
    supporting_files = {
        "ranking": RANKING_FILE,
        "format": FORMAT_FILE,
        "performance": PERFORMANCE_FILE,
        "quality": QUALITY_FILE,
        "relevance": RELEVANCE_FILE,
    }

    supporting_counts = {}
    for name, path in supporting_files.items():
        supporting_counts[name] = len(read_csv(path))

    audit_by_id = {}
    for row in audit_rows:
        video_id = clean(row.get("video_id"))
        if video_id:
            audit_by_id[video_id] = row

    decisions_by_id = {}
    for row in decision_rows:
        video_id = clean(row.get("video_id"))
        if video_id:
            decisions_by_id[video_id] = row

    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)

    queue = []
    generated = 0
    blocked = 0
    approved_without_audit = 0

    for video_id, decision in decisions_by_id.items():
        status = clean(decision.get("decision", "PENDING")).upper()
        audit = audit_by_id.get(video_id)

        if not audit:
            approved_without_audit += int(status == "APPROVE")
            queue.append({
                "video_id": video_id,
                "title": clean(decision.get("title", "")),
                "human_decision": status,
                "package_status": "BLOCKED_AUDIT_RECORD_MISSING",
                "package_file": "",
            })
            continue

        if status == "APPROVE":
            package_name = (
                f"research_package_{safe_filename(video_id)}_{TIMESTAMP}.md"
            )
            package_path = PACKAGE_DIR / package_name
            package_path.write_text(
                make_package(audit, decision),
                encoding="utf-8"
            )
            generated += 1
            package_status = "DRAFT_GENERATED_NOT_PRODUCTION_APPROVED"
            package_file = str(package_path)
        else:
            blocked += 1
            package_status = f"BLOCKED_HUMAN_DECISION_{status}"
            package_file = ""

        queue.append({
            "video_id": video_id,
            "title": first_value(audit, "title", default=""),
            "human_decision": status,
            "package_status": package_status,
            "package_file": package_file,
        })

    # Include audit records with no decision entry as blocked.
    for video_id, audit in audit_by_id.items():
        if video_id not in decisions_by_id:
            blocked += 1
            queue.append({
                "video_id": video_id,
                "title": clean(audit.get("title", "")),
                "human_decision": "MISSING",
                "package_status": "BLOCKED_DECISION_MISSING",
                "package_file": "",
            })

    queue_fields = [
        "video_id", "title", "human_decision",
        "package_status", "package_file"
    ]
    write_csv(QUEUE_FILE, queue, queue_fields)

    report = {
        "engine": "YOUTUBE_UNIVERSE_V3.3_RESEARCH_PACKAGE_GENERATOR",
        "generated_at": datetime.now().astimezone().isoformat(),
        "audit_records": len(audit_rows),
        "human_decision_records": len(decision_rows),
        "supporting_source_counts": supporting_counts,
        "packages_generated": generated,
        "topics_blocked": blocked,
        "approved_topics_missing_audit": approved_without_audit,
        "package_directory": str(PACKAGE_DIR),
        "queue_file": str(QUEUE_FILE),
        "database_modified": False,
        "youtube_api_calls": 0,
        "automatic_topic_approval": False,
        "automatic_fact_verification": False,
        "production_approval": False,
        "status": "COMPLETED",
    }

    REPORT_FILE.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print("\nINPUT RECORD COUNTS")
    print("Audit:", len(audit_rows))
    print("Human decisions:", len(decision_rows))
    for name, count in supporting_counts.items():
        print(f"{name}: {count}")

    print("\nGENERATION SUMMARY")
    print("Packages generated:", generated)
    print("Topics blocked:", blocked)
    print("Approved topics missing audit:", approved_without_audit)

    print("\nOUTPUT VERIFICATION")
    for path in [QUEUE_FILE, REPORT_FILE]:
        print(("PASS" if path.exists() and path.stat().st_size > 0 else "FAIL"),
              path.name)

    print("\nDATABASE MODIFIED: NO")
    print("YOUTUBE API CALLS: 0")
    print("AUTOMATIC FACT VERIFICATION: NO")
    print("PRODUCTION APPROVAL: NO")
    print("STATUS: COMPLETED")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nERROR:", str(exc))
        sys.exit(1)
