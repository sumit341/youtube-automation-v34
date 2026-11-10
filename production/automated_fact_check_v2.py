from pathlib import Path
from datetime import datetime
import argparse
import csv
import json
import re

ROOT = Path(__file__).resolve().parent.parent


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def locate_workspace(topic_id):
    matches = list((ROOT / "data" / "research").rglob("claims.csv"))
    for claims_path in matches:
        if claims_path.parent.name == topic_id:
            required = [
                claims_path,
                claims_path.parent / "evidence.csv",
                claims_path.parent / "sources.csv",
            ]
            if all(path.exists() for path in required):
                return claims_path.parent
    raise FileNotFoundError(
        f"Research workspace with claims/evidence/sources not found for {topic_id}"
    )


def latest_draft(run_dir):
    manifests = list((run_dir / "drafts").glob("*/draft_manifest.json"))
    if not manifests:
        raise FileNotFoundError(f"No draft manifest found under {run_dir / 'drafts'}")
    return max(manifests, key=lambda path: path.stat().st_mtime)


def add(checks, name, passed, detail, severity="BLOCKER"):
    checks.append({
        "name": name,
        "passed": bool(passed),
        "severity": severity,
        "detail": str(detail),
    })


def parse_long(text):
    sections = {}
    mappings = {}
    heading = None
    body = []

    def save():
        if heading and heading.upper() != "DRAFT NOTES":
            sections[heading] = "\n".join(body).strip()

    for line in text.splitlines():
        if line.startswith("## "):
            save()
            heading = line[3:].strip()
            body = []
        elif heading:
            if line.strip().lower().startswith("claim mapping:"):
                mappings[heading] = re.findall(r"\bC\d{2}\b", line.upper())
            elif heading.upper() != "DRAFT NOTES":
                body.append(line)

    save()
    return sections, mappings


def parse_short(text, manifest):
    narration = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            continue
        if stripped.lower().startswith("claim mapping:"):
            continue
        narration.append(stripped)
    claim_ids = set(manifest.get("short_script", {}).get("claim_ids", []))
    return "\n".join(narration), claim_ids


def normalize_numbers(text):
    return {
        token.replace(",", "")
        for token in re.findall(r"-?\d[\d,]*(?:\.\d+)?", text or "")
    }


def numeric_fact_phrases(text):
    patterns = [
        r"\b\d[\d,]*(?:\.\d+)?\s*(?:participants?|undergraduates?|students?|studies|trials|"
        r"randomized controlled trials|effect sizes|adults?|publications?|models?|"
        r"cognitive factors)\b",
        r"\bN\s*=\s*\d[\d,]*(?:\.\d+)?",
        r"\bHedges\s*g\s*(?:of|=|~|approximately)?\s*-?\d+(?:\.\d+)?",
        r"\bg\s*=\s*-?\d+(?:\.\d+)?",
    ]
    found = []
    for pattern in patterns:
        found.extend(re.findall(pattern, text or "", flags=re.I))
    return found


def causal_patterns():
    return [
        r"\bcauses?\s+(?:insomnia|sleep impairment|sleep problems?|overthinking)\b",
        r"\bleads?\s+to\s+(?:insomnia|sleep impairment|sleep problems?)\b",
        r"\bresults?\s+in\s+(?:insomnia|sleep impairment|sleep problems?)\b",
        r"\b(?:overthinking|worry|rumination)\s+(?:directly\s+)?causes?\b",
        r"\bproves?\s+that\b",
        r"\b(?:insomnia|sleep problems?)\s+ki wajah se overthinking\b",
        r"\boverthinking\s+ki wajah se\s+(?:insomnia|sleep problems?)\b",
        r"\bisse\s+insomnia\s+hoti\s+hai\b",
    ]


def main():
    parser = argparse.ArgumentParser(
        description="Deterministic claim/evidence/script consistency gate."
    )
    parser.add_argument("--topic-id", default="E1irX9cDX8U")
    args = parser.parse_args()

    topic_id = args.topic_id
    run_dir = ROOT / "production" / "runs" / topic_id
    audit_path = run_dir / "research_consistency_report.json"
    if not audit_path.exists():
        raise FileNotFoundError(audit_path)

    workspace = locate_workspace(topic_id)
    manifest_path = latest_draft(run_dir)
    draft_dir = manifest_path.parent
    manifest = read_json(manifest_path)
    audit = read_json(audit_path)

    long_path = draft_dir / manifest["long_script"]["file"]
    short_path = draft_dir / manifest["short_script"]["file"]
    long_text = long_path.read_text(encoding="utf-8-sig")
    short_text = short_path.read_text(encoding="utf-8-sig")

    sections, mappings = parse_long(long_text)
    short_narration, short_ids = parse_short(short_text, manifest)

    claims = {row["claim_id"]: row for row in read_csv(workspace / "claims.csv")}
    evidence_rows = read_csv(workspace / "evidence.csv")
    sources = {row["source_id"]: row for row in read_csv(workspace / "sources.csv")}
    audit_claims = {
        row["claim_id"]: row
        for row in audit.get("claim_results", [])
        if row.get("claim_id")
    }

    checks = []
    used_ids = set(short_ids)
    mapped_passages = {}

    add(
        checks, "RESEARCH_GATE",
        audit.get("overall_status") == "READY_FOR_CONTROLLED_DRAFT",
        audit.get("overall_status", "MISSING"),
    )
    add(
        checks, "TOPIC_ID_MATCH",
        manifest.get("topic_id") == topic_id == audit.get("topic_id"),
        f"Requested={topic_id}; manifest={manifest.get('topic_id')}; audit={audit.get('topic_id')}",
    )

    narrative_headings = [
        heading for heading in sections
        if heading.upper() not in {"DRAFT NOTES", "CLAIM MAPPING"}
    ]
    add(
        checks, "LONG_SECTION_MAPPING_COVERAGE",
        bool(narrative_headings)
        and all(heading in mappings and mappings[heading] for heading in narrative_headings),
        f"Mapped sections={sum(bool(mappings.get(h)) for h in narrative_headings)}/{len(narrative_headings)}",
    )

    for heading, ids in mappings.items():
        passage = sections.get(heading, "")
        add(
            checks, f"SECTION_{heading}_HAS_TEXT_AND_CLAIMS",
            bool(passage.strip()) and bool(ids),
            f"Text present={bool(passage.strip())}; mapped claims={ids}",
        )
        for claim_id in ids:
            used_ids.add(claim_id)
            mapped_passages.setdefault(claim_id, []).append(
                {
                    "format": "long",
                    "section": heading,
                    "text": passage,
                    "claim_ids": list(ids),
                }
            )

    add(
        checks, "SHORT_SCRIPT_MAPPING",
        bool(short_ids) and bool(short_narration.strip()),
        f"Claim IDs={sorted(short_ids)}; narration present={bool(short_narration.strip())}",
    )
    for claim_id in short_ids:
        mapped_passages.setdefault(claim_id, []).append(
            {
                "format": "short",
                "section": "Short narration",
                "text": short_narration,
                "claim_ids": sorted(short_ids),
            }
        )

    for claim_id in sorted(used_ids):
        claim = claims.get(claim_id)
        audited = audit_claims.get(claim_id)

        add(
            checks, f"{claim_id}_EXISTS",
            claim is not None and audited is not None,
            "Claim found in CSV and research audit." if claim and audited
            else "Claim missing from CSV or research audit.",
        )
        if not claim or not audited:
            continue

        add(
            checks, f"{claim_id}_ELIGIBLE",
            audited.get("status") == "ELIGIBLE_FOR_DRAFT",
            f"Audit status={audited.get('status')}",
        )

        limitation = (claim.get("limitations") or "").strip()
        audit_limitation = (audited.get("limitations") or "").strip()
        add(
            checks, f"{claim_id}_LIMITATIONS_RECORDED",
            bool(limitation and audit_limitation),
            f"CSV limitation present={bool(limitation)}; audit limitation present={bool(audit_limitation)}",
        )

        evidence_ids = set(audited.get("evidence_ids", []))
        linked = [
            row for row in evidence_rows
            if row.get("evidence_id") in evidence_ids
            and row.get("claim_id") == claim_id
        ]
        add(
            checks, f"{claim_id}_EVIDENCE_LINK",
            bool(evidence_ids) and bool(linked),
            f"Audit IDs={sorted(evidence_ids)}; matching evidence rows={len(linked)}",
        )

        valid_context = []
        for ev in linked:
            source = sources.get(ev.get("source_id"), {})
            if (
                ev.get("evidence_relation", "").upper() == "SUPPORTS"
                and ev.get("review_status", "").upper() == "REVIEWED"
                and source.get("source_review_status", "").upper() == "REVIEWED"
                and ev.get("evidence_summary", "").strip()
                and source.get("title", "").strip()
                and source.get("url_or_doi", "").strip()
            ):
                valid_context.append(
                    " ".join([
                        ev.get("evidence_summary", ""),
                        ev.get("notes", ""),
                        source.get("title", ""),
                        source.get("notes", ""),
                    ])
                )

        add(
            checks, f"{claim_id}_REVIEWED_SOURCE_EVIDENCE",
            bool(valid_context),
            f"Valid reviewed evidence records={len(valid_context)}",
        )

        passages = mapped_passages.get(claim_id, [])
        add(
            checks, f"{claim_id}_HAS_MAPPED_PASSAGE",
            bool(passages),
            f"Mapped passages={len(passages)}",
        )
        if not passages or not valid_context:
            continue

        claim_type = (claim.get("claim_type") or "").upper()
        passage_text = " ".join(item["text"] for item in passages)
        passage_lower = passage_text.lower()
        context_text = " ".join(valid_context + [claim.get("claim_text", "")])
        # Build evidence context separately for each passage.
        # Only claims explicitly mapped to this passage may support it.
        def context_for_passage(item):
            mapped_ids = set(item.get("claim_ids") or [claim_id])
            mapped_ids.add(claim_id)
            context_parts = []

            for mapped_id in sorted(mapped_ids):
                mapped_claim = claims.get(mapped_id, {})
                mapped_audit = audit_claims.get(mapped_id, {})
                context_parts.append(mapped_claim.get("claim_text", ""))

                mapped_evidence_ids = set(
                    mapped_audit.get("evidence_ids", [])
                )

                for mapped_ev in evidence_rows:
                    if (
                        mapped_ev.get("evidence_id") not in mapped_evidence_ids
                        or mapped_ev.get("claim_id") != mapped_id
                    ):
                        continue

                    mapped_source = sources.get(
                        mapped_ev.get("source_id"), {}
                    )

                    if (
                        mapped_ev.get("evidence_relation", "").upper() == "SUPPORTS"
                        and mapped_ev.get("review_status", "").upper() == "REVIEWED"
                        and mapped_source.get("source_review_status", "").upper() == "REVIEWED"
                        and mapped_ev.get("evidence_summary", "").strip()
                        and mapped_source.get("title", "").strip()
                        and mapped_source.get("url_or_doi", "").strip()
                    ):
                        context_parts.extend([
                            mapped_ev.get("evidence_summary", ""),
                            mapped_ev.get("notes", ""),
                            mapped_source.get("title", ""),
                            mapped_source.get("notes", ""),
                        ])

            return " ".join(context_parts)

        if claim_type == "EMPIRICAL_ASSOCIATION":
            risky = [
                pattern for pattern in causal_patterns()
                if re.search(pattern, passage_lower, flags=re.I)
            ]
            add(
                checks, f"{claim_id}_CAUSAL_OVERSTATEMENT",
                not risky,
                f"Potentially risky patterns={risky}",
            )

        # Numeric and population checks are evaluated passage by passage.
        unsupported_numeric = []
        unsupported_populations = []

        population_terms = [
            "undergraduate", "undergraduates", "students", "children",
            "adolescents", "older adults", "adults", "patients",
            "people with insomnia", "people with sleep problems",
        ]

        population_aliases = {
            "students": ("student", "students", "undergraduate", "undergraduates"),
            "undergraduate": ("undergraduate", "undergraduates", "student", "students"),
            "undergraduates": ("undergraduate", "undergraduates", "student", "students"),
        }

        for passage_item in passages:
            item_text = passage_item.get("text", "")
            item_lower = item_text.lower()
            item_context = context_for_passage(passage_item)
            item_context_lower = item_context.lower()
            section_name = passage_item.get("section", "passage")

            for phrase in numeric_fact_phrases(item_text):
                phrase_numbers = normalize_numbers(phrase)
                context_numbers = normalize_numbers(item_context)

                if not phrase_numbers.issubset(context_numbers):
                    unsupported_numeric.append(
                        f"{section_name}: {phrase}"
                    )

            item_populations = [
                term for term in population_terms if term in item_lower
            ]

            for term in item_populations:
                aliases = population_aliases.get(term, (term,))
                if not any(alias in item_context_lower for alias in aliases):
                    unsupported_populations.append(
                        f"{section_name}: {term}"
                    )

        add(
            checks, f"{claim_id}_NUMERIC_FACT_TRACEABILITY",
            not unsupported_numeric,
            f"Unmatched study/statistical quantities={unsupported_numeric}",
            "WARNING",
        )

        add(
            checks, f"{claim_id}_POPULATION_TRACEABILITY",
            not unsupported_populations,
            f"Population terms absent from passage-mapped evidence={unsupported_populations}",
            "WARNING",
        )

        if claim_type == "EMPIRICAL_ASSOCIATION":
            qualification_terms = [
                "association", "associated", "not causal", "does not prove",
                "doesn't prove", "not prove", "not mean", "not universal",
                "cannot conclude", "cannot be concluded",
            ]
            has_qualification = any(term in passage_lower for term in qualification_terms)
            add(
                checks, f"{claim_id}_ASSOCIATION_QUALIFICATION",
                has_qualification,
                "Association/correlation qualification detected in mapped passage."
                if has_qualification else "No configured association qualification phrase detected.",
                "WARNING",
            )

    blockers = [
        item for item in checks
        if not item["passed"] and item["severity"] == "BLOCKER"
    ]
    warnings = [
        item for item in checks
        if not item["passed"] and item["severity"] == "WARNING"
    ]
    status = "FAIL" if blockers else "HOLD" if warnings else "PASS"

    report = {
        "report_version": "2.3",
        "checker": "deterministic_claim_evidence_consistency",
        "created_at": datetime.now().astimezone().isoformat(),
        "topic_id": topic_id,
        "draft_directory": str(draft_dir),
        "status": status,
        "claims_checked": len(used_ids),
        "passed_checks": sum(item["passed"] for item in checks),
        "total_checks": len(checks),
        "blockers": blockers,
        "warnings": warnings,
        "checks": checks,
        "limitations": [
            "This is a deterministic consistency and traceability gate, not an AI semantic fact verifier.",
            "It does not independently fetch or appraise full source documents.",
            "Numeric and population checks use configured text matching and may require review when phrasing differs.",
            "A PASS is not proof of scientific truth.",
            "No production, rendering, or upload authorization is granted.",
        ],
        "safety": {
            "fact_review_approved": False,
            "production_approved": False,
            "render_authorized": False,
            "upload_authorized": False,
        },
    }

    output = draft_dir / "automated_fact_check_v2_report.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("AUTOMATED FACT CHECK v2")
    print("=" * 60)
    print("Topic:", topic_id)
    print("Draft:", draft_dir)
    print("Status:", status)
    print("Claims checked:", len(used_ids))
    print("Checks:", report["passed_checks"], "/", report["total_checks"])
    print("Blockers:", len(blockers))
    print("Warnings:", len(warnings))
    for item in checks:
        label = "PASS" if item["passed"] else item["severity"]
        print(f"{label:8} | {item['name']} | {item['detail']}")
    print("Report:", output)
    print("Production approval: NOT GRANTED")
    print("Upload authorization: NOT GRANTED")


if __name__ == "__main__":
    main()
