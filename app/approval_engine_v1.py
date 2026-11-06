
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse
import csv
import json
import hashlib
import sys

BASE = Path("data/research/youtube_universe_v33")
WORKSPACE = BASE / "research_workspace_v33"

TOPIC_DECISIONS = BASE / "human_review_decisions_v33.csv"
HUMAN_RESEARCH_DECISIONS = BASE / "research_review_decisions_v33.csv"

DECISIONS_OUT = BASE / "automated_approval_decisions_v1.csv"
REPORT_OUT = BASE / "latest_automated_approval_report_v1.json"
AUDIT_OUT = BASE / "automated_approval_audit_v1.json"

PILOT_ID = "E1irX9cDX8U"

NOW = datetime.now().astimezone()
TIMESTAMP = NOW.isoformat(timespec="seconds")

DECISION_FIELDS = [
    "decision_id",
    "video_id",
    "stage",
    "decision",
    "ruleset_version",
    "decided_at",
    "reason_codes",
    "reason_details",
    "source_count",
    "reviewed_source_count",
    "claim_count",
    "supported_claim_count",
    "evidence_count",
    "reviewed_evidence_count",
    "conflict_count",
    "input_fingerprint",
]

def read_csv(path):
    if not path.exists():
        raise FileNotFoundError(f"Required file missing: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def clean(row, key):
    return str(row.get(key, "") or "").strip()

def duplicate_values(rows, key):
    values = [clean(row, key) for row in rows]
    values = [v for v in values if v]
    return sorted({v for v in values if values.count(v) > 1})

def valid_locator(value):
    value = value.strip()

    if value.lower().startswith("doi:"):
        return len(value) > 8

    parsed = urlparse(value)
    return (
        parsed.scheme in ("http", "https")
        and bool(parsed.netloc)
    )

def fingerprint(sources, claims, evidence):
    payload = {
        "sources": sources,
        "claims": claims,
        "evidence": evidence,
    }

    raw = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")

    return hashlib.sha256(raw).hexdigest()

def evaluate_research(video_id):
    folder = WORKSPACE / video_id

    reasons = []
    details = []

    paths = {
        "sources": folder / "sources.csv",
        "claims": folder / "claims.csv",
        "evidence": folder / "evidence.csv",
    }

    missing = [str(p) for p in paths.values() if not p.exists()]

    if missing:
        return {
            "decision": "HOLD",
            "reasons": ["RESEARCH_FILES_MISSING"],
            "details": missing,
            "counts": {},
            "fingerprint": "",
        }

    sources = read_csv(paths["sources"])
    claims = read_csv(paths["claims"])
    evidence = read_csv(paths["evidence"])

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
        if duplicate_values(rows, key):
            reasons.append(f"DUPLICATE_{label}_IDS")
            details.append(
                f"{label} duplicate IDs: "
                + ", ".join(duplicate_values(rows, key))
            )

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

        if relation not in (
            "SUPPORTS", "CONTRADICTS", "MIXED", "CONTEXT"
        ):
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
        ]

        conflicts = [
            item for item in linked
            if clean(item, "evidence_relation").upper()
            in ("CONTRADICTS", "MIXED")
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
            details.append(f"{cid}: no reviewed supporting evidence")

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
        details.append(
            "Explicitly rejected claims: "
            + ", ".join(explicit_rejections)
        )

    elif reasons:
        decision = "HOLD"

    else:
        decision = "AUTO_APPROVE"
        reasons.append("ALL_RESEARCH_RULES_PASSED")

    return {
        "decision": decision,
        "reasons": sorted(set(reasons)),
        "details": details,
        "counts": counts,
        "fingerprint": fingerprint(sources, claims, evidence),
    }

def main():
    print("=" * 68)
    print("AUTOMATED APPROVAL ENGINE V1")
    print("=" * 68)

    if not TOPIC_DECISIONS.exists():
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

    # Existing human research decision is read only.
    historical_human = read_csv(HUMAN_RESEARCH_DECISIONS)
    human_record = next(
        (
            row for row in historical_human
            if clean(row, "video_id") == PILOT_ID
        ),
        None,
    )

    decision_id = (
        f"AA1_{PILOT_ID}_{NOW.strftime('%Y%m%d_%H%M%S')}"
    )

    counts = result["counts"]

    row = {
        "decision_id": decision_id,
        "video_id": PILOT_ID,
        "stage": "RESEARCH",
        "decision": result["decision"],
        "ruleset_version": "1.0.0",
        "decided_at": TIMESTAMP,
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

    # Append-only decision history. Never overwrite previous decisions.
    existing = []
    if DECISIONS_OUT.exists():
        existing = read_csv(DECISIONS_OUT)

    existing.append(row)

    with DECISIONS_OUT.open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=DECISION_FIELDS,
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(existing)

    report = {
        "engine": "AUTOMATED_APPROVAL_ENGINE_V1",
        "ruleset_version": "1.0.0",
        "generated_at": TIMESTAMP,
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
            "counts": counts,
            "input_fingerprint": result["fingerprint"],
            "historical_human_decision": (
                clean(human_record, "research_decision")
                if human_record else "NO_RECORD"
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
    }

    REPORT_OUT.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    audit = {
        "decision_id": decision_id,
        "created_at": TIMESTAMP,
        "ruleset_version": "1.0.0",
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
        "database_modified": False,
        "youtube_api_calls": 0,
    }

    AUDIT_OUT.write_text(
        json.dumps(audit, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Pilot:", PILOT_ID)
    print("Topic prerequisite:", topic_status)
    print("Research decision:", result["decision"])
    print("Reasons:", ", ".join(result["reasons"]))
    print("Sources:", counts.get("source_count", 0))
    print("Reviewed sources:", counts.get("reviewed_source_count", 0))
    print("Claims:", counts.get("claim_count", 0))
    print("Supported claims:", counts.get("supported_claim_count", 0))
    print("Evidence:", counts.get("evidence_count", 0))
    print("Reviewed evidence:", counts.get("reviewed_evidence_count", 0))
    print("Conflicts:", counts.get("conflict_count", 0))
    print()
    print("PASS: automated decision history written")
    print("PASS: audit report written")
    print("PASS: human decisions preserved")
    print("PASS: database untouched")
    print("PASS: no YouTube API calls")
    print("PASS: no rendering or publishing")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("ENGINE ERROR:", str(exc))
        sys.exit(1)
