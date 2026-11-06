
import csv
from pathlib import Path

BASE = Path("data/research/youtube_universe_v33")

FILES = [
    "latest_candidate_ranking_v33.csv",
    "latest_human_review_queue_v33.csv",
    "latest_human_review_audit_v33.csv",
    "latest_research_workbench_queue_v33.csv",
    "latest_final_audit_v33.csv",
    "latest_research_package_queue_v33.csv",
    "research_review_decisions_v33.csv",
]

for name in FILES:
    path = BASE / name
    print("\n" + "=" * 75)
    print("FILE:", name)

    if not path.exists():
        print("MISSING")
        continue

    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        print("\nCOLUMNS:")
        print(reader.fieldnames)

        first = next(reader, None)
        print("\nFIRST RECORD:")
        if first:
            for key, value in first.items():
                print(f"{key}: {value}")
        else:
            print("NO DATA ROWS")

print("\n" + "=" * 75)
print("SCHEMA INSPECTION COMPLETE")
