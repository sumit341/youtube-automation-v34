$ErrorActionPreference = "Stop"
Set-Location "G:\youtube automation"

$root = (Get-Location).Path
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backup = Join-Path $root "backups\phase2_patch_$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null

$qaPath = Join-Path $root "production\script_qa_v1.py"
if (-not (Test-Path $qaPath)) { throw "Missing file: $qaPath" }
Copy-Item $qaPath (Join-Path $backup "script_qa_v1.py") -Force

$qa = Get-Content $qaPath -Raw
if ($qa -notmatch 'import argparse') {
    $qa = [regex]::Replace($qa, 'import json\r?\nimport re', "import json`r`nimport re`r`nimport argparse", 1)
}
$qa = [regex]::Replace($qa, '(?m)^RUN_DIR = ROOT / "production/runs/E1irX9cDX8U"\r?\nAUDIT_FILE = RUN_DIR / "research_consistency_report.json"\r?\n', '')
$mainPattern = '(?s)def main\(\):\s+draft_manifests = sorted\(\s+\(RUN_DIR / "drafts"\)\.glob\("\*/draft_manifest\.json"\),'
$mainReplacement = @'
def main():
    parser = argparse.ArgumentParser(description="Automated script QA for a research topic")
    parser.add_argument("--topic-id", default="E1irX9cDX8U")
    args = parser.parse_args()
    run_dir = ROOT / "production" / "runs" / args.topic_id
    audit_file = run_dir / "research_consistency_report.json"

    draft_manifests = sorted(
        (run_dir / "drafts").glob("*/draft_manifest.json"),
'@
$qa = [regex]::Replace($qa, $mainPattern, $mainReplacement, 1)
$qa = $qa.Replace('research = read_json(AUDIT_FILE)', 'research = read_json(audit_file)')
$qa = $qa.Replace('"topic_id": "E1irX9cDX8U",', '"topic_id": args.topic_id,')
if ($qa -notmatch 'parser.add_argument\("--topic-id"') {
    throw "Could not safely patch script_qa_v1.py; original is backed up."
}
Set-Content -Path $qaPath -Value $qa -Encoding UTF8

$pipelinePath = Join-Path $root "production\phase2_pipeline_v1.py"
if (Test-Path $pipelinePath) {
    Copy-Item $pipelinePath (Join-Path $backup "phase2_pipeline_v1.py") -Force
}

$pipeline = @'
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_json(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def latest_manifest(run_dir: Path) -> Path:
    files = list((run_dir / "drafts").glob("*/draft_manifest.json"))
    if not files:
        raise FileNotFoundError(f"No draft_manifest.json under {run_dir / 'drafts'}")
    return max(files, key=lambda p: p.stat().st_mtime)


def safe_child(parent: Path, relative: str) -> Path:
    candidate = (parent / relative).resolve()
    try:
        candidate.relative_to(parent.resolve())
    except ValueError as exc:
        raise ValueError(f"Script path escapes draft directory: {relative}") from exc
    return candidate


def run_stage(name: str, script: Path, topic_id: str) -> dict:
    command = [sys.executable, str(script), "--topic-id", topic_id]
    result = subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, timeout=1800
    )
    return {
        "stage": name,
        "command": command,
        "exit_code": result.returncode,
        "stdout": result.stdout[-12000:],
        "stderr": result.stderr[-12000:],
        "process_status": "PASS" if result.returncode == 0 else "NONZERO_EXIT",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 2 research-to-script integration and automated readiness gate"
    )
    parser.add_argument("--topic-id", required=True)
    args = parser.parse_args()

    topic_id = args.topic_id.strip()
    if not topic_id or any(x in topic_id for x in ("/", "\\", "..")):
        parser.error("Invalid topic ID")

    run_dir = ROOT / "production" / "runs" / topic_id
    audit_path = run_dir / "research_consistency_report.json"
    report_path = run_dir / "phase2_readiness_report.json"
    started = datetime.now(timezone.utc).isoformat()
    stages = []
    checks = []
    errors = []

    def check(name: str, passed: bool, detail: str = ""):
        checks.append({
            "name": name,
            "status": "PASS" if passed else "FAIL",
            "detail": str(detail),
        })

    try:
        research = load_json(audit_path)
        check(
            "research_gate_ready",
            research.get("overall_status") == "READY_FOR_CONTROLLED_DRAFT",
            research.get("overall_status", "MISSING"),
        )

        manifest_path = latest_manifest(run_dir)
        draft_dir = manifest_path.parent.resolve()
        manifest = load_json(manifest_path)
        check("manifest_topic_matches", manifest.get("topic_id") == topic_id,
              f"manifest={manifest.get('topic_id')}; requested={topic_id}")

        long_meta = manifest.get("long_script") or {}
        short_meta = manifest.get("short_script") or {}
        long_path = safe_child(draft_dir, str(long_meta.get("file", "")))
        short_path = safe_child(draft_dir, str(short_meta.get("file", "")))
        check("long_script_exists", long_path.is_file(), long_path.name)
        check("short_script_exists", short_path.is_file(), short_path.name)

        fact_script = ROOT / "production" / "automated_fact_check_v2.py"
        qa_script = ROOT / "production" / "script_qa_v1.py"
        check("fact_checker_module_exists", fact_script.is_file(), fact_script)
        check("script_qa_module_exists", qa_script.is_file(), qa_script)

        if fact_script.is_file():
            stages.append(run_stage("automated_fact_check_v2", fact_script, topic_id))
        if qa_script.is_file():
            stages.append(run_stage("script_qa_v1", qa_script, topic_id))

        fact_path = draft_dir / "automated_fact_check_v2_report.json"
        qa_path = draft_dir / "script_qa_report.json"
        fact = load_json(fact_path) if fact_path.is_file() else {}
        qa = load_json(qa_path) if qa_path.is_file() else {}

        fact_identity = (
            fact.get("report_version") == "2.3"
            and fact.get("topic_id") == topic_id
            and Path(str(fact.get("draft_directory", ""))).resolve() == draft_dir
            and fact_path.stat().st_mtime >= manifest_path.stat().st_mtime
        ) if fact else False
        check("fact_report_identity_and_freshness", fact_identity,
              f"status={fact.get('status', 'MISSING')}")
        check("fact_check_pass", fact.get("status") == "PASS",
              f"blockers={len(fact.get('blockers', []))}; warnings={len(fact.get('warnings', []))}")

        qa_identity = (
            qa.get("qa_version") == "1.2"
            and qa.get("topic_id") == topic_id
            and Path(str(qa.get("draft_directory", ""))).resolve() == draft_dir
            and qa_path.stat().st_mtime >= fact_path.stat().st_mtime
        ) if qa and fact_path.is_file() else False
        check("script_qa_identity_and_freshness", qa_identity,
              f"status={qa.get('status', 'MISSING')}")
        check("script_qa_pass", qa.get("status") == "PASS",
              f"blockers={len(qa.get('blockers', []))}; warnings={len(qa.get('warnings', []))}")

        for stage in stages:
            check(f"process_{stage['stage']}", stage["exit_code"] == 0,
                  f"exit_code={stage['exit_code']}")

        failures = [x for x in checks if x["status"] == "FAIL"]
        if not failures and fact.get("status") == "PASS" and qa.get("status") == "PASS":
            status = "PHASE2_READY"
        else:
            status = "REGENERATION_OR_RESEARCH_FIX_REQUIRED"

        regen_queue = []
        for item in (fact.get("blockers", []) + fact.get("warnings", [])):
            regen_queue.append({
                "source": "fact_check",
                "name": item.get("name", "unknown"),
                "severity": item.get("severity", "UNKNOWN"),
                "detail": item.get("detail", ""),
            })
        for item in (qa.get("blockers", []) + qa.get("warnings", [])):
            regen_queue.append({
                "source": "script_qa",
                "name": item.get("name", "unknown"),
                "severity": item.get("severity", "UNKNOWN"),
                "detail": item.get("detail", ""),
            })

        report = {
            "phase": 2,
            "version": "1.0.0",
            "topic_id": topic_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "started_at": started,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "draft_directory": str(draft_dir),
            "research_gate_status": research.get("overall_status"),
            "fact_check_status": fact.get("status", "NOT_RUN"),
            "script_qa_status": qa.get("status", "NOT_RUN"),
            "checks_passed": sum(x["status"] == "PASS" for x in checks),
            "checks_total": len(checks),
            "checks": checks,
            "stages": stages,
            "regeneration_queue": regen_queue,
            "automation_capabilities": {
                "automatic_gate_execution": True,
                "failure_queue_generation": True,
                "automatic_script_regeneration": False,
                "semantic_truth_verification": False,
                "independent_source_fetch_and_appraisal": False,
            },
            "safety": {
                "fact_review_approved": False,
                "production_approved": False,
                "render_authorized": False,
                "upload_authorized": False,
                "public_upload_authorized": False,
            },
            "limitations": [
                "The fact checker is deterministic traceability logic, not a semantic truth model.",
                "A PASS does not prove that a source is authentic or that a claim is true.",
                "This phase creates a failure queue but does not invent a script generator or regenerate text.",
                "No production, render, or upload authorization is granted by Phase 2.",
            ],
        }
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        report = {
            "phase": 2,
            "version": "1.0.0",
            "topic_id": topic_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "BLOCKED",
            "checks": checks,
            "stages": stages,
            "errors": errors,
            "regeneration_queue": [],
            "safety": {
                "fact_review_approved": False,
                "production_approved": False,
                "render_authorized": False,
                "upload_authorized": False,
                "public_upload_authorized": False,
            },
        }

    run_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("=" * 64)
    print("PHASE 2 RESEARCH-TO-SCRIPT PIPELINE")
    print("TOPIC:", topic_id)
    print("STATUS:", report["status"])
    print("CHECKS:", report.get("checks_passed", 0), "/", report.get("checks_total", len(checks)))
    print("FAILURE QUEUE:", len(report.get("regeneration_queue", [])))
    print("REPORT:", report_path)
    print("PRODUCTION / RENDER / UPLOAD AUTHORIZATION: FALSE")
    return 0 if report["status"] == "PHASE2_READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
'@

Set-Content -Path $pipelinePath -Value $pipeline -Encoding UTF8

Write-Host "`n--- PHASE 2 PATCH APPLIED ---" -ForegroundColor Green
Write-Host "Backup: $backup"
Write-Host "Updated: production\script_qa_v1.py"
Write-Host "Created: production\phase2_pipeline_v1.py"

Write-Host "`n--- PYTHON SYNTAX CHECK ---" -ForegroundColor Cyan
& ".\.venv\Scripts\python.exe" -m py_compile "production\script_qa_v1.py" "production\phase2_pipeline_v1.py"
if ($LASTEXITCODE -ne 0) { throw "Syntax check failed. Backup retained at $backup" }

Write-Host "`n--- PHASE 2 PIPELINE USAGE ---" -ForegroundColor Cyan
Write-Host '.\.venv\Scripts\python.exe production\phase2_pipeline_v1.py --topic-id E1irX9cDX8U'
Write-Host "`nPatch complete. No research, drafts, assets, credentials, or publishing settings were changed." -ForegroundColor Green
