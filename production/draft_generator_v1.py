
from pathlib import Path
from datetime import datetime
import csv
import json
import re

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / "production/runs/E1irX9cDX8U"
WORKSPACE = ROOT / "data/research/youtube_universe_v33/research_workspace_v33/E1irX9cDX8U"


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_research():
    report_path = RUN_DIR / "research_consistency_report.json"

    if not report_path.exists():
        raise FileNotFoundError("Research consistency report missing.")

    report = json.loads(report_path.read_text(encoding="utf-8"))

    if report.get("overall_status") != "READY_FOR_CONTROLLED_DRAFT":
        raise RuntimeError("Research gate is not ready for controlled drafting.")

    claims = {
        x["claim_id"]: x
        for x in read_csv(WORKSPACE / "claims.csv")
    }
    sources = {
        x["source_id"]: x
        for x in read_csv(WORKSPACE / "sources.csv")
    }
    evidence = read_csv(WORKSPACE / "evidence.csv")

    eligible = {
        x["claim_id"]
        for x in report["claim_results"]
        if x["status"] == "ELIGIBLE_FOR_DRAFT"
    }

    held = {
        x["claim_id"]
        for x in report["claim_results"]
        if x["status"] == "HOLD"
    }

    if "C03" not in held:
        raise RuntimeError("Expected C03 to remain held. Recheck research audit.")

    for claim_id in eligible:
        if claim_id not in claims:
            raise RuntimeError(f"Claim missing: {claim_id}")

    return report, claims, sources, evidence, eligible, held


def references_for(claim_ids, evidence, sources):
    result = []

    for claim_id in claim_ids:
        for item in evidence:
            if item["claim_id"] != claim_id:
                continue

            source = sources.get(item["source_id"])
            if not source:
                continue

            result.append({
                "claim_id": claim_id,
                "evidence_id": item["evidence_id"],
                "source_id": item["source_id"],
                "title": source["title"],
                "url": source["url_or_doi"],
                "source_type": source["source_type"],
                "review_note": source["notes"],
                "limitation": item["notes"],
            })

    return result


def long_script():
    return [
        ("HOOK", "Kabhi aisa hua hai ki din bhar sab normal tha, lekin jaise hi aap sone ke liye bed par gaye, dimaag mein purani baatein aur kal ki tension chalne lagi? Ek conversation dobara yaad aati hai. Ek decision par doubt hota hai. Aur neend aane ke bajaye thoughts ka loop shuru ho jata hai. Lekin kya iska matlab hai ki har insaan raat ko zyada overthink karta hai? Research isse thoda zyada complicated batati hai.", ["C01", "C02"]),
        ("CONTEXT", "Sabse pehle ek difference samajhna zaroori hai. Normal thinking aur repetitive negative thinking ek hi cheez nahi hain. Normal thinking mein hum kisi problem ko samajhne ya solve karne ki koshish karte hain. Repetitive negative thinking mein wahi concern baar-baar dimaag mein laut sakta hai, bina kisi clear solution ke. Is video mein hum isi pattern aur sleep ke beech ke research evidence ko samjhenge.", ["C01", "C02"]),
        ("STUDY ONE", "Ek study mein researchers ne sleep problems wale participants ko examine kiya. Research mein do studies thi, jinmein 139 aur 64 participants shamil the. Findings mein nighttime sleep-related worry ka sleep impairment ke saath consistent association mila. Lekin trait worry aur trait rumination ka result har jagah same nahi tha. Iska matlab ye nahi ki har insaan raat ko hi zyada overthink karta hai. Evidence specifically sleep problems wale logon se aaya tha.", ["C01"]),
        ("STUDY TWO", "Ek doosri study mein 507 undergraduate students ko examine kiya gaya. Researchers ne dekha ki bedtime repetitive negative thinking, perceived stress aur insomnia severity ke relationship ko moderate karti thi. Participants ke insomnia threshold ke hisaab se pattern bhi alag tha. Lekin ye observational research thi. Isse ye prove nahi hota ki bedtime overthinking hi insomnia ka cause hai, ya har age group mein same pattern hoga.", ["C02"]),
        ("WHY IT MATTERS", "Sleep aur emotions ka connection bhi important hai. Ek systematic review aur meta-analysis ne 154 studies aur 5,717 participants ke data ko examine kiya. Experimental sleep loss ke baad positive emotions mein reduction aur anxiety symptoms mein increase dekha gaya. Negative affect ke results mixed the. Dhyan rahe, ye sleep loss ke emotional effects ka evidence hai. Ye directly prove nahi karta ki sleep loss nighttime overthinking cause karta hai.", ["C04"]),
        ("PRACTICAL CONTEXT", "Agar kisi ko chronic insomnia disorder hai, toh sirf generic advice jaise jaldi so jao ya phone side mein rakh do, hamesha sufficient treatment nahi hoti. American Academy of Sleep Medicine adults with chronic insomnia ke liye multicomponent CBT-I ki strong recommendation deti hai. Sleep hygiene alone ko standalone treatment ke roop mein recommend nahi kiya gaya. Ye general information hai, individual diagnosis ya treatment plan nahi.", ["C05"]),
        ("WHAT TREATMENT EVIDENCE SAYS", "CBT-I par ek systematic review aur meta-analysis mein 15 randomized trials examine kiye gaye. Worry par moderate-to-large effects report hue, jabki rumination par effect small tha aur reliable nahi tha. Isliye CBT-I ko overthinking ka guaranteed cure kehna galat hoga. Worry aur rumination alag patterns ho sakte hain, aur research unke results ko bhi alag dikhati hai.", ["C06"]),
        ("TAKEAWAY", "Toh agli baar jab raat ko thoughts repeat hone lagen, khud ko weak ya unusual label mat kijiye. Pehle notice kijiye ki aap kisi problem ka solution dhoondh rahe hain, ya wahi negative thought bina progress ke repeat ho raha hai. Agar sleep problem persistent hai aur daily life affect kar rahi hai, qualified healthcare professional se baat karna sensible step hai. Research humein ek useful distinction deti hai: nighttime worry aur sleep problems connected ho sakte hain, lekin har case ka reason ek jaisa nahi hota.", ["C01", "C02", "C05", "C06"]),
    ]


def short_script():
    return [
        ("HOOK", "Raat ko bed par jaate hi purani baatein aur kal ki tension yaad aane lagti hai?"),
        ("EVIDENCE", "Sleep problems wale logon par hui do studies mein nighttime sleep-related worry ka sleep impairment se consistent association mila. Ek alag study mein 507 students ke beech bedtime repetitive negative thinking aur stress-insomnia relationship ka connection dekha gaya."),
        ("QUALIFICATION", "Lekin ye prove nahi karta ki har insaan raat ko zyada overthink karta hai, ya overthinking hi insomnia ka cause hai."),
        ("TAKEAWAY", "Agar sleep problem lagataar chal rahi hai, professional help lena better hai. Har repetitive thought ko apni weakness mat samjho."),
    ]


def word_count(text):
    return len(re.findall(r"\b[\w'-]+\b", text))


def main():
    report, claims, sources, evidence, eligible, held = load_research()

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    output = RUN_DIR / "drafts" / timestamp
    output.mkdir(parents=True, exist_ok=False)

    long_sections = long_script()
    short_sections = short_script()

    def render_long():
        lines = [
            "# Long-form documentary script — controlled draft",
            "",
            "Topic: Raat Ko Overthinking Kyun Hoti Hai?",
            "Language: Conversational Roman Hinglish",
            "Status: DRAFT ONLY — NOT PRODUCTION APPROVED",
            "",
        ]

        all_claims = set()

        for heading, narration, claim_ids in long_sections:
            all_claims.update(claim_ids)
            lines.extend([
                f"## {heading}",
                "",
                narration,
                "",
                f"Claim mapping: {', '.join(claim_ids)}",
                "",
            ])

        lines.extend([
            "## Draft notes",
            "",
            "- Narration is a deterministic baseline, not an AI-polished final script.",
            "- Add original examples and visual storytelling only after review.",
            "- Do not turn associations into causal claims.",
            "- Do not use held claim C03.",
            "- The current evidence package may not support a complete eight-minute documentary without further research.",
            "",
        ])

        return "\n".join(lines), sorted(all_claims)

    def render_short():
        lines = [
            "# 45-second Short — controlled draft",
            "",
            "Topic: Raat Ko Overthinking Kyun Hoti Hai?",
            "Status: DRAFT ONLY — NOT PRODUCTION APPROVED",
            "",
        ]

        for heading, narration in short_sections:
            lines.extend([f"## {heading}", "", narration, ""])

        lines.extend([
            "## Claim mapping",
            "",
            "C01, C02, C05",
            "",
        ])

        return "\n".join(lines), ["C01", "C02", "C05"]

    long_text, long_claim_ids = render_long()
    short_text, short_claim_ids = render_short()

    long_path = output / "long_video_script_draft.md"
    short_path = output / "short_video_script_draft.md"

    long_path.write_text(long_text, encoding="utf-8")
    short_path.write_text(short_text, encoding="utf-8")

    used_claim_ids = sorted(set(long_claim_ids + short_claim_ids))
    refs = references_for(used_claim_ids, evidence, sources)

    manifest = {
        "topic_id": "E1irX9cDX8U",
        "created_at": datetime.now().astimezone().isoformat(),
        "generator": "deterministic_template_v1",
        "input_audit_status": report["overall_status"],
        "eligible_claim_ids": sorted(eligible),
        "held_claim_ids": sorted(held),
        "used_claim_ids": used_claim_ids,
        "excluded_claim_ids": sorted(held),
        "long_script": {
            "file": long_path.name,
            "word_count": word_count(long_text),
            "estimated_minutes_at_130_wpm": round(word_count(long_text) / 130, 2),
            "claim_ids": long_claim_ids,
        },
        "short_script": {
            "file": short_path.name,
            "word_count": word_count(short_text),
            "estimated_seconds_at_130_wpm": round(word_count(short_text) / 130 * 60),
            "claim_ids": short_claim_ids,
        },
        "references": refs,
        "safety": {
            "original_research_files_modified": False,
            "historical_human_decisions_modified": False,
            "production_approved": False,
            "render_authorized": False,
            "upload_authorized": False,
        },
    }

    manifest_path = output / "draft_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("CONTROLLED SCRIPT DRAFTS CREATED")
    print("=" * 55)
    print("Output:", output)
    print("Long script words:", manifest["long_script"]["word_count"])
    print("Long estimated minutes:", manifest["long_script"]["estimated_minutes_at_130_wpm"])
    print("Short script words:", manifest["short_script"]["word_count"])
    print("Short estimated seconds:", manifest["short_script"]["estimated_seconds_at_130_wpm"])
    print("Claims used:", ", ".join(used_claim_ids))
    print("Held claims excluded:", ", ".join(sorted(held)))
    print("Production approval: NOT GRANTED")
    print("Upload authorization: NOT GRANTED")


if __name__ == "__main__":
    main()
