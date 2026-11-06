
import csv
import json
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "research" / "youtube_universe_v33"
APP = ROOT / "app"

OUTPUT_CSV = DATA / "latest_master_dashboard_v33.csv"
OUTPUT_JSON = DATA / "latest_master_dashboard_report_v33.json"
OUTPUT_MD = DATA / "latest_master_dashboard_v33.md"

BACKUP_DIR = ROOT / "backups" / (
    "batch9_master_dashboard_" + datetime.now().strftime("%Y%m%d_%H%M%S")
)

FILES = {
    "ranking": "latest_candidate_ranking_v33.csv",
    "human_queue": "latest_human_review_queue_v33.csv",
    "human_audit": "latest_human_review_audit_v33.csv",
    "research_queue": "latest_research_workbench_queue_v33.csv",
    "research_decisions": "research_review_decisions_v33.csv",
    "package_queue": "latest_research_package_queue_v33.csv",
    "final_audit": "latest_final_audit_v33.csv",
}

def read_csv(name):
    path = DATA / name
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))

def clean(value):
    if value is None:
        return ""
    return str(value).strip()

def make_index(rows, label, integrity):
    if rows is None:
        integrity["missing_files"].append(label)
        return {}

    counts = Counter(clean(row.get("video_id")) for row in rows)
    duplicates = sorted(
        video_id for video_id, count in counts.items()
        if video_id and count > 1
    )

    if duplicates:
        integrity["duplicate_ids"][label] = duplicates

    # Ambiguous duplicate IDs are deliberately excluded.
    return {
        clean(row.get("video_id")): row
        for row in rows
        if clean(row.get("video_id"))
        and counts[clean(row.get("video_id"))] == 1
    }

def count_values(rows, field, default="NOT_RECORDED"):
    result = Counter()
    for row in rows:
        value = clean(row.get(field)) or default
        result[value] += 1
    return dict(sorted(result.items()))

def number(value):
    try:
        if value is None or clean(value) == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

def write_csv(path, rows):
    if not rows:
        raise RuntimeError("Dashboard output has no rows; refusing to write CSV.")

    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

def main():
    print("=" * 72)
    print("YOUTUBE UNIVERSE V3.3 - MASTER RESEARCH DASHBOARD")
    print("=" * 72)

    if not DATA.exists():
        raise SystemExit("ERROR: V3.3 data directory not found: " + str(DATA))

    integrity = {
        "missing_files": [],
        "duplicate_ids": {},
        "orphan_ids": {},
        "missing_join_records": {},
        "canonical_duplicate_ids": [],
        "canonical_rows": 0,
        "canonical_unique_ids": 0,
    }

    datasets = {}
    for key, filename in FILES.items():
        datasets[key] = read_csv(filename)

    ranking = datasets["ranking"]
    if ranking is None:
        raise SystemExit("ERROR: Canonical ranking CSV is missing.")

    canonical_counts = Counter(
        clean(row.get("video_id")) for row in ranking
        if clean(row.get("video_id"))
    )
    canonical_duplicates = sorted(
        video_id for video_id, count in canonical_counts.items()
        if count > 1
    )

    integrity["canonical_rows"] = len(ranking)
    integrity["canonical_unique_ids"] = len(canonical_counts)
    integrity["canonical_duplicate_ids"] = canonical_duplicates

    if canonical_duplicates:
        raise SystemExit(
            "STOP: Duplicate video_id values found in canonical ranking. "
            "No dashboard outputs were written."
        )

    if len(canonical_counts) != len(ranking):
        raise SystemExit(
            "STOP: Canonical ranking contains blank video_id values."
        )

    indexes = {}
    for key in [
        "human_queue",
        "human_audit",
        "research_queue",
        "research_decisions",
        "package_queue",
    ]:
        indexes[key] = make_index(
            datasets[key], FILES[key], integrity
        )

    base_ids = set(canonical_counts)

    for key, index in indexes.items():
        extra = sorted(set(index) - base_ids)
        missing = sorted(base_ids - set(index))

        if extra:
            integrity["orphan_ids"][FILES[key]] = extra

        if missing:
            integrity["missing_join_records"][FILES[key]] = len(missing)

    final_audit = datasets["final_audit"]
    final_audit_index = make_index(
        final_audit, FILES["final_audit"], integrity
    )

    if final_audit is not None:
        audit_ids = {
            clean(row.get("video_id")) for row in final_audit
            if clean(row.get("video_id"))
        }
        extra = sorted(audit_ids - base_ids)
        missing = sorted(base_ids - audit_ids)

        if extra:
            integrity["orphan_ids"][FILES["final_audit"]] = extra
        if missing:
            integrity["missing_join_records"][FILES["final_audit"]] = len(missing)

    dashboard = []

    for base in ranking:
        video_id = clean(base.get("video_id"))

        human_audit_row = indexes["human_audit"].get(video_id)
        human_queue_row = indexes["human_queue"].get(video_id)
        research_row = indexes["research_queue"].get(video_id)
        research_decision_row = indexes["research_decisions"].get(video_id)
        package_row = indexes["package_queue"].get(video_id)

        # Human review comes from its dedicated audit/queue,
        # never from the final audit's ambiguous human_decision field.
        if human_audit_row is not None:
            human_decision = clean(human_audit_row.get("decision")) or "NOT_RECORDED"
            human_notes = clean(human_audit_row.get("reviewer_notes"))
            human_reason = clean(human_audit_row.get("decision_reason"))
        elif human_queue_row is not None:
            human_decision = clean(human_queue_row.get("review_decision")) or "NOT_RECORDED"
            human_notes = clean(human_queue_row.get("reviewer_notes"))
            human_reason = clean(human_queue_row.get("decision_reason"))
        else:
            human_decision = "NOT_RECORDED"
            human_notes = ""
            human_reason = ""

        topic_decision = (
            clean(research_row.get("topic_decision"))
            if research_row else "NOT_RECORDED"
        ) or "NOT_RECORDED"

        research_decision = (
            clean(research_decision_row.get("research_decision"))
            if research_decision_row else "NOT_RECORDED"
        ) or "NOT_RECORDED"

        workspace_status = (
            clean(research_row.get("workspace_status"))
            if research_row else "NOT_RECORDED"
        ) or "NOT_RECORDED"

        research_gate = (
            clean(research_row.get("research_gate"))
            if research_row else "NOT_RECORDED"
        ) or "NOT_RECORDED"

        package_status = (
            clean(package_row.get("package_status"))
            if package_row else "NOT_RECORDED"
        ) or "NOT_RECORDED"

        # Production approval is intentionally blocked in this dashboard.
        # Topic/research approval is not production approval.
        production_approval = "NO"
        production_gate = "BLOCKED"

        dashboard.append({
            "rank": clean(base.get("rank")),
            "video_id": video_id,
            "title": clean(base.get("title")),
            "relevance_score": clean(base.get("relevance_score")),
            "performance_score": clean(base.get("performance_score")),
            "format_score": clean(base.get("format_score")),
            "ranking_score": clean(base.get("ranking_score")),
            "ranking_status": clean(base.get("ranking_status")),
            "relevance_status": clean(base.get("relevance_status")),
            "performance_status": clean(base.get("performance_status")),
            "recommended_format": clean(base.get("recommended_format")),
            "shorts_eligibility": "NOT_VERIFIED",
            "content_quality_status": clean(base.get("content_quality_status")) or "NOT_EVALUATED",
            "content_quality_score": clean(base.get("content_quality_score")),
            "quality_weight_included": clean(base.get("quality_weight_included")),
            "human_review_decision": human_decision,
            "human_reviewer_notes": human_notes,
            "human_decision_reason": human_reason,
            "topic_decision": topic_decision,
            "workspace_status": workspace_status,
            "source_count": clean(research_row.get("source_count")) if research_row else "",
            "reviewed_source_count": clean(research_row.get("reviewed_source_count")) if research_row else "",
            "claim_count": clean(research_row.get("claim_count")) if research_row else "",
            "supported_claim_count": clean(research_row.get("supported_claim_count")) if research_row else "",
            "conflict_count": clean(research_row.get("conflict_count")) if research_row else "",
            "research_gate": research_gate,
            "research_decision": research_decision,
            "research_package_status": package_status,
            "production_approval": production_approval,
            "production_gate": production_gate,
        })

    # Read-only summary calculations.
    ranking_counts = count_values(dashboard, "ranking_status")
    human_counts = count_values(dashboard, "human_review_decision")
    topic_counts = count_values(dashboard, "topic_decision")
    research_counts = count_values(dashboard, "research_decision")
    research_gate_counts = count_values(dashboard, "research_gate")
    quality_counts = count_values(dashboard, "content_quality_status")
    format_counts = count_values(dashboard, "recommended_format")
    performance_counts = count_values(dashboard, "performance_status")
    package_counts = count_values(dashboard, "research_package_status")

    score_fields = [
        "relevance_score",
        "performance_score",
        "format_score",
        "ranking_score",
    ]
    averages = {}
    for field in score_fields:
        values = [
            number(row.get(field)) for row in dashboard
        ]
        valid = [value for value in values if value is not None]
        averages[field] = round(sum(valid) / len(valid), 2) if valid else None

    audit_report_path = DATA / "latest_final_audit_report_v33.json"
    audit_report = {}
    if audit_report_path.exists():
        try:
            audit_report = json.loads(
                audit_report_path.read_text(encoding="utf-8")
            )
        except (json.JSONDecodeError, OSError):
            audit_report = {"report_read_error": True}

    # Compare, but never use final-audit human_decision as human review.
    final_audit_human_counts = {}
    if final_audit is not None:
        final_audit_human_counts = count_values(
            final_audit, "human_decision"
        )

    warnings = [
        "Ranking scores are provisional and require human review.",
        "Content quality is NOT_EVALUATED because transcripts are unavailable.",
        "Shorts eligibility remains NOT_VERIFIED because aspect-ratio evidence is unavailable.",
        "Research topic approval does not equal research approval or production approval.",
        "Production approval is hard-blocked for every dashboard row.",
        "Final audit human_decision is shown only as a diagnostic and is not used as human review status.",
    ]

    if integrity["duplicate_ids"]:
        warnings.append("Duplicate IDs found in one or more auxiliary datasets; ambiguous joins were skipped.")

    if integrity["orphan_ids"]:
        warnings.append("One or more auxiliary datasets contain video IDs absent from canonical ranking.")

    if integrity["missing_join_records"]:
        warnings.append("Some canonical candidates have no matching auxiliary record; these are shown as NOT_RECORDED.")

    report = {
        "dashboard_name": "YouTube Universe V3.3 Master Research Dashboard",
        "generated_at": datetime.now().astimezone().isoformat(),
        "mode": "READ_ONLY",
        "canonical_source": FILES["ranking"],
        "canonical_rows": len(ranking),
        "canonical_unique_video_ids": len(canonical_counts),
        "dashboard_rows": len(dashboard),
        "kpis": {
            "ranking_status": ranking_counts,
            "human_review_decision": human_counts,
            "topic_decision": topic_counts,
            "research_decision": research_counts,
            "research_gate": research_gate_counts,
            "research_package_status": package_counts,
            "content_quality_status": quality_counts,
            "recommended_format": format_counts,
            "performance_status": performance_counts,
            "average_scores": averages,
            "production_approval": {"NO": len(dashboard)},
            "final_audit_human_decision_diagnostic_only": final_audit_human_counts,
        },
        "integrity": integrity,
        "warnings": warnings,
        "safety": {
            "database_modified": False,
            "youtube_api_calls": 0,
            "source_csv_files_modified": False,
            "human_decisions_modified": False,
            "automatic_approval": False,
            "production_approval_granted": False,
            "transcript_quality_scores_invented": False,
            "ambiguous_final_audit_decisions_used": False,
        },
        "audit_report_reference": {
            key: audit_report.get(key)
            for key in [
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
        } if audit_report else {},
    }

    # Backup existing dashboard outputs and this engine before replacing.
    existing = [
        path for path in [Path(__file__), OUTPUT_CSV, OUTPUT_JSON, OUTPUT_MD]
        if path.exists()
    ]

    if existing:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        for path in existing:
            if path.resolve() == Path(__file__).resolve():
                backup_name = "youtube_universe_master_dashboard_v33.py"
            else:
                backup_name = path.name
            shutil.copy2(path, BACKUP_DIR / backup_name)

    write_csv(OUTPUT_CSV, dashboard)
    OUTPUT_JSON.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    md = [
        "# YouTube Universe V3.3 - Master Research Dashboard",
        "",
        f"- Generated: {report['generated_at']}",
        "- Mode: READ ONLY",
        f"- Canonical candidates: {len(dashboard)}",
        "",
        "## Candidate ranking",
    ]

    for key, value in ranking_counts.items():
        md.append(f"- {key}: {value}")

    md += ["", "## Human review"]
    for key, value in human_counts.items():
        md.append(f"- {key}: {value}")

    md += ["", "## Topic decisions"]
    for key, value in topic_counts.items():
        md.append(f"- {key}: {value}")

    md += ["", "## Research decisions"]
    for key, value in research_counts.items():
        md.append(f"- {key}: {value}")

    md += ["", "## Research gate"]
    for key, value in research_gate_counts.items():
        md.append(f"- {key}: {value}")

    md += ["", "## Content quality"]
    for key, value in quality_counts.items():
        md.append(f"- {key}: {value}")

    md += ["", "## Recommended format"]
    for key, value in format_counts.items():
        md.append(f"- {key}: {value}")

    md += ["", "## Average scores"]
    for key, value in averages.items():
        md.append(f"- {key}: {value}")

    md += [
        "",
        "## Production safety",
        f"- Production approval: NO for all {len(dashboard)} candidates",
        "- Automatic approval: DISABLED",
        "- Database modified: NO",
        "- YouTube API calls: 0",
        "",
        "## Integrity warnings",
    ]
    for warning in warnings:
        md.append("- " + warning)

    md += [
        "",
        "## Integrity checks",
        f"- Canonical duplicate IDs: {len(canonical_duplicates)}",
        f"- Auxiliary duplicate-ID datasets: {len(integrity['duplicate_ids'])}",
        f"- Missing auxiliary files: {len(integrity['missing_files'])}",
        f"- Orphan-ID datasets: {len(integrity['orphan_ids'])}",
        f"- Incomplete join datasets: {len(integrity['missing_join_records'])}",
        "",
        "Final audit human_decision is diagnostic only. Dedicated human review audit is authoritative.",
        "Research topic approval, research approval, script approval and production approval are separate gates.",
    ]

    OUTPUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")

    print("\nDASHBOARD SUMMARY")
    print("Canonical rows:", len(ranking))
    print("Dashboard rows:", len(dashboard))
    print("Human review:", human_counts)
    print("Topic decisions:", topic_counts)
    print("Research decisions:", research_counts)
    print("Research gate:", research_gate_counts)
    print("Content quality:", quality_counts)
    print("Recommended formats:", format_counts)
    print("Production approval: NO for all candidates")

    print("\nINTEGRITY")
    print("Canonical duplicate IDs:", len(canonical_duplicates))
    print("Auxiliary duplicate-ID datasets:", len(integrity["duplicate_ids"]))
    print("Missing auxiliary files:", integrity["missing_files"])
    print("Orphan-ID datasets:", list(integrity["orphan_ids"].keys()))
    print("Incomplete join datasets:", integrity["missing_join_records"])

    print("\nOUTPUT FILES")
    print(OUTPUT_CSV)
    print(OUTPUT_JSON)
    print(OUTPUT_MD)

    if existing:
        print("BACKUP:", BACKUP_DIR)

    print("\nSAFETY")
    print("Database modified: NO")
    print("YouTube API calls: 0")
    print("Automatic approval: NO")
    print("\nBATCH 9 DASHBOARD GENERATION COMPLETE")

if __name__ == "__main__":
    main()
