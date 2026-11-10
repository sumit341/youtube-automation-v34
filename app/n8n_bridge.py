import json
import hmac
import uuid
import subprocess
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
TOKEN_FILE = ROOT / "config" / "n8n_bridge.token"
LOG_DIR = ROOT / "logs" / "n8n_bridge"
JOBS_DIR = LOG_DIR / "jobs"
ORCHESTRATOR = ROOT / "production" / "orchestrator_v1.py"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

LOCK = threading.RLock()
JOBS = {}
ACTIVE_JOB = None


def now():
    return datetime.now(timezone.utc).isoformat()


def read_token():
    if not TOKEN_FILE.is_file():
        raise FileNotFoundError("Bridge token file is missing.")
    return TOKEN_FILE.read_text(encoding="ascii").strip()


def persist_job(job):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    target = JOBS_DIR / f"{job['job_id']}.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(job, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    temporary.replace(target)


def update_job(job_id, **changes):
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job.update(changes)
        job["updated_at"] = now()
        persist_job(job)


def load_jobs():
    global ACTIVE_JOB
    JOBS_DIR.mkdir(parents=True, exist_ok=True)

    for path in JOBS_DIR.glob("*.json"):
        try:
            job = json.loads(path.read_text(encoding="utf-8"))
            if job.get("status") in ("queued", "running"):
                job["status"] = "interrupted"
                job["error"] = "Bridge restarted while this job was active."
                job["updated_at"] = now()
                path.write_text(
                    json.dumps(job, indent=2, ensure_ascii=False),
                    encoding="utf-8"
                )
            JOBS[job["job_id"]] = job
        except Exception:
            continue


def run_research_job(job_id):
    global ACTIVE_JOB

    log_path = LOG_DIR / f"{job_id}.log"

    try:
        update_job(
            job_id,
            status="running",
            started_at=now(),
            log_file=str(log_path.relative_to(ROOT))
        )

        command = [
            str(PYTHON),
            str(ORCHESTRATOR),
            "--run-research",
            "--confirm-overwrite",
        ]

        with log_path.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                command,
                cwd=str(ROOT),
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
                shell=False,
            )
            update_job(job_id, process_id=process.pid)
            exit_code = process.wait()

        update_job(
            job_id,
            status="completed" if exit_code == 0 else "failed",
            exit_code=exit_code,
            finished_at=now(),
        )

    except Exception as error:
        update_job(
            job_id,
            status="failed",
            error=f"{type(error).__name__}: {error}",
            finished_at=now(),
        )

    finally:
        with LOCK:
            if ACTIVE_JOB == job_id:
                ACTIVE_JOB = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def send_json(self, status, data):
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        supplied = self.headers.get("X-Bridge-Token", "")
        try:
            expected = read_token()
            return bool(expected) and hmac.compare_digest(supplied, expected)
        except Exception:
            return False

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            self.send_json(200, {
                "ok": True,
                "service": "youtube-project-bridge",
                "time_utc": now(),
            })
            return

        if not self.authorized():
            self.send_json(401, {"ok": False, "error": "Unauthorized"})
            return

        if path.startswith("/jobs/"):
            job_id = path.rsplit("/", 1)[-1]
            with LOCK:
                job = JOBS.get(job_id)

            if job:
                self.send_json(200, job)
            else:
                self.send_json(404, {
                    "ok": False,
                    "error": "Job not found"
                })
            return

        self.send_json(404, {"ok": False, "error": "Not found"})

    def do_POST(self):
        global ACTIVE_JOB

        if not self.authorized():
            self.send_json(401, {"ok": False, "error": "Unauthorized"})
            return

        if urlparse(self.path).path != "/run":
            self.send_json(404, {"ok": False, "error": "Not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 4096:
                self.send_json(400, {
                    "ok": False,
                    "error": "Invalid request size"
                })
                return

            payload = json.loads(self.rfile.read(length).decode("utf-8"))

        except Exception:
            self.send_json(400, {
                "ok": False,
                "error": "Invalid JSON request"
            })
            return

        if payload.get("action") != "research":
            self.send_json(400, {
                "ok": False,
                "error": "Unsupported action"
            })
            return

        if payload.get("confirm_overwrite") is not True:
            self.send_json(409, {
                "ok": False,
                "error": "Explicit confirm_overwrite=true is required"
            })
            return

        if not PYTHON.is_file() or not ORCHESTRATOR.is_file():
            self.send_json(500, {
                "ok": False,
                "error": "Python environment or orchestrator is missing"
            })
            return

        with LOCK:
            if ACTIVE_JOB is not None:
                self.send_json(409, {
                    "ok": False,
                    "error": "Another research job is already active",
                    "active_job_id": ACTIVE_JOB,
                })
                return

            job_id = str(uuid.uuid4())
            job = {
                "job_id": job_id,
                "action": "research",
                "status": "queued",
                "created_at": now(),
                "updated_at": now(),
                "exit_code": None,
                "safety": {
                    "research_backup_created_by_orchestrator": True,
                    "video_render_executed": False,
                    "youtube_upload_executed": False,
                },
            }

            JOBS[job_id] = job
            ACTIVE_JOB = job_id
            persist_job(job)

        worker = threading.Thread(
            target=run_research_job,
            args=(job_id,),
            daemon=True
        )
        worker.start()

        self.send_json(202, {
            "ok": True,
            "job_id": job_id,
            "status": "queued",
            "status_url": f"/jobs/{job_id}",
        })


if __name__ == "__main__":
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    load_jobs()

    server = ThreadingHTTPServer(("0.0.0.0", 8765), Handler)
    print("YouTube Automation Bridge listening on port 8765")
    server.serve_forever()
