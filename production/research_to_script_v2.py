from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "research" / "youtube_universe_v33"
WORKSPACES = BASE / "research_workspace_v33"
DECISIONS_FILE = BASE / "research_review_decisions_v33.csv"

REQUIRED_FIELDS = {
    "sources": {
        "source_id", "title", "url_or_doi", "source_review_status"
    },
    "claims": {
        "claim_id", "claim_text", "claim_status"
    },
    "evidence": {
        "evidence_id", "claim_id", "source_id",
        "evidence_relation", "evidence_summary",
        "source_locator", "review_status"
    },
    "decisions": {
        "video_id", "research_decision"
    },
}


def clean(value):
    return str(value or "").strip()


def read_csv(path, required):
    if not path.exists():
        raise FileNotFoundError(f"Required file missing: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])

        missing = required - fields
        if missing:
            raise ValueError(
                f"Invalid CSV schema in {path.name}; missing: {sorted(missing)}"
            )

        return list(reader)


def duplicate_ids(rows, field):
    values = [clean(row.get(field)) for row in rows]
    duplicates = sorted({
        value for value in values
        if value and values.count(value) > 1
    })
    blanks = sum(not value for value in values)
    return duplicates, blanks


def valid_locator(value):
    value = clean(value)
    if not value:
        return False

    if value.lower().startswith("doi:"):
        return len(value[4:].strip()) > 5

    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def decision_for(video_id):
    rows = read_csv(DECISIONS_FILE, REQUIRED_FIELDS["decisions"])
    matches = [
        row for row in rows
        if clean(row.get("video_id")) == video_id
    ]

    if len(matches) != 1:
        return "HOLD", (
            f"EXPECTED_EXACTLY_ONE_RESEARCH_DECISION_FOUND_{len(matches)}"
        )

    decision = clean(matches[0].get("research_decision")).upper()

    if decision not in ("APPROVE", "APPROVE_RESEARCH"):
        return "HOLD", f"RESEARCH_DECISION_NOT_APPROVED:{decision or 'EMPTY'}"

    return "APPROVED", ""


def audit(video_id):
    workspace = WORKSPACES / video_id

    sources = read_csv(
        workspace / "sources.csv", REQUIRED_FIELDS["sources"]
    )
    claims = read_csv(
        workspace / "claims.csv", REQUIRED_FIELDS["claims"]
    )
    evidence = read_csv(
        workspace / "evidence.csv", REQUIRED_FIELDS["evidence"]
    )

    errors = []
    claim_results = []

    if not sources:
        errors.append("NO_SOURCES")
    if not claims:
        errors.append("NO_CLAIMS")
    if not evidence:
        errors.append("NO_EVIDENCE")

    for rows, field, label in (
        (sources, "source_id", "SOURCE"),
        (claims, "claim_id", "CLAIM"),
        (evidence, "evidence_id", "EVIDENCE"),
    ):
        duplicates, blanks = duplicate_ids(rows, field)

        if duplicates:
            errors.append(f"DUPLICATE_{label}_IDS:{','.join(duplicates)}")
        if blanks:
            errors.append(f"BLANK_{label}_IDS:{blanks}")

    source_map = {
        clean(row.get("source_id")): row for row in sources
        if clean(row.get("source_id"))
    }
    claim_map = {
        clean(row.get("claim_id")): row for row in claims
        if clean(row.get("claim_id"))
    }

    reviewed_sources = 0

    for source in sources:
        source_id = clean(source.get("source_id"))
        status = clean(source.get("source_review_status")).upper()
        locator = clean(source.get("url_or_doi"))

        if status == "REVIEWED":
            reviewed_sources += 1
            if not valid_locator(locator):
                errors.append(f"REVIEWED_SOURCE_INVALID_LOCATOR:{source_id}")

        elif status not in (
            "DISCOVERED", "PENDING", "NOT_REVIEWED", "REJECTED", ""
        ):
            errors.append(f"INVALID_SOURCE_STATUS:{source_id}:{status}")

    if reviewed_sources == 0:
        errors.append("NO_REVIEWED_SOURCES")

    evidence_by_claim = {}

    for item in evidence:
        evidence_id = clean(item.get("evidence_id"))
        claim_id = clean(item.get("claim_id"))
        source_id = clean(item.get("source_id"))
        relation = clean(item.get("evidence_relation")).upper()
        review_status = clean(item.get("review_status")).upper()

        if claim_id not in claim_map:
            errors.append(f"EVIDENCE_CLAIM_NOT_FOUND:{evidence_id}")

        if source_id not in source_map:
            errors.append(f"EVIDENCE_SOURCE_NOT_FOUND:{evidence_id}")
        else:
            linked_source = source_map[source_id]
            if clean(linked_source.get("source_review_status")).upper() == "REJECTED":
                errors.append(f"EVIDENCE_SOURCE_REJECTED:{evidence_id}:{source_id}")

        if relation not in ("SUPPORTS", "CONTRADICTS", "MIXED", "CONTEXT"):
            errors.append(f"INVALID_EVIDENCE_RELATION:{evidence_id}:{relation}")

        if review_status not in ("REVIEWED", "PENDING", "NOT_REVIEWED", ""):
            errors.append(f"INVALID_EVIDENCE_STATUS:{evidence_id}:{review_status}")

        if not clean(item.get("evidence_summary")):
            errors.append(f"EVIDENCE_SUMMARY_MISSING:{evidence_id}")

        if review_status == "REVIEWED":
            if not valid_locator(item.get("source_locator")):
                errors.append(f"REVIEWED_EVIDENCE_LOCATOR_INVALID:{evidence_id}")

            source = source_map.get(source_id)
            if source and clean(source.get("source_review_status")).upper() != "REVIEWED":
                errors.append(f"REVIEWED_EVIDENCE_SOURCE_NOT_REVIEWED:{evidence_id}")

        if claim_id:
            evidence_by_claim.setdefault(claim_id, []).append(item)

    for claim_id, claim in claim_map.items():
        reasons = []
        linked = evidence_by_claim.get(claim_id, [])
        status = clean(claim.get("claim_status")).upper()

        if not clean(claim.get("claim_text")):
            reasons.append("CLAIM_TEXT_MISSING")

        if status != "SUPPORTED":
            reasons.append(f"CLAIM_NOT_SUPPORTED:{status or 'EMPTY'}")

        if not linked:
            reasons.append("NO_LINKED_EVIDENCE")

        supporting_reviewed = []

        for item in linked:
            evidence_id = clean(item.get("evidence_id"))
            source_id = clean(item.get("source_id"))
            relation = clean(item.get("evidence_relation")).upper()
            review_status = clean(item.get("review_status")).upper()
            source = source_map.get(source_id)

            if review_status != "REVIEWED":
                reasons.append(f"EVIDENCE_NOT_REVIEWED:{evidence_id}")

            if relation in ("CONTRADICTS", "MIXED") and review_status == "REVIEWED":
                reasons.append(f"REVIEWED_CONFLICT:{evidence_id}")

            if (
                relation == "SUPPORTS"
                and review_status == "REVIEWED"
                and source
                and clean(source.get("source_review_status")).upper() == "REVIEWED"
                and valid_locator(item.get("source_locator"))
            ):
                supporting_reviewed.append(evidence_id)

        if not supporting_reviewed:
            reasons.append("NO_VALID_REVIEWED_SUPPORTING_EVIDENCE")

        claim_results.append({
            "claim_id": claim_id,
            "claim_text": clean(claim.get("claim_text")),
            "status": "ELIGIBLE_FOR_CONTROLLED_DRAFT" if not reasons else "HOLD",
            "reasons": sorted(set(reasons)),
            "supporting_evidence_ids": supporting_reviewed,
            "limitations": clean(claim.get("limitations")),
        })

    approved, decision_error = decision_for(video_id)
    if decision_error:
        errors.append(decision_error)

    held_claims = sum(
        item["status"] == "HOLD" for item in claim_results
    )

    ready = (
        approved == "APPROVED"
        and not errors
        and bool(claim_results)
        and held_claims == 0
    )

    return {
        "audit_version": "2.0",
        "video_id": video_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "research_decision": approved,
        "total_sources": len(sources),
        "reviewed_sources": reviewed_sources,
        "total_claims": len(claim_results),
        "eligible_claims": len(claim_results) - held_claims,
        "held_claims": held_claims,
        "overall_status": (
            "READY_FOR_CONTROLLED_SCRIPT_DRAFT" if ready else "HOLD"
        ),
        "errors": sorted(set(errors)),
        "claim_results": claim_results,
        "safety": {
            "original_research_files_modified": False,
            "human_decisions_modified": False,
            "production_approved": False,
            "youtube_upload_authorized": False,
        },
    }


def write_report(report):
    video_id = report["video_id"]
    output = ROOT / "production" / "runs" / video_id
    output.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output / f"research_gate_v2_{stamp}.json"
    brief_path = output / f"script_input_brief_v2_{stamp}.md"

    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        "# Research Gate v2",
        "",
        f"Video ID: {video_id}",
        f"Gate status: {report['overall_status']}",
        f"Research decision: {report['research_decision']}",
        "",
    ]

    if report["overall_status"] == "READY_FOR_CONTROLLED_SCRIPT_DRAFT":
        lines.extend(["## Eligible factual claims", ""])
        for item in report["claim_results"]:
            lines.extend([
                f"### {item['claim_id']}",
                item["claim_text"],
                "Evidence IDs: " + ", ".join(item["supporting_evidence_ids"]),
                "Limitations: " + item["limitations"],
                "",
            ])
    else:
        lines.extend([
            "## Script generation blocked",
            "",
            "Research approval or evidence validation has not passed.",
            "No factual claims are authorized for script drafting by this brief.",
            "",
        ])

    lines.extend([
        "## Gate errors",
        "",
        *[f"- {error}" for error in report["errors"]],
        "",
        "## Claim-level results",
        "",
    ])

    for item in report["claim_results"]:
        lines.append(
            f"- {item['claim_id']}: {item['status']} — "
            + (", ".join(item["reasons"]) or "OK")
        )

    lines.extend([
        "",
        "## Safety",
        "",
        "- This report does not grant production approval.",
        "- Public upload always requires separate explicit authorization.",
        "- Original research data and human decisions were not modified.",
    ])

    brief_path.write_text("\n".join(lines), encoding="utf-8")

    print("=" * 60)
    print("RESEARCH-TO-SCRIPT GATE v2")
    print("=" * 60)
    print("Video ID:", video_id)
    print("Sources:", report["total_sources"])
    print("Reviewed sources:", report["reviewed_sources"])
    print("Claims:", report["total_claims"])
    print("Eligible claims:", report["eligible_claims"])
    print("Held claims:", report["held_claims"])
    print("Research decision:", report["research_decision"])
    print("Overall:", report["overall_status"])
    print("Report:", report_path)
    print("Brief:", brief_path)
    print("Production approval: NOT GRANTED")
    print("Upload authorization: NOT GRANTED")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", required=True)
    args = parser.parse_args()

    video_id = clean(args.video_id)

    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", video_id):
        parser.error("Invalid video ID.")

    report = audit(video_id)
    write_report(report)

    return 0 if report["overall_status"] == "READY_FOR_CONTROLLED_SCRIPT_DRAFT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
