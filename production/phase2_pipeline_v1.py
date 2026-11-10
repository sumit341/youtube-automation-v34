from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUPPORTED_PILOT = "E1irX9cDX8U"


def read_json(path):
    if not path.is_file():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def latest_draft(topic_id):
    base = ROOT / "production" / "runs" / topic_id / "drafts"
    manifests = list(base.glob("*/draft_manifest.json"))
    if not manifests:
        raise FileNotFoundError(f"No draft manifest under {base}")
    return max(manifests, key=lambda p: p.stat().st_mtime).parent.resolve()


def execute_stage(name, command, log_dir):
    log_path = log_dir / f"{name}.log"
    started = datetime.now().astimezone().isoformat()
    with log_path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(
            command,
            cwd=ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    return {
        "stage": name,
        "command": [str(x) for x in command],
        "exit_code": result.returncode,
        "status": "PASS" if result.returncode == 0 else "FAIL",
        "started_at": started,
        "finished_at": datetime.now().astimezone().isoformat(),
        "log": str(log_path.relative_to(ROOT)),
    }


def evaluate_reports(topic_id, draft, fact, qa):
    problems = []

    if fact.get("report_version") != "2.3":
        problems.append("FACT_REPORT_VERSION_INVALID")
    if fact.get("status") != "PASS":
        problems.append("FACT_CHECK_NOT_PASS")
    if fact.get("topic_id") != topic_id:
        problems.append("FACT_CHECK_TOPIC_MISMATCH")
    if Path(str(fact.get("draft_directory", ""))).resolve() != draft:
        problems.append("FACT_CHECK_DRAFT_MISMATCH")
    if int(fact.get("blocker_count", len(fact.get("blockers", [])))) != 0:
        problems.append("FACT_CHECK_HAS_BLOCKERS")

    if qa.get("qa_version") != "1.2":
        problems.append("SCRIPT_QA_VERSION_INVALID")
    if qa.get("status") != "PASS":
        problems.append("SCRIPT_QA_NOT_PASS")
    if qa.get("topic_id") != topic_id:
        problems.append("SCRIPT_QA_TOPIC_MISMATCH")
    if Path(str(qa.get("draft_directory", ""))).resolve() != draft:
        problems.append("SCRIPT_QA_DRAFT_MISMATCH")
    if int(qa.get("passed_checks", 0)) != int(qa.get("total_checks", -1)):
        problems.append("SCRIPT_QA_CHECKS_INCOMPLETE")

    safety = qa.get("safety") or {}
    for key in ("production_approved", "render_authorized", "upload_authorized"):
        if safety.get(key) is not False:
            problems.append("SAFETY_LOCK_NOT_FALSE:" + key)

    return problems


def self_test():
    draft = (ROOT / "production" / "runs" / SUPPORTED_PILOT / "drafts" / "test").resolve()
    fact = {
        "report_version": "2.3", "status": "PASS",
        "topic_id": SUPPORTED_PILOT, "draft_directory": str(draft),
        "blockers": [],
    }
    qa = {
        "qa_version": "1.2", "status": "PASS",
        "topic_id": SUPPORTED_PILOT, "draft_directory": str(draft),
        "passed_checks": 23, "total_checks": 23,
        "safety": {
            "production_approved": False,
            "render_authorized": False,
            "upload_authorized": False,
        },
    }
    assert evaluate_reports(SUPPORTED_PILOT, draft, fact, qa) == []

    bad_qa = dict(qa)
    bad_qa["safety"] = dict(qa["safety"], upload_authorized=True)
    assert any("SAFETY_LOCK" in x for x in evaluate_reports(SUPPORTED_PILOT, draft, fact, bad_qa))

    bad_fact = dict(fact, status="HOLD")
    assert "FACT_CHECK_NOT_PASS" in evaluate_reports(SUPPORTED_PILOT, draft, bad_fact, qa)

    bad_qa2 = dict(qa, topic_id="WRONG_TOPIC")
    assert "SCRIPT_QA_TOPIC_MISMATCH" in evaluate_reports(SUPPORTED_PILOT, draft, fact, bad_qa2)

    print("[PASS] Phase 2 pipeline self-tests: 4 scenarios")
    return 0


def run(topic_id):
    if topic_id != SUPPORTED_PILOT:
        raise RuntimeError(
            "Current Script QA v1.2 is hardcoded to pilot topic "
            f"{SUPPORTED_PILOT}; refusing unsafe cross-topic run."
        )

    draft = latest_draft(topic_id)
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    report_dir = ROOT / "reports" / "phase2_runs" / stamp
    log_dir = report_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=False)

    report = {
        "pipeline_version": "1.0.0",
        "topic_id": topic_id,
        "draft_directory": str(draft),
        "started_at": datetime.now().astimezone().isoformat(),
        "stages": [],
        "status": "RUNNING",
        "production_approved": False,
        "render_authorized": False,
        "upload_authorized": False,
        "public_upload_authorization": False,
        "capabilities": {
            "deterministic_fact_traceability": True,
            "script_quality_checks": True,
            "automatic_script_regeneration": False,
            "semantic_truth_verification": False,
            "independent_source_appraisal": False,
        },
        "limitations": [
            "A deterministic PASS does not independently prove scientific truth.",
            "No AI/API regeneration provider is configured; failed scripts are held, not falsely regenerated.",
            "Source authenticity and semantic appraisal require independent verification.",
            "Visual originality, rendering, and upload are outside this script-gate runner.",
        ],
    }

    try:
        python = sys.executable
        stages = [
            ("automated_fact_check", [
                python, str(ROOT / "production" / "automated_fact_check_v2.py"),
                "--topic-id", topic_id,
            ]),
            ("script_qa", [
                python, str(ROOT / "production" / "script_qa_v1.py"),
            ]),
        ]

        for name, command in stages:
            stage = execute_stage(name, command, log_dir)
            report["stages"].append(stage)
            if stage["status"] != "PASS":
                report["status"] = "FAILED_STOPPED"
                report["failure_queue"] = [{
                    "stage": name,
                    "reason": "PROCESS_EXIT_NONZERO",
                    "log": stage["log"],
                }]
                break
        else:
            fact_path = draft / "automated_fact_check_v2_report.json"
            qa_path = draft / "script_qa_report.json"
            fact = read_json(fact_path)
            qa = read_json(qa_path)
            problems = evaluate_reports(topic_id, draft, fact, qa)

            report["fact_check_report"] = str(fact_path)
            report["script_qa_report"] = str(qa_path)
            report["fact_check_status"] = fact.get("status")
            report["script_qa_status"] = qa.get("status")
            report["failed_identity_and_safety_checks"] = problems

            if problems:
                report["status"] = "HOLD"
                report["failure_queue"] = [
                    {"reason": problem, "action": "REVIEW_AND_FIX_THEN_RERUN"}
                    for problem in problems
                ]
            else:
                report["status"] = "SCRIPT_GATES_PASS_VISUAL_RENDER_PENDING"
                report["failure_queue"] = []

    except Exception as exc:
        report["status"] = "FAILED_STOPPED"
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()

    finally:
        report["finished_at"] = datetime.now().astimezone().isoformat()
        report_path = report_dir / "phase2_pipeline_report.json"
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print("\n" + "=" * 65)
        print("PHASE 2 INTEGRATED PIPELINE")
        print("STATUS:", report["status"])
        print("TOPIC:", topic_id)
        print("DRAFT:", draft)
        print("REPORT:", report_path)
        print("PRODUCTION APPROVED: False")
        print("RENDER AUTHORIZED: False")
        print("UPLOAD AUTHORIZED: False")
        print("=" * 65)

    return 0 if report["status"] == "SCRIPT_GATES_PASS_VISUAL_RENDER_PENDING" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-id", default=SUPPORTED_PILOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    return run(args.topic_id)


if __name__ == "__main__":
    raise SystemExit(main())
