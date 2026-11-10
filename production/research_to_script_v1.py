
from pathlib import Path
from datetime import datetime
import csv
import json
import re

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "data/research/youtube_universe_v33/research_workspace_v33/E1irX9cDX8U"
OUTPUT = ROOT / "production/runs/E1irX9cDX8U"

FILES = {
    "sources": WORKSPACE / "sources.csv",
    "claims": WORKSPACE / "claims.csv",
    "evidence": WORKSPACE / "evidence.csv",
}


def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(path)

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def clean(value):
    return (value or "").strip()


def audit():
    sources = read_csv(FILES["sources"])
    claims = read_csv(FILES["claims"])
    evidence = read_csv(FILES["evidence"])

    source_map = {clean(x.get("source_id")): x for x in sources}
    claim_map = {clean(x.get("claim_id")): x for x in claims}

    claim_results = []

    for claim_id, claim in claim_map.items():
        reasons = []
        linked = [
            e for e in evidence
            if clean(e.get("claim_id")) == claim_id
        ]

        if clean(claim.get("claim_status")).upper() != "SUPPORTED":
            reasons.append("CLAIM_NOT_MARKED_SUPPORTED")

        if not linked:
            reasons.append("NO_LINKED_EVIDENCE")

        for item in linked:
            source_id = clean(item.get("source_id"))
            source = source_map.get(source_id)

            if not source:
                reasons.append(f"SOURCE_NOT_FOUND:{source_id}")
                continue

            if clean(source.get("source_review_status")).upper() != "REVIEWED":
                reasons.append(f"SOURCE_NOT_REVIEWED:{source_id}")

            if clean(item.get("review_status")).upper() != "REVIEWED":
                reasons.append(f"EVIDENCE_NOT_REVIEWED:{item.get('evidence_id')}")

            if clean(item.get("evidence_relation")).upper() != "SUPPORTS":
                reasons.append(f"EVIDENCE_NOT_SUPPORTING:{item.get('evidence_id')}")

            if not clean(item.get("source_locator")):
                reasons.append(f"SOURCE_LOCATOR_MISSING:{item.get('evidence_id')}")

            if not clean(source.get("url_or_doi")):
                reasons.append(f"SOURCE_URL_MISSING:{source_id}")

            # Known numerical/category contradiction in this pilot:
            # source says 12 publications = 10 articles + 2 book chapters.
            if (
                source_id == "S03"
                and "12 articles" in clean(item.get("evidence_summary")).lower()
                and "10 journal articles" in clean(source.get("notes")).lower()
                and "2 book chapters" in clean(source.get("notes")).lower()
            ):
                reasons.append("PUBLICATION_COUNT_TYPE_MISMATCH")

        claim_results.append({
            "claim_id": claim_id,
            "claim_text": clean(claim.get("claim_text")),
            "status": "HOLD" if reasons else "ELIGIBLE_FOR_DRAFT",
            "reasons": sorted(set(reasons)),
            "evidence_ids": [
                clean(e.get("evidence_id")) for e in linked
            ],
            "source_ids": [
                clean(e.get("source_id")) for e in linked
            ],
            "limitations": clean(claim.get("limitations")),
        })

    return {
        "audit_version": "1.0",
        "topic_id": "E1irX9cDX8U",
        "generated_at": datetime.now().astimezone().isoformat(),
        "total_claims": len(claim_results),
        "eligible_claims": sum(
            x["status"] == "ELIGIBLE_FOR_DRAFT" for x in claim_results
        ),
        "held_claims": sum(
            x["status"] == "HOLD" for x in claim_results
        ),
        "overall_status": (
            "READY_FOR_CONTROLLED_DRAFT"
            if any(x["status"] == "ELIGIBLE_FOR_DRAFT" for x in claim_results)
            else "HOLD"
        ),
        "claim_results": claim_results,
        "safety": {
            "original_research_files_modified": False,
            "human_decisions_modified": False,
            "production_approved": False,
            "youtube_upload_authorized": False,
        },
    }


def write_outputs(report):
    OUTPUT.mkdir(parents=True, exist_ok=True)

    report_path = OUTPUT / "research_consistency_report.json"
    brief_path = OUTPUT / "script_input_brief.md"

    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    eligible = [
        x for x in report["claim_results"]
        if x["status"] == "ELIGIBLE_FOR_DRAFT"
    ]

    held = [
        x for x in report["claim_results"]
        if x["status"] == "HOLD"
    ]

    lines = [
        "# Controlled Script Input Brief",
        "",
        f"Topic ID: {report['topic_id']}",
        f"Audit status: {report['overall_status']}",
        "",
        "## Eligible factual claims",
        "",
    ]

    for item in eligible:
        lines.extend([
            f"### {item['claim_id']}",
            item["claim_text"],
            f"Evidence IDs: {', '.join(item['evidence_ids'])}",
            f"Source IDs: {', '.join(item['source_ids'])}",
            f"Limitations: {item['limitations']}",
            "",
        ])

    lines.extend(["## Excluded / held claims", ""])

    for item in held:
        lines.extend([
            f"### {item['claim_id']}",
            f"Reason: {', '.join(item['reasons'])}",
            item["claim_text"],
            "",
        ])

    lines.extend([
        "## Drafting restrictions",
        "",
        "- Use conversational Roman Hinglish.",
        "- Do not invent statistics, studies, quotations or citations.",
        "- Preserve every claim's population and context.",
        "- Do not turn association into causation.",
        "- Preserve limitations and uncertainty.",
        "- Do not use held claims as factual statements.",
        "- Every factual statement must map to an eligible claim ID.",
        "- This brief does not grant production or upload approval.",
    ])

    brief_path.write_text("\n".join(lines), encoding="utf-8")

    print("RESEARCH CONSISTENCY AUDIT")
    print("=" * 55)
    print("Total claims:", report["total_claims"])
    print("Eligible:", report["eligible_claims"])
    print("Held:", report["held_claims"])
    print("Overall:", report["overall_status"])

    for item in report["claim_results"]:
        print(
            item["claim_id"],
            "|",
            item["status"],
            "|",
            ", ".join(item["reasons"]) or "OK",
        )

    print()
    print("REPORT:", report_path)
    print("BRIEF:", brief_path)
    print("Original research files: UNCHANGED")
    print("Production approval: NOT GRANTED")


def main():
    report = audit()
    write_outputs(report)


if __name__ == "__main__":
    main()
