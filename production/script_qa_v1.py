
from pathlib import Path
from datetime import datetime
import json
import re

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / "production/runs/E1irX9cDX8U"
AUDIT_FILE = RUN_DIR / "research_consistency_report.json"

TARGETS = {
    "long": {"minimum": 900, "maximum": 1200, "wpm": 130},
    "short": {"minimum": 85, "maximum": 110, "wpm": 130},
}


def read_json(path):
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path):
    if not path.exists():
        raise FileNotFoundError(path)
    return path.read_text(encoding="utf-8")


def word_count(text):
    return len(re.findall(r"\b[\w'-]+\b", text))


def extract_mapping_ids(text):
    found = set()

    for line in text.splitlines():
        if line.strip().lower().startswith("claim mapping:"):
            found.update(re.findall(r"\bC\d{2}\b", line))

    return found


def extract_narration(text):
    sections = []
    current_heading = ""
    current_lines = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_heading and current_lines:
                if current_heading.upper() not in {
                    "DRAFT NOTES", "CLAIM MAPPING"
                }:
                    sections.extend(current_lines)

            current_heading = line[3:].strip()
            current_lines = []
            continue

        if line.strip().startswith("Claim mapping:"):
            continue

        if current_heading:
            current_lines.append(line)

    if current_heading and current_heading.upper() not in {
        "DRAFT NOTES", "CLAIM MAPPING"
    }:
        sections.extend(current_lines)

    return "\n".join(sections)


def add_check(checks, name, passed, detail, severity="BLOCKER"):
    checks.append({
        "name": name,
        "passed": bool(passed),
        "severity": severity,
        "detail": detail,
    })


def check_sections(text, required):
    headings = {
        x.strip().upper()
        for x in re.findall(r"^##\s+(.+?)\s*$", text, re.MULTILINE)
    }
    return {x: x in headings for x in required}


def main():
    draft_manifests = sorted(
        (RUN_DIR / "drafts").glob("*/draft_manifest.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not draft_manifests:
        raise FileNotFoundError("No draft manifest found.")

    manifest_path = draft_manifests[0]
    draft_dir = manifest_path.parent
    manifest = read_json(manifest_path)
    research = read_json(AUDIT_FILE)

    long_text = read_text(draft_dir / manifest["long_script"]["file"])
    short_text = read_text(draft_dir / manifest["short_script"]["file"])

    eligible = {
        x["claim_id"] for x in research["claim_results"]
        if x["status"] == "ELIGIBLE_FOR_DRAFT"
    }
    held = {
        x["claim_id"] for x in research["claim_results"]
        if x["status"] == "HOLD"
    }

    checks = []

    add_check(
        checks, "RESEARCH_GATE",
        research.get("overall_status") == "READY_FOR_CONTROLLED_DRAFT",
        research.get("overall_status", "MISSING"),
    )

    for label, text, target, required in [
        ("LONG", long_text, TARGETS["long"],
         ["HOOK", "CONTEXT", "TAKEAWAY"]),
        ("SHORT", short_text, TARGETS["short"],
         ["HOOK", "EVIDENCE", "QUALIFICATION", "TAKEAWAY"]),
    ]:
        narration = extract_narration(text)
        words = word_count(narration)
        mapping = extract_mapping_ids(text)

        add_check(
            checks, f"{label}_WORD_COUNT",
            target["minimum"] <= words <= target["maximum"],
            f"{words} narration words; target {target['minimum']}-{target['maximum']}",
            "WARNING",
        )

        for section, passed in check_sections(text, required).items():
            add_check(
                checks, f"{label}_SECTION_{section}",
                passed, "Present" if passed else "Missing",
            )

        add_check(
            checks, f"{label}_CLAIM_MAPPING",
            bool(mapping) and mapping.issubset(eligible),
            f"Mapped: {sorted(mapping)}; eligible: {sorted(eligible)}",
        )

        add_check(
            checks, f"{label}_HELD_CLAIM_MAPPING",
            not bool(mapping & held),
            f"Held claims in explicit mapping: {sorted(mapping & held)}",
        )

        # Detect literal claim IDs in narration separately.
        narration_mentions = set(
            re.findall(r"\bC\d{2}\b", narration)
        )

        add_check(
            checks, f"{label}_NARRATION_CLAIM_REFERENCE",
            not bool(narration_mentions & held),
            f"Held claim IDs mentioned in narration: {sorted(narration_mentions & held)}",
        )

    safety = manifest.get("safety", {})

    add_check(
        checks, "NO_PRODUCTION_APPROVAL",
        safety.get("production_approved") is False,
        "Production approval remains disabled.",
    )

    add_check(
        checks, "NO_UPLOAD_AUTHORIZATION",
        safety.get("upload_authorized") is False,
        "Upload authorization remains disabled.",
    )

    fact_report_path = draft_dir / "automated_fact_check_v2_report.json"
    fact_report = read_json(fact_report_path) if fact_report_path.exists() else {}

    report_version_ok = fact_report.get("report_version") == "2.3"
    report_topic_ok = fact_report.get("topic_id") == RUN_DIR.name

    try:
        report_draft_ok = (
            Path(fact_report.get("draft_directory", "")).resolve()
            == draft_dir.resolve()
        )
    except (OSError, TypeError, ValueError):
        report_draft_ok = False

    report_fresh_ok = (
        fact_report_path.exists()
        and fact_report_path.stat().st_mtime >= manifest_path.stat().st_mtime
    )

    add_check(
        checks, "FACT_CHECK_REPORT_VERSION",
        report_version_ok,
        f"Expected 2.3; found {fact_report.get('report_version', 'MISSING')}",
    )

    add_check(
        checks, "FACT_CHECK_TOPIC_MATCH",
        report_topic_ok,
        f"Expected {RUN_DIR.name}; found {fact_report.get('topic_id', 'MISSING')}",
    )

    add_check(
        checks, "FACT_CHECK_DRAFT_MATCH",
        report_draft_ok,
        f"Report draft directory matches current draft: {report_draft_ok}",
    )

    add_check(
        checks, "FACT_CHECK_REPORT_FRESHNESS",
        report_fresh_ok,
        f"Report exists and is not older than draft manifest: {report_fresh_ok}",
    )

    add_check(
        checks, "AUTOMATED_FACT_CHECK",
        report_version_ok
        and report_topic_ok
        and report_draft_ok
        and report_fresh_ok
        and fact_report.get("status") == "PASS",
        f"v2.3 fact-check status: {fact_report.get('status', 'NOT_RUN')}",
    )

    blockers = [x for x in checks if not x["passed"] and x["severity"] == "BLOCKER"]
    warnings = [x for x in checks if not x["passed"] and x["severity"] == "WARNING"]
    reviews = [x for x in checks if not x["passed"] and x["severity"] == "REVIEW"]

    status = "FAIL" if blockers else "HOLD" if warnings or reviews else "PASS"

    result = {
        "qa_version": "1.2",
        "topic_id": "E1irX9cDX8U",
        "generated_at": datetime.now().astimezone().isoformat(),
        "draft_directory": str(draft_dir),
        "status": status,
        "long_narration_words": word_count(extract_narration(long_text)),
        "short_narration_words": word_count(extract_narration(short_text)),
        "passed_checks": sum(x["passed"] for x in checks),
        "total_checks": len(checks),
        "blockers": blockers,
        "warnings": warnings,
        "review_items": reviews,
        "checks": checks,
        "safety": {
            "production_approved": False,
            "render_authorized": False,
            "upload_authorized": False,
            "original_drafts_modified": False,
            "original_research_modified": False,
        },
    }

    report_path = draft_dir / "script_qa_report.json"
    report_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("SCRIPT QA REPORT v1.2")
    print("=" * 55)
    print("Status:", status)
    print("Checks:", result["passed_checks"], "/", result["total_checks"])
    print("Long narration words:", result["long_narration_words"])
    print("Short narration words:", result["short_narration_words"])

    for item in checks:
        label = "PASS" if item["passed"] else item["severity"]
        print(f"{label:8} | {item['name']} | {item['detail']}")

    print("\nReport:", report_path)
    print("Production approval: NOT GRANTED")
    print("Upload authorization: NOT GRANTED")


if __name__ == "__main__":
    main()
