
import csv
import shutil
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DECISIONS = BASE / "data" / "research" / "youtube_universe_v33" / "research_review_decisions_v33.csv"
BACKUP_DIR = BASE / "backups" / f"research_approval_{datetime.now():%Y%m%d_%H%M%S}"

VIDEO_ID = "E1irX9cDX8U"
DECISION = "APPROVE"
NOTES = (
    "Six sources and claims reviewed. Accept with limitations; "
    "avoid universal and causal claims. Proceed to Roman Hinglish script drafting."
)

def main():
    if not DECISIONS.exists():
        raise FileNotFoundError(f"Decision file missing: {DECISIONS}")

    with DECISIONS.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("Decision CSV has no header.")

        fields = list(reader.fieldnames)
        rows = list(reader)

    required = {"video_id", "research_decision"}
    missing = required - set(fields)
    if missing:
        raise ValueError(f"Required columns missing: {sorted(missing)}")

    matches = [r for r in rows if r.get("video_id", "").strip() == VIDEO_ID]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one pilot row; found {len(matches)}. No changes made."
        )

    current = matches[0].get("research_decision", "").strip().upper()
    if current not in {"", "PENDING", "APPROVE"}:
        raise ValueError(
            f"Existing decision is {current!r}; refusing to overwrite it."
        )

    if "reviewer_notes" not in fields:
        fields.append("reviewer_notes")

    # Preserve the original before any write.
    BACKUP_DIR.mkdir(parents=True, exist_ok=False)
    backup_path = BACKUP_DIR / DECISIONS.name
    shutil.copy2(DECISIONS, backup_path)

    matches[0]["research_decision"] = DECISION
    matches[0]["reviewer_notes"] = NOTES

    temp_path = DECISIONS.with_name(DECISIONS.stem + ".tmp.csv")
    with temp_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    temp_path.replace(DECISIONS)

    # Read-after-write verification.
    with DECISIONS.open("r", encoding="utf-8-sig", newline="") as f:
        verified = list(csv.DictReader(f))

    check = [r for r in verified if r.get("video_id", "").strip() == VIDEO_ID]
    if len(check) != 1:
        raise RuntimeError("Verification failed: pilot row count changed.")

    if check[0].get("research_decision", "").strip().upper() != DECISION:
        raise RuntimeError("Verification failed: decision was not saved.")

    if check[0].get("reviewer_notes", "").strip() != NOTES:
        raise RuntimeError("Verification failed: reviewer notes mismatch.")

    print("=" * 62)
    print("RESEARCH DECISION SAVE — PASS")
    print("Pilot video ID:", VIDEO_ID)
    print("Research decision:", DECISION)
    print("Reviewer notes: VERIFIED")
    print("Backup:", backup_path)
    print("Decision CSV: VERIFIED")
    print("YouTube API calls: 0")
    print("V3.3 database modified: NO")
    print("Topic human-review decision modified: NO")
    print("Script approval: NOT GRANTED")
    print("Production approval: NOT GRANTED")

if __name__ == "__main__":
    main()
