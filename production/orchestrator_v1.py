
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data" / "research" / "youtube_universe_v33"
BACKUP_ROOT = ROOT / "backups" / "production_runs"
REPORT_ROOT = ROOT / "reports" / "production_runs"

# Existing research engines only.
# Scanner and approval engine are deliberately excluded.
STAGES = [
    ("relevance_scoring", "app/youtube_universe_scoring_v33.py"),
    ("performance", "app/youtube_universe_performance_v33.py"),
    ("format_suitability", "app/youtube_universe_format_v33.py"),
    ("content_quality", "app/youtube_universe_content_quality_v33.py"),
    ("candidate_ranking", "app/youtube_universe_ranking_v33.py"),
    ("final_audit", "app/youtube_universe_final_audit_v33.py"),
    ("research_workbench", "app/youtube_universe_research_workbench_v33.py"),
    ("research_package", "app/youtube_universe_research_package_v33.py"),
    ("master_dashboard", "app/youtube_universe_master_dashboard_v33.py"),
]


def timestamp():
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")


def print_plan():
    print("=" * 65)
    print("YOUTUBE AUTOMATION V34 - RESEARCH PIPELINE")
    print("=" * 65)
    print("MODE: PLAN ONLY - no engine will execute")
    print()

    for number, (name, relative_path) in enumerate(STAGES, start=1):
        path = ROOT / relative_path
        status = "READY" if path.is_file() else "MISSING"
        print(f"{number:02}. {name:22} | {relative_path} | {status}")

    print()
    print("Excluded intentionally:")
    print("- YouTube scanner: may consume API quota")
    print("- Approval engine: appends decision history")
    print("- Video production and upload: not integrated yet")
    print("=" * 65)


def create_backup(run_id):
    if not DATA_DIR.is_dir():
        raise FileNotFoundError(
            f"Research data directory missing: {DATA_DIR}"
        )

    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    destination = BACKUP_ROOT / run_id / "youtube_universe_v33"

    if destination.exists():
        raise FileExistsError(destination)

    destination.parent.mkdir(parents=True, exist_ok=True)

    print(f"Creating research backup: {destination}")
    shutil.copytree(DATA_DIR, destination)

    return destination


def execute_stage(name, relative_path, log_dir):
    script = ROOT / relative_path

    if not script.is_file():
        raise FileNotFoundError(script)

    log_file = log_dir / f"{name}.log"
    command = [sys.executable, str(script)]

    print()
    print("-" * 65)
    print(f"STAGE: {name}")
    print(f"COMMAND: {' '.join(command)}")
    print("-" * 65)

    started = time.time()

    with log_file.open("w", encoding="utf-8") as output:
        process = subprocess.run(
            command,
            cwd=ROOT,
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=1800,
            check=False,
        )

    elapsed = round(time.time() - started, 2)

    result = {
        "stage": name,
        "script": relative_path,
        "exit_code": process.returncode,
        "duration_seconds": elapsed,
        "log_file": str(log_file.relative_to(ROOT)),
        "status": "PASS" if process.returncode == 0 else "FAIL",
    }

    print(f"STATUS: {result['status']}")
    print(f"EXIT CODE: {process.returncode}")
    print(f"DURATION: {elapsed}s")
    print(f"LOG: {result['log_file']}")

    return result


def run_pipeline():
    run_id = timestamp()
    report_dir = REPORT_ROOT / run_id
    log_dir = report_dir / "logs"

    report_dir.mkdir(parents=True, exist_ok=False)
    log_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "run_id": run_id,
        "started_at": datetime.now().astimezone().isoformat(),
        "mode": "RESEARCH_ONLY",
        "backup": None,
        "stages": [],
        "status": "RUNNING",
        "safety": {
            "youtube_scanner_executed": False,
            "approval_engine_executed": False,
            "youtube_upload_executed": False,
            "video_render_executed": False,
        },
    }

    try:
        for name, relative_path in STAGES:
            if not (ROOT / relative_path).is_file():
                raise FileNotFoundError(relative_path)

        backup = create_backup(run_id)
        report["backup"] = str(backup.relative_to(ROOT))

        for name, relative_path in STAGES:
            result = execute_stage(name, relative_path, log_dir)
            report["stages"].append(result)

            if result["status"] != "PASS":
                report["status"] = "FAILED_STOPPED"
                break
        else:
            report["status"] = "COMPLETED"

    except Exception as error:
        report["status"] = "FAILED_STOPPED"
        report["error"] = f"{type(error).__name__}: {error}"

    finally:
        report["finished_at"] = datetime.now().astimezone().isoformat()
        report_path = report_dir / "run_report.json"
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print()
        print("=" * 65)
        print(f"PIPELINE STATUS: {report['status']}")
        print(f"REPORT: {report_path.relative_to(ROOT)}")
        print("=" * 65)

    return 0 if report["status"] == "COMPLETED" else 1


def main():
    parser = argparse.ArgumentParser(
        description="Safe V34 research pipeline orchestrator"
    )
    parser.add_argument(
        "--run-research",
        action="store_true",
        help="Execute research engines after backing up research data",
    )
    parser.add_argument(
        "--confirm-overwrite",
        action="store_true",
        help="Confirm that existing latest research outputs may be refreshed",
    )

    args = parser.parse_args()

    if not args.run_research:
        print_plan()
        return 0

    if not args.confirm_overwrite:
        print("BLOCKED: execution requires --confirm-overwrite")
        return 2

    return run_pipeline()


if __name__ == "__main__":
    raise SystemExit(main())
