
from pathlib import Path
import csv

ROOT = Path(r"G:\youtube automation")
DATA = ROOT / "data" / "research" / "youtube_universe_v33"
PILOT = "E1irX9cDX8U"

KEYWORDS = (
    "rank", "score", "source", "claim", "evidence",
    "decision", "approval", "script", "production",
    "quality", "audit", "dashboard", "transcript"
)

def read_csv(path):
    for encoding in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode: {path}")

def short(value, limit=180):
    value = str(value or "").replace("\n", " ").replace("\r", " ")
    return value[:limit] + ("..." if len(value) > limit else "")

print("=" * 68)
print("BATCH 10 — AUTOMATED APPROVAL ENGINE PREFLIGHT")
print("=" * 68)
print("MODE: STRICTLY READ ONLY")
print("PILOT:", PILOT)

if not DATA.exists():
    raise SystemExit(f"DATA DIRECTORY NOT FOUND: {DATA}")

print("\n1. RELEVANT CSV INVENTORY")

csv_files = sorted(
    p for p in DATA.rglob("*.csv")
    if any(k in p.name.lower() for k in KEYWORDS)
)

for p in csv_files:
    print(" ", p.relative_to(ROOT))

print("\n2. CSV SCHEMAS, COUNTS AND PILOT RECORDS")

for p in csv_files:
    try:
        rows = read_csv(p)
        columns = list(rows[0].keys()) if rows else []

        print("\nFILE:", p.relative_to(ROOT))
        print("ROWS:", len(rows))
        print("COLUMNS:", columns)

        pilot_rows = [
            row for row in rows
            if any(
                str(value).strip() == PILOT
                for key, value in row.items()
                if key.lower() in ("video_id", "youtube_id", "topic_id")
            )
        ]

        if pilot_rows:
            for row in pilot_rows[:3]:
                print("PILOT ROW:")
                for key, value in row.items():
                    print(f"  {key}: {short(value)}")

    except Exception as exc:
        print("READ ERROR:", repr(exc))

print("\n3. PILOT RESEARCH PACKAGE INVENTORY")

package_dir = DATA / "research_packages_v33"

if package_dir.exists():
    for p in sorted(package_dir.glob("*.md")):
        print(
            p.name,
            "| bytes:", p.stat().st_size
        )
else:
    print("Research package directory not found.")

print("\n4. SCRIPT / APPROVAL / PRODUCTION REFERENCES")

app_dir = ROOT / "app"

terms = (
    "script_approval", "production_approval",
    "research_decision", "human_decision",
    "content_quality_status", "claim_status",
    "evidence_status", "qa_status"
)

for p in sorted(app_dir.glob("*.py")):
    try:
        lines = p.read_text(encoding="utf-8-sig").splitlines()
        matches = [
            (i, line.strip())
            for i, line in enumerate(lines, 1)
            if any(term in line.lower() for term in terms)
        ]

        if matches:
            print("\nFILE:", p.name)
            for number, line in matches[:12]:
                print(f"  {number}: {short(line, 220)}")

    except Exception as exc:
        print("READ ERROR:", p.name, repr(exc))

print("\n" + "=" * 68)
print("PREFLIGHT COMPLETE")
print("DATABASE MODIFIED: NO")
print("CSV / JSON / MARKDOWN MODIFIED: NO")
print("YOUTUBE API CALLED: NO")
print("PRODUCTION STARTED: NO")
print("=" * 68)
