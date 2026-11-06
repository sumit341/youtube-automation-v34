
import csv
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
APP = BASE / "app"
DATA = BASE / "data" / "research" / "youtube_universe_v33"
PILOT = "E1irX9cDX8U"

KEYWORDS = ("script", "production", "approval", "preflight", "gate")

def main():
    print("=" * 65)
    print("BATCH 10 — SCRIPT / PRODUCTION PREFLIGHT")
    print("=" * 65)
    print("MODE: READ ONLY")
    print("PILOT:", PILOT)

    print("\n1. RELEVANT APP FILES")
    for path in sorted(APP.glob("*.py")):
        if any(word in path.name.lower() for word in KEYWORDS):
            print(" ", path.name)

    print("\n2. RELEVANT DATA FILES")
    for pattern in ("*.csv", "*.json", "*.md"):
        for path in sorted(DATA.glob(pattern)):
            if any(word in path.name.lower() for word in KEYWORDS):
                print(" ", path.name)

    print("\n3. CSV SCHEMAS AND PILOT ROWS")
    for path in sorted(DATA.glob("*.csv")):
        if not any(word in path.name.lower() for word in KEYWORDS):
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            print("\nFILE:", path.name)
            print("COLUMNS:", reader.fieldnames)
            matches = [r for r in rows if PILOT in str(r.values())]
            for row in matches[:2]:
                print("PILOT ROW:", json.dumps(row, ensure_ascii=False))
        except Exception as e:
            print("READ ERROR:", path.name, type(e).__name__, str(e))

    print("\n4. RELEVANT PYTHON GATE REFERENCES")
    for path in sorted(APP.glob("*.py")):
        if not any(word in path.name.lower() for word in KEYWORDS):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            hits = []
            for number, line in enumerate(lines, 1):
                low = line.lower()
                if any(term in low for term in (
                    "script_approval", "production_approval",
                    "research_decision", "human_decision",
                    "script_status", "production gate"
                )):
                    hits.append((number, line.strip()))
            if hits:
                print("\nFILE:", path.name)
                for number, line in hits[:25]:
                    print(f"{number}: {line[:220]}")
        except Exception as e:
            print("READ ERROR:", path.name, str(e))

    print("\nDATABASE: NOT OPENED")
    print("YOUTUBE API: NOT CALLED")
    print("FILES MODIFIED: NO")
    print("PRODUCTION STARTED: NO")
    print("\nPREFLIGHT COMPLETE — REVIEW OUTPUT BEFORE NEXT ACTION")

if __name__ == "__main__":
    main()
