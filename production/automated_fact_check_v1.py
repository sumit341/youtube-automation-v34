from pathlib import Path
from datetime import datetime
import csv
import json
import re

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / "production/runs/E1irX9cDX8U"
WORKSPACE = ROOT / "data/research/youtube_universe_v33/research_workspace_v33/E1irX9cDX8U"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def latest_draft():
    files = list((RUN_DIR / "drafts").glob("*/draft_manifest.json"))
    if not files:
        raise RuntimeError("No draft manifest found.")
    return max(files, key=lambda p: p.stat().st_mtime)


def extract_long(text):
    sections = {}
    heading = None
    lines = []

    def save():
        if heading and heading.upper() != "DRAFT NOTES":
            sections[heading] = "\n".join(lines).strip()

    for line in text.splitlines():
        if line.startswith("## "):
            save()
            heading = line[3:].strip()
            lines = []
        elif heading and not line.strip().lower().startswith("claim mapping:"):
            lines.append(line)

    save()
    return sections


def extract_long_mapping(text):
    mapping = {}
    heading = None

    for line in text.splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
        elif line.strip().lower().startswith("claim mapping:") and heading:
            mapping[heading] = re.findall(r"\bC\d{2}\b", line.upper())

    return mapping


def extract_short(text):
    lines = []
    for line in text.splitlines():
        if not line.strip() or line.startswith("#") or line.startswith("-"):
            continue
        if line.strip().lower().startswith("claim mapping:"):
            continue
        lines.append(line.strip())
    return "\n".join(lines)


def add(checks, name, passed, detail, severity="BLOCKER"):
    checks.append({
        "name": name,
        "passed": bool(passed),
        "severity": severity,
        "detail": str(detail),
    })


def main():
    manifest_path = latest_draft()
    draft_dir = manifest_path.parent
    manifest = read_json(manifest_path)

    audit = read_json(RUN_DIR / "research_consistency_report.json")
    claims_rows = read_csv(WORKSPACE / "claims.csv")
    evidence_rows = read_csv(WORKSPACE / "evidence.csv")
    source_rows = read_csv(WORKSPACE / "sources.csv")

    long_path = draft_dir / manifest["long_script"]["file"]
    short_path = draft_dir / manifest["short_script"]["file"]

    long_text = long_path.read_text(encoding="utf-8")
    short_text = short_path.read_text(encoding="utf-8")

    long_sections = extract_long(long_text)
    long_mapping = extract_long_mapping(long_text)
    short_narration = extract_short(short_text)

    claims = {r["claim_id"]: r for r in claims_rows}
    sources = {r["source_id"]: r for r in source_rows}
    audit_claims = {r["claim_id"]: r for r in audit.get("claim_results", [])}

    checks = []
    used_claims = set()

    add(
        checks,
        "RESEARCH_GATE",
        audit.get("overall_status") == "READY_FOR_CONTROLLED_DRAFT",
        audit.get("overall_status", "MISSING"),
    )

    add(
        checks,
        "DRAFT_TOPIC_MATCH",
        manifest.get("topic_id") == audit.get("topic_id"),
        f"Draft={manifest.get('topic_id')}; audit={audit.get('topic_id')}",
    )

    for heading, claim_ids in long_mapping.items():
        passage = long_sections.get(heading, "")

        add(
            checks,
            f"LONG_SECTION_MAPPING_{heading}",
            bool(passage) and bool(claim_ids),
            f"Passage present={bool(passage)}; claims={claim_ids}",
        )

        for claim_id in claim_ids:
            used_claims.add(claim_id)

    short_ids = set(manifest.get("short_script", {}).get("claim_ids", []))
    used_claims.update(short_ids)

    add(
        checks,
        "SHORT_SCRIPT_MAPPING",
        bool(short_ids) and bool(short_narration),
        f"Claims={sorted(short_ids)}; narration present={bool(short_narration)}",
    )

    for claim_id in sorted(used_claims):
        claim = claims.get(claim_id)
        audited = audit_claims.get(claim_id)

        add(
            checks,
            f"{claim_id}_EXISTS",
            claim is not None and audited is not None,
            "Claim exists in CSV and audit." if claim and audited else "Claim missing from CSV or audit.",
        )

        if not claim or not audited:
            continue

        add(
            checks,
            f"{claim_id}_AUDIT_ELIGIBILITY",
            audited.get("status") == "ELIGIBLE_FOR_DRAFT",
            f"Audit status={audited.get('status')}",
        )

        add(
            checks,
            f"{claim_id}_LIMITATIONS_RECORDED",
            bool(claim.get("limitations", "").strip()) and bool(audited.get("limitations", "").strip()),
            "Limitations must exist in both research CSV and audit.",
        )

        linked_ids = set(audited.get("evidence_ids", []))
        linked_evidence = [
            e for e in evidence_rows
            if e.get("evidence_id") in linked_ids
            and e.get("claim_id") == claim_id
        ]

        add(
            checks,
            f"{claim_id}_EVIDENCE_LINK",
            bool(linked_ids) and bool(linked_evidence),
            f"Audit evidence IDs={sorted(linked_ids)}; matched CSV rows={len(linked_evidence)}",
        )

        valid_evidence = []
        for ev in linked_evidence:
            source = sources.get(ev.get("source_id"), {})
            evidence_ok = (
                ev.get("evidence_relation", "").upper() == "SUPPORTS"
                and ev.get("review_status", "").upper() == "REVIEWED"
                and bool(ev.get("evidence_summary", "").strip())
                and bool(ev.get("source_locator", "").strip())
            )
            source_ok = (
                source.get("source_review_status", "").upper() == "REVIEWED"
                and bool(source.get("title", "").strip())
                and bool(source.get("url_or_doi", "").strip())
            )

            if evidence_ok and source_ok:
                valid_evidence.append(ev["evidence_id"])

        add(
            checks,
            f"{claim_id}_SOURCE_EVIDENCE_STATUS",
            bool(valid_evidence),
            f"Valid reviewed evidence rows={valid_evidence}",
        )

        passages = []
        for heading, ids in long_mapping.items():
            if claim_id in ids and long_sections.get(heading):
                passages.append(long_sections[heading])

        if claim_id in short_ids and short_narration:
            passages.append(short_narration)

        add(
            checks,
            f"{claim_id}_SCRIPT_PASSAGE_EXISTS",
            bool(passages),
            f"Mapped passages={len(passages)}",
        )

        # Deterministic warning for obvious causal overstatement
        claim_type = claim.get("claim_type", "").upper()
        combined = " ".join(passages).lower()

        if claim_type == "EMPIRICAL_ASSOCIATION":
            causal_patterns = [
                r"\bcauses?\s+(?:insomnia|sleep impairment|sleep problems?)",
                r"\bleads?\s+to\s+(?:insomnia|sleep impairment)",
                r"\bresults?\s+in\s+(?:insomnia|sleep impairment)",
                r"\boverthinking\s+is\s+the\s+cause\b",
                r"\b(?:insomnia|sleep problems?)\s+ki wajah se overthinking\b",
            ]
            risky = [p for p in causal_patterns if re.search(p, combined)]

            add(
                checks,
                f"{claim_id}_CAUSAL_LANGUAGE",
                not risky,
                f"Potential causal overstatement patterns={risky}",
            )

    blockers = [
        c for c in checks
        if not c["passed"] and c["severity"] == "BLOCKER"
    ]
    warnings = [
        c for c in checks
        if not c["passed"] and c["severity"] == "WARNING"
    ]

    status = "FAIL" if blockers else "HOLD" if warnings else "PASS"

    report = {
        "report_version": "1.0",
        "checker": "deterministic_evidence_traceability",
        "created_at": datetime.now().astimezone().isoformat(),
        "topic_id": audit.get("topic_id"),
        "draft_directory": str(draft_dir),
        "status": status,
        "claims_checked": len(used_claims),
        "passed_checks": sum(c["passed"] for c in checks),
        "total_checks": len(checks),
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "limitations": [
            "This module validates evidence traceability and configured wording risks.",
            "It does not independently retrieve or semantically verify source documents.",
            "A PASS is not proof of scientific truth or independent peer review.",
            "No production, rendering or upload authorization is granted.",
        ],
        "safety": {
            "fact_review_approved": False,
            "production_approved": False,
            "render_authorized": False,
            "upload_authorized": False,
        },
    }

    out = draft_dir / "automated_fact_check_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("AUTOMATED FACT CHECK v1")
    print("=" * 55)
    print("Draft:", draft_dir)
    print("Status:", status)
    print("Claims checked:", len(used_claims))
    print("Checks:", report["passed_checks"], "/", report["total_checks"])

    for item in checks:
        label = "PASS" if item["passed"] else item["severity"]
        print(f"{label:8} | {item['name']} | {item['detail']}")

    print("Report:", out)
    print("Production approval: NOT GRANTED")
    print("Upload authorization: NOT GRANTED")


if __name__ == "__main__":
    main()
