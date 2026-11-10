
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import csv
import json
import re
import sys

BASE = Path("data/research/youtube_universe_v33")
WORKSPACE = BASE / "research_workspace_v33"
TEMPLATES = WORKSPACE / "_templates"
PACKAGES = BASE / "research_packages_v33"

AUDIT_FILE = BASE / "latest_final_audit_v33.csv"
DECISIONS_FILE = BASE / "human_review_decisions_v33.csv"
RESEARCH_DECISIONS_FILE = BASE / "research_review_decisions_v33.csv"

QUEUE_FILE = BASE / "latest_research_workbench_queue_v33.csv"
REPORT_FILE = BASE / "latest_research_workbench_report_v33.json"

NOW = datetime.now().astimezone()
STAMP = NOW.strftime("%Y%m%d_%H%M%S")

SOURCE_FIELDS = [
    "source_id", "title", "author", "organization", "published_date",
    "source_type", "url_or_doi", "accessed_date",
    "source_review_status", "notes"
]

CLAIM_FIELDS = [
    "claim_id", "claim_text", "claim_type", "importance",
    "claim_status", "limitations", "reviewer_notes"
]

EVIDENCE_FIELDS = [
    "evidence_id", "claim_id", "source_id", "evidence_relation",
    "evidence_summary", "source_locator", "review_status", "notes"
]

RESEARCH_DECISION_FIELDS = [
    "video_id", "research_decision", "reviewer_notes", "decided_at"
]

QUEUE_FIELDS = [
    "video_id", "title", "topic_decision", "workspace_status",
    "source_count", "reviewed_source_count", "claim_count",
    "supported_claim_count", "conflict_count", "research_gate",
    "research_package"
]


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Required file missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def create_template_if_missing(path, fields):
    if not path.exists():
        write_csv(path, [], fields)
        return True
    return False


def value(row, key, default=""):
    return str(row.get(key, default) or "").strip()


def safe_name(text):
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", str(text))
    return text[:70] or "unknown"


def valid_source_locator(locator):
    locator = locator.strip()
    if not locator:
        return False
    if locator.lower().startswith("doi:"):
        return len(locator) > 8
    parsed = urlparse(locator)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def make_workspace(video_id):
    folder = WORKSPACE / safe_name(video_id)
    folder.mkdir(parents=True, exist_ok=True)

    created = []
    files = {
        "sources.csv": SOURCE_FIELDS,
        "claims.csv": CLAIM_FIELDS,
        "evidence.csv": EVIDENCE_FIELDS,
    }

    for filename, fields in files.items():
        if create_template_if_missing(folder / filename, fields):
            created.append(filename)

    return folder, created


def analyze_workspace(folder):
    sources = read_csv(folder / "sources.csv")
    claims = read_csv(folder / "claims.csv")
    evidence = read_csv(folder / "evidence.csv")

    source_map = {
        value(row, "source_id"): row
        for row in sources if value(row, "source_id")
    }
    claim_map = {
        value(row, "claim_id"): row
        for row in claims if value(row, "claim_id")
    }

    reviewed_sources = 0
    source_errors = []
    for source in sources:
        source_id = value(source, "source_id")
        status = value(source, "source_review_status").upper()
        locator = value(source, "url_or_doi")

        if status == "REVIEWED":
            if not valid_source_locator(locator):
                source_errors.append(
                    f"{source_id}: REVIEWED source has invalid URL/DOI"
                )
            elif not value(source, "title") or not (
                value(source, "author") or value(source, "organization")
            ):
                source_errors.append(
                    f"{source_id}: title and author/organization required"
                )
            else:
                reviewed_sources += 1

    evidence_by_claim = {}
    evidence_errors = []
    conflicts = []

    for item in evidence:
        evidence_id = value(item, "evidence_id")
        claim_id = value(item, "claim_id")
        source_id = value(item, "source_id")
        relation = value(item, "evidence_relation").upper()
        review_status = value(item, "review_status").upper()

        if claim_id not in claim_map:
            evidence_errors.append(
                f"{evidence_id}: claim_id does not exist"
            )
            continue
        if source_id not in source_map:
            evidence_errors.append(
                f"{evidence_id}: source_id does not exist"
            )
            continue

        evidence_by_claim.setdefault(claim_id, []).append(item)

        if relation not in ("SUPPORTS", "CONTRADICTS", "MIXED", "CONTEXT"):
            evidence_errors.append(
                f"{evidence_id}: invalid evidence_relation"
            )
        if review_status == "REVIEWED":
            if value(source_map[source_id], "source_review_status").upper() != "REVIEWED":
                evidence_errors.append(
                    f"{evidence_id}: linked source is not REVIEWED"
                )

    supported_claims = 0
    unresolved_claims = 0
    claim_errors = []
    claim_results = []

    for claim_id, claim in claim_map.items():
        status = value(claim, "claim_status").upper()
        linked = evidence_by_claim.get(claim_id, [])

        reviewed_support = [
            item for item in linked
            if value(item, "evidence_relation").upper() == "SUPPORTS"
            and value(item, "review_status").upper() == "REVIEWED"
            and value(
                source_map.get(value(item, "source_id"), {}),
                "source_review_status"
            ).upper() == "REVIEWED"
        ]

        reviewed_contradictions = [
            item for item in linked
            if value(item, "evidence_relation").upper()
            in ("CONTRADICTS", "MIXED")
            and value(item, "review_status").upper() == "REVIEWED"
        ]

        if reviewed_contradictions:
            conflicts.append({
                "claim_id": claim_id,
                "claim_text": value(claim, "claim_text"),
                "conflicting_evidence_count": len(reviewed_contradictions),
                "status": status or "NOT_REVIEWED",
            })

        if status == "SUPPORTED" and reviewed_support and not reviewed_contradictions:
            supported_claims += 1
        else:
            unresolved_claims += 1

        if not value(claim, "claim_text"):
            claim_errors.append(f"{claim_id}: claim_text is empty")

        claim_results.append({
            "claim_id": claim_id,
            "claim_text": value(claim, "claim_text"),
            "claim_status": status or "NOT_REVIEWED",
            "supporting_evidence": len(reviewed_support),
            "conflicting_evidence": len(reviewed_contradictions),
            "limitations": value(claim, "limitations"),
        })

    errors = source_errors + evidence_errors + claim_errors

    gate_reasons = []
    if not sources:
        gate_reasons.append("No research sources added")
    if not claims:
        gate_reasons.append("No factual claims added")
    if not evidence:
        gate_reasons.append("No evidence mapped to claims")
    if unresolved_claims:
        gate_reasons.append("One or more claims are unresolved")
    if conflicts:
        gate_reasons.append("Conflicting or mixed evidence requires review")
    if errors:
        gate_reasons.append("Data validation errors exist")

    return {
        "sources": sources,
        "claims": claims,
        "evidence": evidence,
        "source_count": len(sources),
        "reviewed_source_count": reviewed_sources,
        "claim_count": len(claims),
        "supported_claim_count": supported_claims,
        "unresolved_claim_count": unresolved_claims,
        "conflicts": conflicts,
        "claim_results": claim_results,
        "validation_errors": errors,
        "gate_reasons": gate_reasons,
        "research_ready": (
            bool(sources)
            and bool(claims)
            and bool(evidence)
            and unresolved_claims == 0
            and not conflicts
            and not errors
        ),
    }


def build_package(video, decision, folder, analysis, research_decision):
    video_id = value(video, "video_id")
    title = value(video, "title", "Untitled topic")

    source_lines = []
    for source in analysis["sources"]:
        source_lines.append(
            f"| {value(source, 'source_id')} | "
            f"{value(source, 'title')} | "
            f"{value(source, 'author') or value(source, 'organization')} | "
            f"{value(source, 'url_or_doi')} | "
            f"{value(source, 'source_review_status')} |"
        )

    claim_lines = []
    for claim in analysis["claim_results"]:
        claim_lines.append(
            f"| {claim['claim_id']} | {claim['claim_text']} | "
            f"{claim['claim_status']} | {claim['supporting_evidence']} | "
            f"{claim['conflicting_evidence']} | {claim['limitations']} |"
        )

    conflict_lines = [
        f"- {item['claim_id']}: {item['claim_text']} "
        f"(conflicting evidence: {item['conflicting_evidence_count']})"
        for item in analysis["conflicts"]
    ]

    error_lines = [
        f"- {item}" for item in analysis["validation_errors"]
    ]
    reason_lines = [
        f"- {item}" for item in analysis["gate_reasons"]
    ]

    research_ready = analysis["research_ready"]
    approved = research_decision in ("APPROVE", "APPROVE_RESEARCH") and research_ready
    package_status = (
        "RESEARCH_APPROVED_FOR_SCRIPT_BRIEF"
        if approved else "RESEARCH_DRAFT_NOT_READY"
    )

    return f"""# Research Package — {title}

## Package control

- Video ID: `{video_id}`
- Topic decision: `{value(decision, 'decision').upper()}`
- Research decision: `{research_decision or 'PENDING'}`
- Research gate: `{'PASS' if research_ready else 'BLOCKED'}`
- Package status: `{package_status}`
- Generated: `{NOW.isoformat(timespec='seconds')}`

## Topic and research objective

**Topic:** {title}

Research the exact central claim, its scientific or documentary basis,
real-world relevance, limitations, counter-evidence and practical value.

## Source register

| Source ID | Title | Author / organization | URL / DOI | Review status |
|---|---|---|---|---|
{chr(10).join(source_lines) if source_lines else '| No sources added | | | | |'}

A source is marked REVIEWED only after a person has opened and assessed it.
A URL alone is not proof that the source supports a claim.

## Claim register

| Claim ID | Claim | Status | Supporting evidence | Conflicting evidence | Limitations |
|---|---|---|---:|---:|---|
{chr(10).join(claim_lines) if claim_lines else '| No claims added | | | | | |'}

## Evidence conflicts

{chr(10).join(conflict_lines) if conflict_lines else 'No reviewed conflicting evidence recorded.'}

## Data validation

{chr(10).join(error_lines) if error_lines else 'No structural validation errors.'}

## Research gate reasons

{chr(10).join(reason_lines) if reason_lines else 'All research checks passed.'}

## Research summary

- Sources: {analysis['source_count']}
- Reviewed sources: {analysis['reviewed_source_count']}
- Claims: {analysis['claim_count']}
- Supported claims: {analysis['supported_claim_count']}
- Unresolved claims: {analysis['unresolved_claim_count']}
- Conflicts: {len(analysis['conflicts'])}

## Script brief

- Language: Conversational Roman Hinglish
- Style: Clear, realistic documentary narration
- Hook: Use a relatable situation or a focused question.
- Main body: Explain the concept using only supported claims.
- Counterpoint: Include relevant limitations and disagreement.
- Ending: Give a practical takeaway without exaggerated promises.

Do not copy the reference video's script, wording or distinctive structure.
Every factual claim in a future script must map to a reviewed source and evidence record.

## Final production gate

- Topic approval: {'PASS' if value(decision, 'decision').upper() == 'APPROVE' else 'BLOCKED'}
- Research readiness: {'PASS' if research_ready else 'BLOCKED'}
- Research human approval: {'PASS' if research_decision in ('APPROVE', 'APPROVE_RESEARCH') else 'BLOCKED'}
- Script approval: NOT_STARTED
- Production approval: BLOCKED

**Final status: {package_status}**
"""


def main():
    print("=" * 65)
    print("YOUTUBE UNIVERSE V3.3")
    print("RESEARCH & SOURCE VERIFICATION WORKBENCH")
    print("=" * 65)

    for path in (AUDIT_FILE, DECISIONS_FILE):
        if not path.exists():
            raise FileNotFoundError(f"Required input missing: {path}")

    WORKSPACE.mkdir(parents=True, exist_ok=True)
    TEMPLATES.mkdir(parents=True, exist_ok=True)
    PACKAGES.mkdir(parents=True, exist_ok=True)

    audit_rows = read_csv(AUDIT_FILE)
    decisions = read_csv(DECISIONS_FILE)

    # Preserve this file and all existing reviewer decisions.
    create_template_if_missing(
        RESEARCH_DECISIONS_FILE, RESEARCH_DECISION_FIELDS
    )

    research_decisions = read_csv(RESEARCH_DECISIONS_FILE)
    research_decision_map = {
        value(row, "video_id"): row
        for row in research_decisions if value(row, "video_id")
    }
    decision_map = {
        value(row, "video_id"): row
        for row in decisions if value(row, "video_id")
    }

    audit_map = {
        value(row, "video_id"): row
        for row in audit_rows if value(row, "video_id")
    }

    queue = []
    generated_packages = 0
    approved_topics = 0
    blocked_topics = 0
    ready_topics = 0
    all_validation_errors = []

    for video_id, video in audit_map.items():
        decision = decision_map.get(video_id, {})
        topic_status = value(decision, "decision", "MISSING").upper()

        if topic_status != "APPROVE":
            blocked_topics += 1
            queue.append({
                "video_id": video_id,
                "title": value(video, "title"),
                "topic_decision": topic_status,
                "workspace_status": "BLOCKED_TOPIC_NOT_APPROVED",
                "source_count": 0,
                "reviewed_source_count": 0,
                "claim_count": 0,
                "supported_claim_count": 0,
                "conflict_count": 0,
                "research_gate": "BLOCKED",
                "research_package": "",
            })
            continue

        approved_topics += 1
        folder, created = make_workspace(video_id)

        analysis = analyze_workspace(folder)
        research_decision = value(
            research_decision_map.get(video_id, {}),
            "research_decision"
        ).upper()

        if analysis["research_ready"]:
            ready_topics += 1

        all_validation_errors.extend(
            [f"{video_id}: {err}" for err in analysis["validation_errors"]]
        )

        package_name = (
            f"research_package_{safe_name(video_id)}_{STAMP}.md"
        )
        package_path = PACKAGES / package_name
        package_path.write_text(
            build_package(video, decision, folder, analysis, research_decision),
            encoding="utf-8"
        )
        generated_packages += 1

        gate_pass = (
            analysis["research_ready"]
            and research_decision in ("APPROVE", "APPROVE_RESEARCH")
        )

        queue.append({
            "video_id": video_id,
            "title": value(video, "title"),
            "topic_decision": topic_status,
            "workspace_status": (
                "WORKSPACE_READY" if created else "WORKSPACE_EXISTS"
            ),
            "source_count": analysis["source_count"],
            "reviewed_source_count": analysis["reviewed_source_count"],
            "claim_count": analysis["claim_count"],
            "supported_claim_count": analysis["supported_claim_count"],
            "conflict_count": len(analysis["conflicts"]),
            "research_gate": "PASS" if gate_pass else "BLOCKED",
            "research_package": str(package_path),
        })

    # Preserve visibility of decision records that are not in the audit.
    for video_id, decision in decision_map.items():
        if video_id not in audit_map:
            queue.append({
                "video_id": video_id,
                "title": value(decision, "title"),
                "topic_decision": value(decision, "decision"),
                "workspace_status": "BLOCKED_AUDIT_RECORD_MISSING",
                "source_count": 0,
                "reviewed_source_count": 0,
                "claim_count": 0,
                "supported_claim_count": 0,
                "conflict_count": 0,
                "research_gate": "BLOCKED",
                "research_package": "",
            })

    write_csv(QUEUE_FILE, queue, QUEUE_FIELDS)

    report = {
        "engine": "YOUTUBE_UNIVERSE_V3.3_RESEARCH_WORKBENCH",
        "generated_at": NOW.isoformat(),
        "audit_records": len(audit_rows),
        "human_decision_records": len(decisions),
        "research_decision_records": len(research_decisions),
        "approved_topics": approved_topics,
        "blocked_topics": blocked_topics,
        "workspaces_created_or_checked": approved_topics,
        "research_ready_topics": ready_topics,
        "research_packages_generated": generated_packages,
        "packages_are_production_approved": False,
        "validation_errors": all_validation_errors,
        "database_modified": False,
        "youtube_api_calls": 0,
        "automatic_source_verification": False,
        "automatic_claim_verification": False,
        "human_research_approval_required": True,
        "script_generation_allowed_only_after_research_gate": True,
        "outputs": {
            "workspace": str(WORKSPACE),
            "queue": str(QUEUE_FILE),
            "report": str(REPORT_FILE),
            "packages": str(PACKAGES),
        },
        "status": "COMPLETED",
    }

    REPORT_FILE.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print("\nINPUT COUNTS")
    print("Audit:", len(audit_rows))
    print("Topic decisions:", len(decisions))
    print("Research decisions:", len(research_decisions))

    print("\nWORKBENCH SUMMARY")
    print("Approved topics:", approved_topics)
    print("Blocked topics:", blocked_topics)
    print("Research-ready topics:", ready_topics)
    print("Research packages generated:", generated_packages)
    print("Validation errors:", len(all_validation_errors))

    print("\nOUTPUT VERIFICATION")
    for path in (QUEUE_FILE, REPORT_FILE, WORKSPACE, PACKAGES):
        exists = path.exists()
        print(("PASS" if exists else "FAIL"), path)

    print("\nDATABASE MODIFIED: NO")
    print("YOUTUBE API CALLS: 0")
    print("AUTOMATIC SOURCE VERIFICATION: NO")
    print("AUTOMATIC CLAIM VERIFICATION: NO")
    print("AUTOMATIC PRODUCTION APPROVAL: NO")
    print("STATUS: COMPLETED")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nERROR:", str(exc))
        sys.exit(1)
