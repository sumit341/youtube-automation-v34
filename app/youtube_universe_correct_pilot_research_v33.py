import csv
import shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "research" / "youtube_universe_v33"
VID = "E1irX9cDX8U"

WORK = BASE / "research_workspace_v33" / VID
BACKUP = ROOT / "backups" / "pilot_research_correction_20261106"

def update_csv(filename, updates, key):
    path = WORK / filename

    if not path.exists():
        raise FileNotFoundError(path)

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)

    if not fields:
        raise ValueError(f"Missing CSV headers: {filename}")

    if key not in fields:
        raise ValueError(f"Missing key column {key}: {filename}")

    BACKUP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, BACKUP / filename)

    changed = 0

    for row in rows:
        record_id = row.get(key, "").strip()

        if record_id in updates:
            row.update(updates[record_id])
            changed += 1

    temp = path.with_suffix(".csv.tmp")

    with temp.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f, fieldnames=fields, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)

    temp.replace(path)

    print(f"PASS {filename}: {changed} records corrected")

    return changed


source_updates = {
    "S01": {
        "notes": (
            "PubMed abstract independently checked. Two studies: "
            "139 and 64 participants. Only nighttime sleep-related "
            "worry was consistently associated with sleep impairment. "
            "Abstract-level verification; not a full-text appraisal."
        )
    },
    "S02": {
        "notes": (
            "Wiley journal abstract independently checked. "
            "507 undergraduate participants. Stress and insomnia "
            "relationship was moderated by bedtime repetitive negative "
            "thinking, with different patterns in insomnia and "
            "non-insomnia subgroups. Observational; not causal. "
            "Abstract-level verification."
        )
    },
    "S03": {
        "notes": (
            "PubMed and open-access PMC record checked. 12 articles "
            "were included in synthesis; review identified 9 distinct "
            "insomnia models and 20 cognitive factors (39 including "
            "sub-factors). Abstract/full bibliographic record checked."
        )
    },
    "S04": {
        "notes": (
            "PubMed abstract independently checked. Meta-analysis: "
            "154 studies, 1,338 effect sizes, N=5,717. Sleep loss "
            "reduced positive affect and increased anxiety symptoms; "
            "negative-affect findings were mixed. Abstract-level "
            "verification."
        )
    },
    "S05": {
        "notes": (
            "PubMed abstract independently checked. 15 randomized "
            "controlled trials. CBT-I effects on worry Hedges g "
            "approximately -0.41 to -0.71; rumination effect g=-0.13 "
            "and not reliable. Abstract-level verification."
        )
    },
    "S06": {
        "notes": (
            "American Academy of Sleep Medicine clinical practice "
            "guideline checked. Strong recommendation for multicomponent "
            "CBT-I for chronic insomnia in adults; conditional "
            "recommendation against sleep hygiene as standalone treatment. "
            "Guideline-level verification."
        )
    }
}

claim_updates = {
    "C01": {
        "claim_text": (
            "In two studies of people with sleep problems (139 and "
            "64 participants), nighttime sleep-related worry was "
            "consistently associated with sleep impairment. Trait "
            "rumination and trait worry were not associated with "
            "sleep impairment in Study 1."
        ),
        "limitations": (
            "Evidence concerns people with sleep problems. It does "
            "not establish that everyone overthinks more at night."
        )
    },
    "C02": {
        "claim_text": (
            "In a sample of 507 undergraduates, bedtime repetitive "
            "negative thinking moderated the relationship between "
            "perceived stress and insomnia severity. The pattern "
            "differed between participants above and below the "
            "insomnia threshold."
        ),
        "limitations": (
            "Observational study in undergraduates. The relationship "
            "does not establish causation or universal applicability."
        )
    },
    "C03": {
        "claim_text": (
            "A systematic review included 12 articles in its synthesis, "
            "identified nine distinct theoretical models of insomnia, "
            "and extracted 20 cognitive factors and processes "
            "(39 when sub-factors were counted)."
        ),
        "limitations": (
            "This review maps theoretical models; it does not mean "
            "every person with insomnia experiences all identified "
            "cognitive factors."
        ),
        "reviewer_notes": (
            "Corrected after checking PubMed and open-access full "
            "bibliographic record. 12 refers to included articles, "
            "not 12 models."
        )
    },
    "C04": {
        "claim_text": (
            "A systematic review and meta-analysis covering 154 studies "
            "and 5,717 participants found that experimental sleep loss "
            "reduced positive affect and increased anxiety symptoms. "
            "Findings for negative affect were mixed."
        ),
        "limitations": (
            "This evidence concerns effects of sleep loss on emotion. "
            "It does not prove that sleep loss causes nighttime "
            "overthinking."
        )
    },
    "C05": {
        "limitations": (
            "The recommendation concerns adults with chronic insomnia "
            "disorder. It is not individualized medical advice."
        )
    },
    "C06": {
        "claim_text": (
            "A systematic review and meta-analysis of 15 randomized "
            "trials found CBT-I had moderate-to-large effects on worry "
            "(Hedges g approximately -0.41 to -0.71), while its effect "
            "on rumination was small and not reliable (g approximately "
            "-0.13)."
        ),
        "limitations": (
            "Evidence base is limited and developing. Do not claim "
            "CBT-I eliminates all forms of overthinking."
        )
    }
}

evidence_updates = {
    "E01": {
        "evidence_summary": (
            "PubMed abstract reports two studies with 139 and 64 "
            "participants. Only nighttime sleep-related worry was "
            "consistently associated with sleep impairment."
        )
    },
    "E02": {
        "evidence_summary": (
            "Wiley journal abstract reports 507 undergraduates. "
            "Bedtime repetitive negative thinking moderated the "
            "stress-insomnia relationship, with differing subgroup "
            "patterns."
        )
    },
    "E03": {
        "evidence_summary": (
            "Systematic review: 12 articles included in synthesis, "
            "nine distinct insomnia models identified, and 20 cognitive "
            "factors extracted (39 including sub-factors)."
        )
    },
    "E04": {
        "evidence_summary": (
            "Meta-analysis: 154 studies, 1,338 effect sizes, N=5,717. "
            "Sleep loss reduced positive affect and increased anxiety; "
            "negative-affect findings were mixed."
        )
    },
    "E05": {
        "evidence_summary": (
            "AASM guideline strongly recommends multicomponent CBT-I "
            "for chronic insomnia in adults. Sleep hygiene alone is "
            "not recommended as a standalone treatment."
        )
    },
    "E06": {
        "evidence_summary": (
            "Meta-analysis of 15 randomized trials: moderate-to-large "
            "effects on worry (g approximately -0.41 to -0.71), but "
            "small, non-reliable effects on rumination (g approximately "
            "-0.13)."
        )
    }
}

print("=" * 60)
print("PILOT RESEARCH EVIDENCE CORRECTION")
print("=" * 60)

update_csv("sources.csv", source_updates, "source_id")
update_csv("claims.csv", claim_updates, "claim_id")
update_csv("evidence.csv", evidence_updates, "evidence_id")

print("\nBACKUPS:", BACKUP)
print("DATABASE MODIFIED: NO")
print("YOUTUBE API CALLS: 0")
print("STATUS: CORRECTIONS SAVED")