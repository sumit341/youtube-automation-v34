
from pathlib import Path
from datetime import datetime
import csv
import json
import re

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / "production/runs/E1irX9cDX8U"
WORKSPACE = ROOT / "data/research/youtube_universe_v33/research_workspace_v33/E1irX9cDX8U"


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def first(row, names, default="Not recorded"):
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def latest_draft():
    folders = [
        p for p in (RUN_DIR / "drafts").iterdir()
        if p.is_dir() and (p / "draft_manifest.json").exists()
    ]
    if not folders:
        raise RuntimeError("No generated draft with a manifest was found.")
    return max(folders, key=lambda p: p.name)


def parse_long_sections(text):
    sections = {}
    current_heading = None
    narration_lines = []

    def save():
        if current_heading and narration_lines:
            body = "\n".join(narration_lines).strip()
            if body:
                sections[current_heading] = body

    for line in text.splitlines():
        if line.startswith("## "):
            save()
            current_heading = line[3:].strip()
            narration_lines = []
            continue

        if current_heading is None:
            continue

        if line.strip().lower().startswith("claim mapping:"):
            continue

        if current_heading.lower() in {"draft notes", "claim mapping"}:
            continue

        if line.strip():
            narration_lines.append(line.strip())

    save()
    return sections


def parse_mapping(text):
    mapping = {}
    current_heading = None

    for line in text.splitlines():
        if line.startswith("## "):
            current_heading = line[3:].strip()
            continue

        match = re.match(r"\s*Claim mapping:\s*(.*)", line, re.I)
        if match and current_heading:
            ids = re.findall(r"\bC\d{2}\b", match.group(1).upper())
            mapping[current_heading] = ids

    return mapping


def main():
    draft_dir = latest_draft()
    manifest = read_json(draft_dir / "draft_manifest.json")
    audit = read_json(RUN_DIR / "research_consistency_report.json")

    claims_rows = read_csv(WORKSPACE / "claims.csv")
    sources_rows = read_csv(WORKSPACE / "sources.csv")
    evidence_rows = read_csv(WORKSPACE / "evidence.csv")

    claims = {
        first(r, ["claim_id", "id"]): r
        for r in claims_rows
    }
    sources = {
        first(r, ["source_id", "id"]): r
        for r in sources_rows
    }

    long_text = (draft_dir / "long_video_script_draft.md").read_text(
        encoding="utf-8"
    )
    short_text = (draft_dir / "short_video_script_draft.md").read_text(
        encoding="utf-8"
    )

    long_sections = parse_long_sections(long_text)
    long_mapping = parse_mapping(long_text)

    short_narration = "\n".join(
        line.strip()
        for line in short_text.splitlines()
        if line.strip()
        and not line.startswith("#")
        and not line.lower().startswith("claim mapping:")
        and not line.startswith("-")
    )

    eligible = set(manifest.get("eligible_claim_ids", []))
    held = set(manifest.get("held_claim_ids", []))

    claim_ids = sorted(set(manifest["long_script"]["claim_ids"]) |
                       set(manifest["short_script"]["claim_ids"]))

    review_items = []

    for claim_id in claim_ids:
        claim = claims.get(claim_id, {})
        related_evidence = [
            e for e in evidence_rows
            if first(e, ["claim_id"]) == claim_id
        ]

        source_items = []
        for evidence in related_evidence:
            source_id = first(evidence, ["source_id"])
            source = sources.get(source_id, {})

            source_items.append({
                "evidence_id": first(evidence, ["evidence_id", "id"]),
                "source_id": source_id,
                "source_title": first(source, ["title", "source_title"]),
                "source_url_or_doi": first(
                    source, ["url_or_doi", "url", "doi"]
                ),
                "source_status": first(
                    source, ["review_status", "status"]
                ),
                "source_notes": first(source, ["notes", "review_notes"]),
                "evidence_notes": first(
                    evidence, ["notes", "evidence_note", "description"]
                ),
            })

        mapped_sections = [
            heading for heading, ids in long_mapping.items()
            if claim_id in ids
        ]

        passages = []
        for heading in mapped_sections:
            if heading in long_sections:
                passages.append({
                    "format": "long",
                    "section": heading,
                    "text": long_sections[heading],
                })

        if claim_id in manifest["short_script"]["claim_ids"]:
            passages.append({
                "format": "short",
                "section": "Short narration",
                "text": short_narration,
            })

        review_items.append({
            "claim_id": claim_id,
            "research_claim": first(
                claim,
                ["claim_text", "claim_statement", "statement", "claim"]
            ),
            "research_status": first(claim, ["status", "claim_status"]),
            "limitations": first(
                claim, ["limitations", "limitation", "notes"]
            ),
            "eligible_for_draft": claim_id in eligible,
            "held_by_research_gate": claim_id in held,
            "script_passages": passages,
            "evidence_and_sources": source_items,
            "human_review": {
                "source_identity_confirmed": False,
                "population_and_sample_checked": False,
                "finding_matches_source": False,
                "limitations_preserved": False,
                "script_wording_is_not_overstated": False,
                "reviewer_notes": "",
                "reviewer_name": "",
                "reviewed_at": "",
                "decision": "PENDING",
            },
        })

    report = {
        "report_version": "1.0",
        "created_at": datetime.now().astimezone().isoformat(),
        "topic_id": "E1irX9cDX8U",
        "draft_folder": str(draft_dir),
        "research_gate": audit.get("overall_status", "UNKNOWN"),
        "review_status": "PENDING_HUMAN_REVIEW",
        "claims_in_review": len(review_items),
        "claims": review_items,
        "approval": {
            "fact_review_approved": False,
            "production_approved": False,
            "render_authorized": False,
            "upload_authorized": False,
        },
        "instructions": [
            "Open each source and confirm the exact study or guideline.",
            "Check sample, population, findings and stated limitations.",
            "Compare the source with every mapped script passage.",
            "Do not approve a claim merely because a source URL exists.",
            "Keep uncertain or unsupported claims on HOLD.",
            "Do not change original research CSVs from this report.",
        ],
    }

    json_path = draft_dir / "fact_review_report.json"
    md_path = draft_dir / "fact_review_checklist.md"

    json_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        "# Independent Fact Review Checklist",
        "",
        f"- Topic: {report['topic_id']}",
        f"- Draft: {draft_dir.name}",
        f"- Research gate: {report['research_gate']}",
        "- Review status: PENDING HUMAN REVIEW",
        "- Production approval: NOT GRANTED",
        "- Upload authorization: NOT GRANTED",
        "",
        "## Review instructions",
        "",
        "For every claim, open the cited source and verify the actual finding,",
        "sample, population, limitations and exact script wording.",
        "A source URL alone is not proof of a claim.",
        "",
    ]

    for item in review_items:
        lines += [
            f"## {item['claim_id']}",
            "",
            f"**Research claim:** {item['research_claim']}",
            "",
            f"**Research status:** {item['research_status']}",
            f"**Limitations:** {item['limitations']}",
            f"**Eligible for draft:** {item['eligible_for_draft']}",
            f"**Held by research gate:** {item['held_by_research_gate']}",
            "",
            "### Mapped script passages",
            "",
        ]

        if item["script_passages"]:
            for passage in item["script_passages"]:
                lines += [
                    f"**{passage['format'].upper()} — {passage['section']}**",
                    "",
                    passage["text"],
                    "",
                ]
        else:
            lines += ["No mapped passage found.", ""]

        lines += ["### Sources and evidence", ""]

        if item["evidence_and_sources"]:
            for source in item["evidence_and_sources"]:
                lines += [
                    f"- Evidence: {source['evidence_id']}",
                    f"- Source: {source['source_id']} — {source['source_title']}",
                    f"- URL/DOI: {source['source_url_or_doi']}",
                    f"- Source notes: {source['source_notes']}",
                    f"- Evidence notes: {source['evidence_notes']}",
                    "",
                ]
        else:
            lines += ["- No linked evidence row found.", ""]

        lines += [
            "### Reviewer checklist",
            "",
            "- [ ] Source identity confirmed",
            "- [ ] Population and sample checked",
            "- [ ] Finding matches source",
            "- [ ] Limitations preserved",
            "- [ ] Script wording is not overstated",
            "- Reviewer notes:",
            "- Reviewer name:",
            "- Review date:",
            "- Decision: PENDING / APPROVE / HOLD / REJECT",
            "",
        ]

    md_path.write_text("\n".join(lines), encoding="utf-8")

    print("FACT REVIEW PACKET CREATED")
    print("=" * 55)
    print("Draft:", draft_dir)
    print("Claims:", len(review_items))
    print("JSON:", json_path)
    print("Checklist:", md_path)
    print("Review status: PENDING HUMAN REVIEW")
    print("Production approval: NOT GRANTED")
    print("Upload authorization: NOT GRANTED")


if __name__ == "__main__":
    main()
