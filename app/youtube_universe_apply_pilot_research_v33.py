import csv
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "research" / "youtube_universe_v33"

VIDEO_ID = "E1irX9cDX8U"
TODAY = "2026-11-06"

HUMAN_FILE = BASE / "human_review_decisions_v33.csv"
RESEARCH_DECISIONS_FILE = BASE / "research_review_decisions_v33.csv"

WORKSPACE = BASE / "research_workspace_v33" / VIDEO_ID
SOURCES_FILE = WORKSPACE / "sources.csv"
CLAIMS_FILE = WORKSPACE / "claims.csv"
EVIDENCE_FILE = WORKSPACE / "evidence.csv"

BACKUP_DIR = ROOT / "backups" / "pilot_research_20261106"

SOURCE_FIELDS = [
    "source_id", "title", "author", "organization", "published_date",
    "source_type", "url_or_doi", "accessed_date",
    "source_review_status", "notes"
]

CLAIM_FIELDS = [
    "claim_id", "claim_text", "claim_type", "importance",
    "claim_status", "limitations", "reviewer_notes"
]

EVIDENCE_FIELDS = [
    "evidence_id", "claim_id", "source_id", "evidence_relation",
    "evidence_summary", "source_locator", "review_status", "notes"
]

RESEARCH_DECISION_FIELDS = [
    "video_id", "research_decision", "reviewer_notes", "decided_at"
]


def read_csv(path):
    if not path.exists():
        return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")

    with temp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)

    temp.replace(path)


def backup(path):
    if path.exists():
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, BACKUP_DIR / path.name)


def merge_by_id(path, fields, new_rows, key):
    rows, existing_fields = read_csv(path)

    if existing_fields:
        for field in fields:
            if field not in existing_fields:
                existing_fields.append(field)
        output_fields = existing_fields
    else:
        output_fields = fields

    existing_ids = {
        str(row.get(key, "")).strip()
        for row in rows
    }

    added = 0
    for new_row in new_rows:
        record_id = str(new_row.get(key, "")).strip()
        if record_id and record_id not in existing_ids:
            rows.append(new_row)
            existing_ids.add(record_id)
            added += 1

    backup(path)
    write_csv(path, rows, output_fields)
    return added, len(rows)


def main():
    print("=" * 65)
    print("YOUTUBE UNIVERSE V3.3")
    print("PILOT RESEARCH DATA IMPORT")
    print("=" * 65)

    if not HUMAN_FILE.exists():
        raise FileNotFoundError(
            f"Human review decisions file missing: {HUMAN_FILE}"
        )

    human_rows, human_fields = read_csv(HUMAN_FILE)

    if "video_id" not in human_fields or "decision" not in human_fields:
        raise ValueError(
            "Human decisions CSV must contain video_id and decision columns."
        )

    target_rows = [
        row for row in human_rows
        if row.get("video_id", "").strip() == VIDEO_ID
    ]

    if len(target_rows) != 1:
        raise ValueError(
            f"Expected exactly one decision row for {VIDEO_ID}; "
            f"found {len(target_rows)}. No changes made."
        )

    target = target_rows[0]
    old_decision = target.get("decision", "").strip().upper()

    if old_decision not in ("", "PENDING", "APPROVE"):
        raise ValueError(
            f"Existing decision is {old_decision}. "
            "Refusing to overwrite it."
        )

    target["decision"] = "APPROVE"

    if "decision_reason" in human_fields:
        target["decision_reason"] = (
            "User explicitly approved this topic for pilot research."
        )

    if "reviewer_notes" in human_fields:
        target["reviewer_notes"] = (
            "Pilot research approved by user on 2026-11-06."
        )

    if "decided_at" in human_fields:
        target["decided_at"] = "2026-11-06"

    backup(HUMAN_FILE)
    write_csv(HUMAN_FILE, human_rows, human_fields)

    WORKSPACE.mkdir(parents=True, exist_ok=True)

    sources = [
        {
            "source_id": "S01",
            "title": "When Thinking Impairs Sleep: Trait, Daytime and Nighttime Repetitive Thinking in Insomnia",
            "author": "Lancee J, Eisma MC, van Zanten KB, Topper M",
            "organization": "University of Amsterdam; Utrecht University",
            "published_date": "2017-01",
            "source_type": "Primary study",
            "url_or_doi": "https://doi.org/10.1080/15402002.2015.1083022",
            "accessed_date": TODAY,
            "source_review_status": "REVIEWED",
            "notes": "Two studies: 139 and 64 participants. Abstract reviewed. Nighttime sleep-related worry was consistently associated with sleep impairment. Not proof that all people overthink more at night."
        },
        {
            "source_id": "S02",
            "title": "Bedtime repetitive negative thinking moderates the relationship between psychological stress and insomnia",
            "author": "Benham G",
            "organization": "University of Texas Rio Grande Valley",
            "published_date": "2021-12",
            "source_type": "Primary study",
            "url_or_doi": "https://doi.org/10.1002/smi.3055",
            "accessed_date": TODAY,
            "source_review_status": "REVIEWED",
            "notes": "Study of 507 undergraduates. Observational findings; association/moderation does not establish causation or generalize automatically to everyone."
        },
        {
            "source_id": "S03",
            "title": "Cognitive factors and processes in models of insomnia: A systematic review",
            "author": "Tang NKY, Saconi B, Jansson-Frojmark M, Ong JC, Carney CE",
            "organization": "University of Warwick and collaborating institutions",
            "published_date": "2023-12",
            "source_type": "Systematic review",
            "url_or_doi": "https://doi.org/10.1111/jsr.13923",
            "accessed_date": TODAY,
            "source_review_status": "REVIEWED",
            "notes": "Review identified 12 theoretical models for synthesis and multiple cognitive factors. Insomnia is multifactorial; no single factor explains every case."
        },
        {
            "source_id": "S04",
            "title": "Sleep loss and emotion: A systematic review and meta-analysis of over 50 years of experimental research",
            "author": "Palmer CA, Bower JL, Cho KW, Clementi MA, Lau S, Oosterhoff B, Alfano CA",
            "organization": "Montana State University and collaborating institutions",
            "published_date": "2024-04",
            "source_type": "Systematic review and meta-analysis",
            "url_or_doi": "https://doi.org/10.1037/bul0000410",
            "accessed_date": TODAY,
            "source_review_status": "REVIEWED",
            "notes": "154 studies; N=5717. Sleep loss reduced positive affect and increased anxiety symptoms. Negative affect findings were mixed."
        },
        {
            "source_id": "S05",
            "title": "Does cognitive behaviour therapy for insomnia reduce repetitive negative thinking and sleep-related worry beliefs? A systematic review and meta-analysis",
            "author": "Ballesio A, Bacaro V, Vacca M, Chirico A, Lucidi F, Riemann D, Baglioni C, Lombardo C",
            "organization": "Collaborating sleep and psychology research institutions",
            "published_date": "2021-02",
            "source_type": "Systematic review and meta-analysis",
            "url_or_doi": "https://doi.org/10.1016/j.smrv.2020.101378",
            "accessed_date": TODAY,
            "source_review_status": "REVIEWED",
            "notes": "15 randomized controlled trials. CBT-I showed moderate-to-large effects on worry; effects on rumination were small and not reliable."
        },
        {
            "source_id": "S06",
            "title": "Behavioral and psychological treatments for chronic insomnia disorder in adults: An American Academy of Sleep Medicine clinical practice guideline",
            "author": "Edinger JD et al.",
            "organization": "American Academy of Sleep Medicine",
            "published_date": "2021-02",
            "source_type": "Clinical practice guideline",
            "url_or_doi": "https://doi.org/10.5664/jcsm.8986",
            "accessed_date": TODAY,
            "source_review_status": "REVIEWED",
            "notes": "AASM guideline strongly recommends multicomponent CBT-I for chronic insomnia in adults. Sleep hygiene alone is not recommended as a standalone treatment."
        }
    ]

    claims = [
        {
            "claim_id": "C01",
            "claim_text": "Among people with sleep problems, nighttime sleep-related worry was consistently associated with sleep impairment in the two studies reported by Lancee and colleagues. The same study did not find equally consistent associations for trait and daytime repetitive thinking.",
            "claim_type": "EMPIRICAL_ASSOCIATION",
            "importance": "HIGH",
            "claim_status": "SUPPORTED",
            "limitations": "Evidence comes from people with sleep problems and does not prove that everyone experiences more overthinking at night.",
            "reviewer_notes": "Supported by S01 abstract; retain population and association qualifiers."
        },
        {
            "claim_id": "C02",
            "claim_text": "In a sample of 507 undergraduate students, bedtime repetitive negative thinking moderated the relationship between perceived psychological stress and insomnia severity.",
            "claim_type": "EMPIRICAL_ASSOCIATION",
            "importance": "HIGH",
            "claim_status": "SUPPORTED",
            "limitations": "The sample was undergraduate students. The observational association does not establish that repetitive thinking causes insomnia.",
            "reviewer_notes": "Supported by S02 abstract; do not present as universal causal law."
        },
        {
            "claim_id": "C03",
            "claim_text": "Worry, rumination, negatively valenced thoughts and cognitive arousal appear across theoretical models of insomnia, while insomnia itself has multifactorial causes.",
            "claim_type": "SYSTEMATIC_REVIEW_FINDING",
            "importance": "HIGH",
            "claim_status": "SUPPORTED",
            "limitations": "The review examined theoretical models; it does not mean every person with insomnia has all these cognitive factors.",
            "reviewer_notes": "Supported by S03."
        },
        {
            "claim_id": "C04",
            "claim_text": "Experimental sleep loss was associated with reduced positive affect and increased anxiety symptoms; findings for negative affect varied by the type of sleep loss and outcome measured.",
            "claim_type": "META_ANALYSIS_FINDING",
            "importance": "HIGH",
            "claim_status": "SUPPORTED",
            "limitations": "This is evidence about effects of sleep loss on emotional functioning, not proof that nighttime thinking is caused by sleep loss.",
            "reviewer_notes": "Preserve the mixed-results qualification for negative affect."
        },
        {
            "claim_id": "C05",
            "claim_text": "For adults with chronic insomnia disorder, the American Academy of Sleep Medicine strongly recommends multicomponent cognitive behavioral therapy for insomnia (CBT-I); sleep hygiene alone is not recommended as a standalone treatment.",
            "claim_type": "CLINICAL_GUIDELINE",
            "importance": "HIGH",
            "claim_status": "SUPPORTED",
            "limitations": "Guideline concerns adults with chronic insomnia disorder. It is not individualized medical advice.",
            "reviewer_notes": "Supported by S06."
        },
        {
            "claim_id": "C06",
            "claim_text": "A systematic review and meta-analysis of 15 randomized trials found CBT-I had moderate-to-large effects on worry, while its effects on rumination were small and not reliable.",
            "claim_type": "TREATMENT_META_ANALYSIS",
            "importance": "MEDIUM",
            "claim_status": "SUPPORTED",
            "limitations": "The evidence base was described as small and developing; do not claim CBT-I eliminates all forms of overthinking.",
            "reviewer_notes": "Supported by S05 abstract."
        }
    ]

    evidence = [
        {
            "evidence_id": "E01",
            "claim_id": "C01",
            "source_id": "S01",
            "evidence_relation": "SUPPORTS",
            "evidence_summary": "Two studies examined repetitive thinking in people with sleep problems. Nighttime sleep-related worry was consistently associated with sleep impairment.",
            "source_locator": "https://pubmed.ncbi.nlm.nih.gov/26651373/",
            "review_status": "REVIEWED",
            "notes": "Abstract reviewed; sample sizes 139 and 64."
        },
        {
            "evidence_id": "E02",
            "claim_id": "C02",
            "source_id": "S02",
            "evidence_relation": "SUPPORTS",
            "evidence_summary": "In 507 undergraduates, bedtime repetitive negative thinking moderated the association between perceived stress and insomnia severity.",
            "source_locator": "https://pubmed.ncbi.nlm.nih.gov/33904245/",
            "review_status": "REVIEWED",
            "notes": "Observational study; avoid causal language."
        },
        {
            "evidence_id": "E03",
            "claim_id": "C03",
            "source_id": "S03",
            "evidence_relation": "SUPPORTS",
            "evidence_summary": "Systematic review synthesized 12 theoretical models and identified recurring cognitive factors, including worry and rumination. The review describes insomnia as multifactorial.",
            "source_locator": "https://pmc.ncbi.nlm.nih.gov/articles/PMC10909484/",
            "review_status": "REVIEWED",
            "notes": "Open-access systematic review."
        },
        {
            "evidence_id": "E04",
            "claim_id": "C04",
            "source_id": "S04",
            "evidence_relation": "SUPPORTS",
            "evidence_summary": "Meta-analysis included 154 studies and 5,717 participants. Sleep loss reduced positive affect and increased anxiety symptoms; negative-affect findings were mixed.",
            "source_locator": "https://pubmed.ncbi.nlm.nih.gov/38127505/",
            "review_status": "REVIEWED",
            "notes": "Do not extend findings to claim that sleep loss directly causes nighttime overthinking."
        },
        {
            "evidence_id": "E05",
            "claim_id": "C05",
            "source_id": "S06",
            "evidence_relation": "SUPPORTS",
            "evidence_summary": "AASM guideline gives a strong recommendation for multicomponent CBT-I for chronic insomnia in adults and advises against sleep hygiene as a single-component treatment.",
            "source_locator": "https://doi.org/10.5664/jcsm.8986",
            "review_status": "REVIEWED",
            "notes": "Clinical practice guideline."
        },
        {
            "evidence_id": "E06",
            "claim_id": "C06",
            "source_id": "S05",
            "evidence_relation": "SUPPORTS",
            "evidence_summary": "Meta-analysis of 15 randomized controlled trials found moderate-to-large effects on worry and small, non-reliable effects on rumination.",
            "source_locator": "https://pubmed.ncbi.nlm.nih.gov/32992228/",
            "review_status": "REVIEWED",
            "notes": "Use cautious language; evidence base is limited."
        }
    ]

    source_added, source_total = merge_by_id(
        SOURCES_FILE, SOURCE_FIELDS, sources, "source_id"
    )
    claim_added, claim_total = merge_by_id(
        CLAIMS_FILE, CLAIM_FIELDS, claims, "claim_id"
    )
    evidence_added, evidence_total = merge_by_id(
        EVIDENCE_FILE, EVIDENCE_FIELDS, evidence, "evidence_id"
    )

    # Create a PENDING research decision only if no decision exists.
    research_rows, research_fields = read_csv(RESEARCH_DECISIONS_FILE)

    if not research_fields:
        research_fields = RESEARCH_DECISION_FIELDS

    if "video_id" not in research_fields or "research_decision" not in research_fields:
        raise ValueError("Research decision CSV has an unexpected schema.")

    existing_decision = [
        row for row in research_rows
        if row.get("video_id", "").strip() == VIDEO_ID
    ]

    if not existing_decision:
        new_decision = {
            "video_id": VIDEO_ID,
            "research_decision": "PENDING",
            "reviewer_notes": "Research package prepared; awaiting user's final review.",
            "decided_at": ""
        }
        research_rows.append(new_decision)
        backup(RESEARCH_DECISIONS_FILE)
        write_csv(RESEARCH_DECISIONS_FILE, research_rows, research_fields)
        research_decision_status = "PENDING (created)"
    else:
        research_decision_status = existing_decision[0].get(
            "research_decision", "UNKNOWN"
        )

    print("\nPILOT TOPIC")
    print("Video ID:", VIDEO_ID)
    print("Human topic decision: APPROVE")

    print("\nRESEARCH DATA IMPORT")
    print("Sources added:", source_added, "| Total:", source_total)
    print("Claims added:", claim_added, "| Total:", claim_total)
    print("Evidence rows added:", evidence_added, "| Total:", evidence_total)

    print("\nRESEARCH DECISION:", research_decision_status)
    print("Final research acceptance: NOT AUTOMATICALLY APPROVED")

    print("\nFILES")
    print("PASS", SOURCES_FILE)
    print("PASS", CLAIMS_FILE)
    print("PASS", EVIDENCE_FILE)
    print("PASS", RESEARCH_DECISIONS_FILE)
    print("BACKUP DIRECTORY:", BACKUP_DIR)

    print("\nDATABASE MODIFIED: NO")
    print("YOUTUBE API CALLS: 0")
    print("STATUS: IMPORT COMPLETED")


if __name__ == "__main__":
    main()