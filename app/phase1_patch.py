
from pathlib import Path
from datetime import datetime
import shutil
import subprocess
import ast
import sys

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"

FILES = [
    APP / "youtube_universe_scoring_v33.py",
    APP / "youtube_universe_scanner_v30.py",
    APP / "youtube_universe_scanner_v32.py",
    APP / "youtube_universe_research_workbench_v33.py",
    APP / "approval_engine_v1.py",
]


def stop(message):
    print("\nPATCH STOPPED:", message)
    sys.exit(1)


def read_source(path):
    raw = path.read_bytes()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8-sig"), has_bom, raw


def replace_exact(text, old, new, expected, label):
    count = text.count(old)

    if count != expected:
        stop(
            f"{label}: expected {expected} matches, found {count}. "
            "No source files have been changed."
        )

    return text.replace(old, new)


def replace_line_block(text, old_lines, new_lines, expected, label):
    lines = text.splitlines()
    matches = []

    width = len(old_lines)

    for index in range(len(lines) - width + 1):
        if lines[index:index + width] == old_lines:
            matches.append(index)

    if len(matches) != expected:
        stop(
            f"{label}: expected {expected} exact blocks, "
            f"found {len(matches)}. No source files have been changed."
        )

    for index in reversed(matches):
        lines[index:index + width] = new_lines

    return "\n".join(lines) + "\n"


def main():
    print("=" * 68)
    print("YOUTUBE AUTOMATION PHASE 1 SAFE PATCH")
    print("=" * 68)

    if not (ROOT / ".git").exists():
        stop("Project root is not a Git repository.")

    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        cwd=ROOT,
        text=True
    ).strip()

    if branch != "phase1-core-stabilization":
        stop(
            "Expected branch phase1-core-stabilization, "
            f"found {branch}."
        )

    original = {}
    prepared = {}
    bom_flags = {}

    for path in FILES:
        if not path.is_file():
            stop(f"Required file missing: {path}")

        text, bom, raw = read_source(path)

        original[path] = raw
        prepared[path] = text
        bom_flags[path] = bom

    print("\n1. Source files verified.")

    # --------------------------------------------------------
    # V33 SCORER: REMOVE ONLY EXACT DUPLICATE MODULE
    # --------------------------------------------------------

    path = FILES[0]
    text = prepared[path]

    marker = "import argparse"
    first = text.find(marker)

    if first < 0:
        stop("First scorer module not found.")

    second = text.find(marker, first + len(marker))

    if second < 0:
        stop("Second scorer module not found.")

    first_module = text[:second]
    second_module = text[second:]

    if first_module.strip() != second_module.strip():
        stop("Scorer modules are not exactly identical.")

    prepared[path] = first_module.rstrip() + "\n"

    print("2. V33 duplicate module verified.")

    # --------------------------------------------------------
    # V30 / V32 PORTABLE ROOT
    # --------------------------------------------------------

    old_root = 'ROOT = Path(r"G:\\youtube automation")'
    new_root = "ROOT = Path(__file__).resolve().parent.parent"

    prepared[FILES[1]] = replace_exact(
        prepared[FILES[1]],
        old_root,
        new_root,
        2,
        "V30 ROOT"
    )

    prepared[FILES[2]] = replace_exact(
        prepared[FILES[2]],
        old_root,
        new_root,
        1,
        "V32 ROOT"
    )

    print("3. V30/V32 portable roots prepared.")

    # --------------------------------------------------------
    # RESEARCH WORKBENCH: ACCEPT BOTH HISTORICAL LABELS
    # --------------------------------------------------------

    old_double = 'research_decision == "APPROVE_RESEARCH"'
    new_double = (
        'research_decision in ("APPROVE", "APPROVE_RESEARCH")'
    )

    prepared[FILES[3]] = replace_exact(
        prepared[FILES[3]],
        old_double,
        new_double,
        2,
        "Research decision double-quoted expressions"
    )

    old_single = "research_decision == 'APPROVE_RESEARCH'"
    new_single = (
        "research_decision in ('APPROVE', 'APPROVE_RESEARCH')"
    )

    prepared[FILES[3]] = replace_exact(
        prepared[FILES[3]],
        old_single,
        new_single,
        1,
        "Research decision single-quoted expression"
    )

    print("4. Research decision compatibility prepared.")

    # --------------------------------------------------------
    # APPROVAL ENGINE: NO APPROVAL WITHOUT SOURCE VERIFICATION
    # --------------------------------------------------------

    approval_old = [
        "    else:",
        '        decision = "AUTO_APPROVE"',
        '        reasons.append("ALL_RESEARCH_RULES_PASSED")',
    ]

    approval_new = [
        "    else:",
        '        decision = "HOLD"',
        '        reasons.append(',
        '            "SOURCE_CONTENT_NOT_INDEPENDENTLY_VERIFIED"',
        "        )",
        "        details.append(",
        '            "Source URLs and manually entered review statuses do not "',
        '            "establish independent verification of source content."',
        "        )",
    ]

    prepared[FILES[4]] = replace_line_block(
        prepared[FILES[4]],
        approval_old,
        approval_new,
        1,
        "Approval safety gate"
    )

    print("5. Approval safety gate prepared.")

    # --------------------------------------------------------
    # DECISION HISTORY: AVOID IDENTICAL REPEATED DECISIONS
    # --------------------------------------------------------

    history_old = [
        "    # Append-only decision history. Never overwrite previous decisions.",
        "    existing = []",
        "    if DECISIONS_OUT.exists():",
        "        existing = read_csv(DECISIONS_OUT)",
        "",
        "    existing.append(row)",
    ]

    history_new = [
        "    # Preserve history; avoid duplicate identical decisions.",
        "    existing = []",
        "    if DECISIONS_OUT.exists():",
        "        existing = read_csv(DECISIONS_OUT)",
        "",
        "    duplicate_exists = any(",
        '        clean(old, "video_id") == PILOT_ID',
        '        and clean(old, "stage") == "RESEARCH"',
        '        and clean(old, "decision") == result["decision"]',
        '        and clean(old, "input_fingerprint") == result["fingerprint"]',
        "        for old in existing",
        "    )",
        "",
        '    if duplicate_exists:',
        '        history_action = "SKIPPED_IDENTICAL_DECISION"',
        "    else:",
        "        existing.append(row)",
        '        history_action = "APPENDED_NEW_DECISION"',
    ]

    prepared[FILES[4]] = replace_line_block(
        prepared[FILES[4]],
        history_old,
        history_new,
        1,
        "Decision history idempotency"
    )

    # --------------------------------------------------------
    # AUDIT HISTORY ACTION IN REPORT
    # --------------------------------------------------------

    report_old = [
        '        "publishing_authorized": False,',
    ]

    report_new = [
        '        "publishing_authorized": False,',
        '        "decision_history_action": history_action,',
    ]

    prepared[FILES[4]] = replace_line_block(
        prepared[FILES[4]],
        report_old,
        report_new,
        1,
        "Report audit field"
    )

    audit_old = [
        '        "human_decision_preserved": True,',
    ]

    audit_new = [
        '        "human_decision_preserved": True,',
        '        "decision_history_action": history_action,',
    ]

    prepared[FILES[4]] = replace_line_block(
        prepared[FILES[4]],
        audit_old,
        audit_new,
        1,
        "Audit history field"
    )

    print("6. Duplicate-history protection prepared.")

    # --------------------------------------------------------
    # SYNTAX VALIDATION BEFORE ANY WRITE
    # --------------------------------------------------------

    for path in FILES:
        try:
            ast.parse(prepared[path], filename=str(path))
        except SyntaxError as exc:
            stop(f"Syntax error in {path}: {exc}")

    print("7. All prepared source files passed syntax validation.")

    # --------------------------------------------------------
    # BACKUP ALL SOURCE FILES
    # --------------------------------------------------------

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    backup_dir = ROOT / "backups" / f"phase1_patch_{stamp}"

    backup_dir.mkdir(parents=True, exist_ok=False)

    for path in FILES:
        shutil.copy2(path, backup_dir / path.name)

    print("8. Backup created:", backup_dir)

    # --------------------------------------------------------
    # ATOMIC WRITES + ROLLBACK ON FAILURE
    # --------------------------------------------------------

    written = []

    try:
        for path in FILES:
            content = prepared[path].encode("utf-8")

            if bom_flags[path]:
                content = b"\xef\xbb\xbf" + content

            temp_path = path.with_name(
                path.name + ".phase1tmp"
            )

            temp_path.write_bytes(content)
            temp_path.replace(path)

            written.append(path)

        for path in FILES:
            ast.parse(
                path.read_text(encoding="utf-8-sig"),
                filename=str(path)
            )

    except Exception as exc:
        print("\nWRITE ERROR:", repr(exc))
        print("Restoring original source files...")

        for path in written:
            path.write_bytes(original[path])

        stop("Write failed. Original source files restored.")

    # --------------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------------

    print("\n" + "=" * 68)
    print("PHASE 1 PATCH SUCCESS")
    print("=" * 68)

    print("Branch:", branch)
    print("Updated source files:", len(FILES))
    print("V33 duplicate module: removed")
    print("V30/V32 ROOT: portable")
    print("Research labels: APPROVE and APPROVE_RESEARCH accepted")
    print("Research source verification: HOLD required")
    print("Duplicate decision records: prevented")
    print("Historical records: preserved")
    print("Database files: not modified by patch")
    print("YouTube API calls: none")
    print("Rendering/upload: not started")
    print("Python syntax: PASS")
    print("Backup:", backup_dir)


if __name__ == "__main__":
    main()
