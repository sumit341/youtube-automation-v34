from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import csv
import json
import hashlib
import os
import sys
import tempfile

BASE = Path("data/research/youtube_universe_v33")
WORKSPACE = BASE / "research_workspace_v33"

TOPIC_DECISIONS = BASE / "human_review_decisions_v33.csv"
HUMAN_RESEARCH_DECISIONS = BASE / "research_review_decisions_v33.csv"

DECISIONS_OUT = BASE / "automated_approval_decisions_v1.csv"
REPORT_OUT = BASE / "latest_automated_approval_report_v1.json"
AUDIT_OUT = BASE / "automated_approval_audit_v1.json"

PILOT_ID = "E1irX9cDX8U"
RULESET_VERSION = "1.0.1"

DECISION_FIELDS = [
    "decision_id", "video_id", "stage", "decision", "ruleset_version",
    "decided_at", "reason_codes", "reason_details", "source_count",
    "reviewed_source_count", "claim_count", "supported_claim_count",
    "evidence_count", "reviewed_evidence_count", "conflict_count",
    "input_fingerprint",
]


def current_timestamp():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_csv(path):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Required file missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def clean(row, key):
    return str(row.get(key, "") or "").strip()


def duplicate_values(rows, key):
    seen = set()
    duplicates = set()
    for row in rows:
        value = clean(row, key)
        if not value:
            continue
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def valid_locator(value):
    value = str(value or "").strip()
    if value.lower().startswith("doi:"):
        return len(value) > 8
    parsed = urlparse(value)
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def fingerprint(sources, claims, evidence):
    payload = {"sources": sources, "claims": claims, "evidence": evidence}
    raw = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def evaluate_research(video_id):
    folder = WORKSPACE / video_id
    paths = {
        "sources": folder / "sources.csv",
        "claims": folder / "claims.csv",
        "evidence": folder / "evidence.csv",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        missing_fingerprint = fingerprint([], [], [{"missing_files": missing}])
        return {
            "decision": "HOLD",
            "reasons": ["RESEARCH_FILES_MISSING"],
            "details": missing,
            "counts": {
                "source_count": 0, "reviewed_source_count": 0,
                "claim_count": 0, "supported_claim_count": 0,
                "evidence_count": 0, "reviewed_evidence_count": 0,
                "conflict_count": 0,
            },
            "fingerprint": missing_fingerprint,
        }

    sources = read_csv(paths["sources"])
    claims = read_csv(paths["claims"])
    evidence = read_csv(paths["evidence"])
    reasons, details = [], []

    counts = {
        "source_count": len(sources),
        "reviewed_source_count": 0,
        "claim_count": len(claims),
        "supported_claim_count": 0,
        "evidence_count": len(evidence),
        "reviewed_evidence_count": 0,
        "conflict_count": 0,
    }

    if not sources or not claims or not evidence:
        reasons.append("RESEARCH_RECORDS_MISSING")

    for rows, key, label in (
        (sources, "source_id", "SOURCE"),
        (claims, "claim_id", "CLAIM"),
        (evidence, "evidence_id", "EVIDENCE"),
    ):
        duplicates = duplicate_values(rows, key)
        if duplicates:
            reasons.append(f"DUPLICATE_{label}_IDS")
            details.append(f"{label} duplicate IDs: {', '.join(duplicates)}")
        if any(not clean(row, key) for row in rows):
            reasons.append(f"MISSING_{label}_ID")

    source_map = {
        clean(row, "source_id"): row
        for row in sources if clean(row, "source_id")
    }
    claim_map = {
        clean(row, "claim_id"): row
        for row in claims if clean(row, "claim_id")
    }

    reviewed_sources = set()
    for row in sources:
        sid = clean(row, "source_id")
        status = clean(row, "source_review_status").upper()
        if status != "REVIEWED":
            reasons.append("SOURCE_NOT_REVIEWED")
            details.append(f"{sid}: source status is {status or 'MISSING'}")
            continue
        if (
            not clean(row, "title")
            or not (clean(row, "author") or clean(row, "organization"))
            or not valid_locator(clean(row, "url_or_doi"))
        ):
            reasons.append("SOURCE_METADATA_INVALID")
            details.append(f"{sid}: incomplete source metadata")
            continue
        if sid:
            reviewed_sources.add(sid)

    counts["reviewed_source_count"] = len(reviewed_sources)
    evidence_by_claim = {}

    for row in evidence:
        eid = clean(row, "evidence_id")
        cid = clean(row, "claim_id")
        sid = clean(row, "source_id")
        relation = clean(row, "evidence_relation").upper()
        status = clean(row, "review_status").upper()

        if cid not in claim_map:
            reasons.append("EVIDENCE_CLAIM_REFERENCE_INVALID")
            details.append(f"{eid}: unknown claim {cid}")
            continue
        if sid not in source_map:
            reasons.append("EVIDENCE_SOURCE_REFERENCE_INVALID")
            details.append(f"{eid}: unknown source {sid}")
            continue
        if relation not in ("SUPPORTS", "CONTRADICTS", "MIXED", "CONTEXT"):
            reasons.append("INVALID_EVIDENCE_RELATION")
            details.append(f"{eid}: {relation or 'MISSING'}")
            continue
        if status != "REVIEWED":
            reasons.append("EVIDENCE_NOT_REVIEWED")
            details.append(f"{eid}: evidence status is {status or 'MISSING'}")
            continue
        if sid not in reviewed_sources:
            reasons.append("EVIDENCE_SOURCE_NOT_VALIDATED")
            details.append(f"{eid}: linked source is not validated")
            continue
        if not clean(row, "evidence_summary"):
            reasons.append("EVIDENCE_SUMMARY_MISSING")
            details.append(f"{eid}: evidence summary missing")
        if not valid_locator(clean(row, "source_locator")):
            reasons.append("EVIDENCE_LOCATOR_INVALID")
            details.append(f"{eid}: invalid evidence locator")

        evidence_by_claim.setdefault(cid, []).append(row)
        counts["reviewed_evidence_count"] += 1
        if relation in ("CONTRADICTS", "MIXED"):
            counts["conflict_count"] += 1

    explicit_rejections = []
    for cid, claim in claim_map.items():
        status = clean(claim, "claim_status").upper()
        text = clean(claim, "claim_text")
        limitations = clean(claim, "limitations")
        linked = evidence_by_claim.get(cid, [])
        supports = [
            item for item in linked
            if clean(item, "evidence_relation").upper() == "SUPPORTS"
            and clean(item, "review_status").upper() == "REVIEWED"
            and clean(item, "evidence_summary")
            and valid_locator(clean(item, "source_locator"))
        ]
        conflicts = [
            item for item in linked
            if clean(item, "evidence_relation").upper() in ("CONTRADICTS", "MIXED")
        ]

        if status in ("UNSUPPORTED", "REJECTED", "FALSE"):
            explicit_rejections.append(cid)
            continue
        if not text:
            reasons.append("CLAIM_TEXT_MISSING")
            details.append(f"{cid}: empty claim text")
        if not limitations:
            reasons.append("CLAIM_LIMITATIONS_MISSING")
            details.append(f"{cid}: limitations missing")
        if not supports:
            reasons.append("CLAIM_WITHOUT_REVIEWED_SUPPORT")
            details.append(f"{cid}: no complete reviewed supporting evidence")
        if conflicts:
            reasons.append("CLAIM_HAS_CONFLICTING_EVIDENCE")
            details.append(f"{cid}: conflicting or mixed evidence")
        if status != "SUPPORTED":
            reasons.append("CLAIM_NOT_SUPPORTED")
            details.append(f"{cid}: claim status is {status or 'MISSING'}")
        else:
            counts["supported_claim_count"] += 1

    if explicit_rejections:
        decision = "AUTO_REJECT"
        reasons.append("EXPLICIT_UNSUPPORTED_CLAIMS")
        details.append("Explicitly rejected claims: " + ", ".join(explicit_rejections))
    elif reasons:
        decision = "HOLD"
    else:
        # Metadata and manually entered REVIEWED labels cannot prove that
        # the source content was independently checked. Fail closed.
        decision = "HOLD"
        reasons.append("SOURCE_CONTENT_NOT_INDEPENDENTLY_VERIFIED")
        details.append(
            "Source URLs and manually entered review statuses do not "
            "establish independent verification of source content."
        )

    return {
        "decision": decision,
        "reasons": sorted(set(reasons)),
        "details": details,
        "counts": counts,
        "fingerprint": fingerprint(sources, claims, evidence),
    }


def _read_decision_history(path):
    path = Path(path)
    if not path.exists():
        return [], False
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames
        if headers is None:
            return [], True
        if headers != DECISION_FIELDS:
            raise ValueError(
                "Decision history CSV header mismatch; refusing to rewrite "
                f"or append. Found: {headers}"
            )
        return list(reader), True


def record_decision(row, path=None):
    """Append once; on duplicate, do not open the history file for writing."""
    target = Path(path or DECISIONS_OUT)
    existing, file_exists = _read_decision_history(target)

    duplicate = next(
        (
            old for old in existing
            if clean(old, "video_id") == clean(row, "video_id")
            and clean(old, "stage") == clean(row, "stage")
            and clean(old, "decision") == clean(row, "decision")
            and clean(old, "input_fingerprint") == clean(row, "input_fingerprint")
        ),
        None,
    )
    if duplicate:
        return clean(duplicate, "decision_id"), "SKIPPED_IDENTICAL_DECISION"

    target.parent.mkdir(parents=True, exist_ok=True)
    new_file = not target.exists() or target.stat().st_size == 0
    mode = "a"
    append_encoding = "utf-8-sig" if new_file else "utf-8"
    with target.open(mode, encoding=append_encoding, newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=DECISION_FIELDS, extrasaction="raise"
        )
        if new_file:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()
        os.fsync(handle.fileno())
    return clean(row, "decision_id"), "APPENDED_NEW_DECISION"


def atomic_write_json(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n",
            dir=str(target.parent), prefix=target.name + ".",
            suffix=".tmp", delete=False
        ) as handle:
            temp_name = handle.name
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def build_row(result, decision_id, timestamp):
    counts = result["counts"]
    return {
        "decision_id": decision_id,
        "video_id": PILOT_ID,
        "stage": "RESEARCH",
        "decision": result["decision"],
        "ruleset_version": RULESET_VERSION,
        "decided_at": timestamp,
        "reason_codes": "|".join(result["reasons"]),
        "reason_details": " | ".join(result["details"]),
        "source_count": counts.get("source_count", 0),
        "reviewed_source_count": counts.get("reviewed_source_count", 0),
        "claim_count": counts.get("claim_count", 0),
        "supported_claim_count": counts.get("supported_claim_count", 0),
        "evidence_count": counts.get("evidence_count", 0),
        "reviewed_evidence_count": counts.get("reviewed_evidence_count", 0),
        "conflict_count": counts.get("conflict_count", 0),
        "input_fingerprint": result["fingerprint"],
    }


def main():
    timestamp = current_timestamp()
    print("=" * 68)
    print("AUTOMATED APPROVAL ENGINE V1")
    print("=" * 68)

    if not TOPIC_DECISIONS.is_file():
        raise FileNotFoundError(TOPIC_DECISIONS)
    topic_rows = read_csv(TOPIC_DECISIONS)
    topic_map = {
        clean(row, "video_id"): row
        for row in topic_rows if clean(row, "video_id")
    }
    topic = topic_map.get(PILOT_ID)
    if not topic:
        raise RuntimeError("Pilot topic decision record not found")

    topic_status = clean(topic, "decision").upper()
    if topic_status != "APPROVE":
        raise RuntimeError(
            "Pilot topic is not approved in existing topic records. "
            "Research engine will not bypass this prerequisite."
        )

    result = evaluate_research(PILOT_ID)
    historical_human = read_csv(HUMAN_RESEARCH_DECISIONS)
    human_record = next(
        (row for row in historical_human if clean(row, "video_id") == PILOT_ID),
        None,
    )

    proposed_id = f"AA1_{PILOT_ID}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
    row = build_row(result, proposed_id, timestamp)
    decision_id, history_action = record_decision(row)

    report = {
        "engine": "AUTOMATED_APPROVAL_ENGINE_V1",
        "ruleset_version": RULESET_VERSION,
        "generated_at": timestamp,
        "decision_id": decision_id,
        "video_id": PILOT_ID,
        "topic_gate": {
            "status": "PASS",
            "source": "existing_human_topic_decision",
            "decision": topic_status,
        },
        "research_gate": {
            "decision": result["decision"],
            "reason_codes": result["reasons"],
            "reason_details": result["details"],
            "counts": result["counts"],
            "input_fingerprint": result["fingerprint"],
            "historical_human_decision": (
                clean(human_record, "research_decision") if human_record else "NO_RECORD"
            ),
        },
        "script_gate": {
            "decision": "HOLD",
            "reason": "Script artifact not yet registered and evaluated",
        },
        "production_gate": {
            "decision": "HOLD",
            "reason": "Actual rendered assets and production QA not evaluated",
        },
        "publishing_gate": {
            "decision": "HOLD",
            "reason": "No separate publishing authorization configured",
        },
        "database_modified": False,
        "existing_human_records_modified": False,
        "youtube_api_calls": 0,
        "rendering_started": False,
        "publishing_authorized": False,
        "decision_history_action": history_action,
    }
    atomic_write_json(REPORT_OUT, report)

    audit = {
        "decision_id": decision_id,
        "created_at": timestamp,
        "ruleset_version": RULESET_VERSION,
        "input_fingerprint": result["fingerprint"],
        "input_files": [
            str(WORKSPACE / PILOT_ID / "sources.csv"),
            str(WORKSPACE / PILOT_ID / "claims.csv"),
            str(WORKSPACE / PILOT_ID / "evidence.csv"),
            str(TOPIC_DECISIONS),
            str(HUMAN_RESEARCH_DECISIONS),
        ],
        "decision": result["decision"],
        "reason_codes": result["reasons"],
        "reason_details": result["details"],
        "human_decision_preserved": True,
        "decision_history_action": history_action,
        "database_modified": False,
        "youtube_api_calls": 0,
    }
    atomic_write_json(AUDIT_OUT, audit)

    print("Pilot:", PILOT_ID)
    print("Topic prerequisite:", topic_status)
    print("Research decision:", result["decision"])
    print("History action:", history_action)
    print("Decision ID:", decision_id)
    print("Reasons:", ", ".join(result["reasons"]))
    print("Counts:", json.dumps(result["counts"], ensure_ascii=False))
    print("PASS: human records read-only; DB/API/render/upload untouched")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ENGINE ERROR:", str(exc))
        sys.exit(1)
