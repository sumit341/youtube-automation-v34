
import sqlite3
from pathlib import Path

databases = {
    "V32": Path("data/research/youtube_universe_v32/youtube_universe.db"),
    "V33": Path("data/research/youtube_universe_v33/youtube_universe.db"),
}

counts = {}

for label, path in databases.items():
    print(f"\n--- {label} DATABASE ---")
    connection = sqlite3.connect(
        f"file:{path.resolve().as_posix()}?mode=ro", uri=True
    )

    counts[label] = {}
    for table in ("videos", "discovered_videos", "scan_runs", "search_pages"):
        count = connection.execute(
            f'SELECT COUNT(*) FROM "{table}"'
        ).fetchone()[0]
        counts[label][table] = count
        print(f"{table}: {count:,}")

    connection.close()

print("\n--- SUMMARY ---")
for table in ("videos", "discovered_videos", "scan_runs", "search_pages"):
    print(
        f"{table}: V32={counts['V32'][table]:,} | "
        f"V33={counts['V33'][table]:,}"
    )

print("\nREAD-ONLY CHECK COMPLETE. NO DATABASE CHANGES.")
