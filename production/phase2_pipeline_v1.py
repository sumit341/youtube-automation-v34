from __future__ import annotations

import argparse
import json
import subprocess
import sys
import traceback
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOPIC_ID = "E1irX9cDX8U"
SCRIPT_QA_VERSION = "1.3"
TOPIC_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def validate_topic_id(topic_id):
    if not isinstance(topic_id, str) or not TOPIC_ID_PATTERN.fullmatch(topic_id):
        raise ValueError("Invalid topic ID. Use 1-128 letters, numbers, underscores, or hyphens.")
    return topic_id


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

    if fact.get("report_version") != "2.4":
        problems.append("FACT_REPORT_VERSION_INVALID")
    if fact.get("status") != "PASS":
        problems.append("FACT_CHECK_NOT_PASS")
    if fact.get("topic_id") != topic_id:
        problems.append("FACT_CHECK_TOPIC_MISMATCH")
    if Path(str(fact.get("draft_directory", ""))).resolve() != draft:
        problems.append("FACT_CHECK_DRAFT_MISMATCH")
    if int(fact.get("blocker_count", len(fact.get("blockers", [])))) != 0:
        problems.append("FACT_CHECK_HAS_BLOCKERS")

    if qa.get("qa_version") != SCRIPT_QA_VERSION:
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
    test_topic = DEFAULT_TOPIC_ID
    draft = (ROOT / "production" / "runs" / test_topic / "drafts" / "test").resolve()
    fact = {
        "report_version": "2.4", "status": "PASS",
        "topic_id": test_topic, "draft_directory": str(draft),
        "blockers": [],
    }
    qa = {
        "qa_version": SCRIPT_QA_VERSION, "status": "PASS",
        "topic_id": test_topic, "draft_directory": str(draft),
        "passed_checks": 23, "total_checks": 23,
        "safety": {
            "production_approved": False,
            "render_authorized": False,
            "upload_authorized": False,
        },
    }
    assert evaluate_reports(test_topic, draft, fact, qa) == []

    bad_qa = dict(qa)
    bad_qa["safety"] = dict(qa["safety"], upload_authorized=True)
    assert any("SAFETY_LOCK" in x for x in evaluate_reports(test_topic, draft, fact, bad_qa))

    bad_fact = dict(fact, status="HOLD")
    assert "FACT_CHECK_NOT_PASS" in evaluate_reports(test_topic, draft, bad_fact, qa)

    bad_qa2 = dict(qa, topic_id="WRONG_TOPIC")
    assert "SCRIPT_QA_TOPIC_MISMATCH" in evaluate_reports(test_topic, draft, fact, bad_qa2)

    old_version_qa = dict(qa, qa_version="1.2")
    assert "SCRIPT_QA_VERSION_INVALID" in evaluate_reports(test_topic, draft, fact, old_version_qa)

    bad_fact_topic = dict(fact, topic_id="DIFFERENT_TOPIC")
    assert "FACT_CHECK_TOPIC_MISMATCH" in evaluate_reports(test_topic, draft, bad_fact_topic, qa)

    try:
        validate_topic_id("../escape")
    except ValueError:
        pass
    else:
        raise AssertionError("Path traversal topic ID was not rejected")

    print("[PASS] Phase 2 pipeline self-tests: 7 scenarios")
    return 0


def run(topic_id):
    validate_topic_id(topic_id)
    try:
        draft = latest_draft(topic_id)
    except FileNotFoundError:
        draft = ROOT / "production" / "runs" / topic_id / "drafts" / "PENDING_GEMINI"
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    report_dir = ROOT / "reports" / "phase2_runs" / stamp
    log_dir = report_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=False)

    report = {
        "pipeline_version": "1.1.0",
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
            "gemini_topic_based_draft_generation": True,
            "automatic_script_regeneration": False,
            "semantic_truth_verification": False,
            "independent_source_appraisal": False,
        },
        "limitations": [
            "A deterministic PASS does not independently prove scientific truth.",
            "Gemini generates a new topic-specific draft from reviewed evidence; failed QA remains on HOLD.",
            "Source authenticity and semantic appraisal require independent verification.",
            "Visual assets and originality checks run after script gates; render and upload remain separately locked.",
        ],
    }

    try:
        python = sys.executable
        stages = [
            ("gemini_draft_generation", [
                python, str(ROOT / "production" / "gemini_draft_generator_v1.py"),
                "--topic-id", topic_id,
            ]),
            ("automated_fact_check", [
                python, str(ROOT / "production" / "automated_fact_check_v2.py"),
                "--topic-id", topic_id,
            ]),
            ("script_qa", [
                python, str(ROOT / "production" / "script_qa_v1.py"),
                "--topic-id", topic_id,
            ]),
        ]

        for name, command in stages:
            stage = execute_stage(name, command, log_dir)
            report["stages"].append(stage)
            if name == "gemini_draft_generation" and stage["status"] == "PASS":
                draft = latest_draft(topic_id)
                report["draft_directory"] = str(draft)
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
                # Visual generation starts only after both script gates pass.
                visual_engine = ROOT / "production" / "automated_visual_engine_v1.py"
                visual_stage = execute_stage(
                    "visual_generation",
                    [python, str(visual_engine), "--topic-id", topic_id],
                    log_dir,
                )
                report["stages"].append(visual_stage)

                if visual_stage["status"] != "PASS":
                    report["status"] = "HOLD_VISUAL_GENERATION_FAILED"
                    report["failure_queue"] = [{
                        "stage": "visual_generation",
                        "reason": "PROCESS_EXIT_NONZERO",
                        "log": visual_stage["log"],
                    }]
                else:
                    packages = sorted(
                        draft.glob("automated_visual_assets_v1_*"),
                        key=lambda item: item.stat().st_mtime,
                        reverse=True,
                    )
                    manifest_path = (
                        packages[0] / "asset_manifest.json"
                        if packages else None
                    )
                    if not manifest_path or not manifest_path.is_file():
                        report["status"] = "HOLD_VISUAL_MANIFEST_MISSING"
                        report["failure_queue"] = [{
                            "stage": "visual_generation",
                            "reason": "ASSET_MANIFEST_NOT_FOUND",
                        }]
                    else:
                        originality_gate = ROOT / "production" / "premium_originality_gate_v1_3.py"
                        originality_stage = execute_stage(
                            "visual_originality_gate",
                            [
                                python, str(originality_gate),
                                "--draft", str(draft),
                                "--manifest", str(manifest_path),
                                "--runs-root", str(ROOT / "production" / "runs"),
                            ],
                            log_dir,
                        )
                        report["stages"].append(originality_stage)
                        gate_report_path = draft / "premium_originality_gate_v1_3_report.json"
                        gate_report = (
                            read_json(gate_report_path)
                            if gate_report_path.is_file() else {}
                        )
                        report["visual_manifest"] = str(manifest_path)
                        report["visual_originality_report"] = str(gate_report_path)
                        report["visual_originality_status"] = gate_report.get("status")
                        report["visual_asset_count"] = gate_report.get("asset_count", 0)

                        if (
                            originality_stage["status"] == "PASS"
                            and gate_report.get("status") == "PASS_ORIGINALITY_GATE"
                            and gate_report.get("topic_id_match") is True
                        ):
                            report["status"] = "VISUAL_ORIGINALITY_GATES_PASS_RENDER_PENDING"
                            report["failure_queue"] = []
                        else:
                            report["status"] = "HOLD_VISUAL_ORIGINALITY"
                            report["failure_queue"] = [{
                                "stage": "visual_originality_gate",
                                "reason": "ORIGINALITY_GATE_NOT_PASS",
                                "gate_status": gate_report.get("status"),
                                "report": str(gate_report_path),
                            }]

                # Visual PASS is still not production approval or render/upload permission.
                report["production_approved"] = False
                report["render_authorized"] = False
                report["upload_authorized"] = False
                report["public_upload_authorization"] = False

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

    return 0 if report["status"] == "VISUAL_ORIGINALITY_GATES_PASS_RENDER_PENDING" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-id", default=DEFAULT_TOPIC_ID)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    return run(args.topic_id)


if __name__ == "__main__":
    raise SystemExit(main())
