
from pathlib import Path
from datetime import datetime
import csv
import json
import re

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / "production/runs/E1irX9cDX8U"
WORKSPACE = ROOT / "data/research/youtube_universe_v33/research_workspace_v33/E1irX9cDX8U"

LONG_SECTIONS = [
    ("HOOK", """Raat ke 11:30 baj rahe hain. Aapne phone side mein rakh diya, light off kar di, aur decide kiya ki ab sona hai. Lekin dimaag abhi bhi active hai. Din mein kisi se hui baat yaad aa rahi hai. Kal ka kaam pending hai. Ek purana decision dobara question ban gaya hai. Aap khud se kehte hain, bas paanch minute sochunga. Lekin wahi thought baar-baar laut aata hai. Kabhi aisa experience hua hai? Is situation ko hum casually overthinking bol dete hain. Lekin psychology aur sleep research is topic ko thoda carefully dekhti hai. Sawal sirf ye nahi ki raat ko thoughts kyun aate hain; sawal ye hai ki repetitive worry aur sleep problems ke beech evidence asal mein kya kehta hai.""", ["C01", "C02"]),

    ("CONTEXT", """Sabse pehle do cheezon ko alag samajhna zaroori hai. Sochna apne aap mein problem nahi hai. Agar aap kal ki meeting ke liye points arrange kar rahe hain, ya kisi issue ka practical solution plan kar rahe hain, toh thinking useful ho sakti hai. Repetitive negative thinking kuch alag pattern hai: ek hi concern baar-baar mind mein aata hai, lekin har repetition ke saath zaroori nahi ki koi naya solution mile. Worry aksar future ke possible problems se judi hoti hai; rumination mein kisi past event ya feeling par baar-baar sochna shamil ho sakta hai. Dono terms related hain, lekin identical nahi. Isliye research mein worry, rumination aur general repetitive thinking ko ek hi label mein mix karna misleading ho sakta hai. Is video mein hum wahi distinction maintain karenge.""", ["C01", "C02", "C06"]),

    ("STUDY ONE", """Ek primary study ne sleep problems wale logon mein repetitive thinking aur sleep impairment ka relation examine kiya. Is research mein do studies thi: pehli mein 139 participants aur doosri mein 64 participants the. Researchers ne report kiya ki nighttime sleep-related worry ka sleep impairment ke saath consistent association mila. Lekin ek important detail bhi thi: Study 1 mein trait rumination aur trait worry sleep impairment se associated nahi the. Is finding ka matlab ye nahi ki har insaan raat ko din ke comparison mein zyada overthink karta hai. Study ka focus sleep problems wale participants par tha, aur result association dikhata hai, universal rule nahi. Yaani specific context mein bedtime worry relevant ho sakti hai, lekin isse sab logon ke liye ek fixed explanation nahi banaya ja sakta.""", ["C01"]),

    ("STUDY TWO", """Ek doosri study mein 507 undergraduate students ko include kiya gaya. Researchers ne bedtime repetitive negative thinking, perceived stress aur insomnia severity ke relationship ko examine kiya. Study ke mutabik bedtime repetitive negative thinking ne perceived stress aur insomnia severity ke association ko moderate kiya. Participants insomnia threshold ke upar the ya neeche, iske hisaab se pattern alag tha. Yahan sample ko yaad rakhna zaroori hai: ye undergraduate students the, har age aur background ke log nahi. Ye study stress, bedtime repetitive thinking aur insomnia ke beech relationship examine karti hai. Is tarah ka association apne aap cause prove nahi karta. Ho sakta hai stress, sleep difficulty aur repetitive thinking ek doosre se related hon; study ka result unke relationship ko describe karta hai, simple one-way cause ko prove nahi karta.""", ["C02"]),

    ("ILLUSTRATIVE EXAMPLE", """Ek hypothetical example lete hain. Maan lijiye, Riya ko office mein manager ne ek short message bheja: “Kal baat karte hain.” Riya ko exact context nahi pata. Raat ko woh possibilities sochne lagti hai: kya kaam mein mistake hui, kya presentation weak thi, ya koi urgent issue hai? Ye example kisi study ka participant ya documented case nahi hai. Iska purpose sirf repetitive thinking ka pattern samjhana hai. Ek useful question ho sakta hai: “Kya main abhi koi actionable step le sakta hoon, ya bas same possibilities repeat kar raha hoon?” Agar action possible hai, toh use note karke kal ke liye plan banaya ja sakta hai. Agar abhi koi action possible nahi, toh baar-baar mental rehearsal karna zaroori nahi ki answer de. Ye ek reflection prompt hai, treatment ya guaranteed technique nahi.""", ["C01", "C02"]),

    ("SLEEP AND EMOTION", """Sleep aur emotion ke connection par ek alag systematic review aur meta-analysis ne 154 studies, 1,338 effect sizes aur 5,717 participants ka evidence examine kiya. Researchers ne experimental sleep loss ke baad positive affect mein reduction aur anxiety symptoms mein increase report kiya. Negative affect ke results mixed the. Is finding ko sahi boundary mein samajhna important hai. Ye research sleep loss ke emotional effects ko examine karti hai; ye prove nahi karti ki sleep loss directly nighttime overthinking cause karta hai. Dono topics related ho sakte hain, lekin ek study ke result ko doosre question ka direct answer nahi banana chahiye. Research ko responsibly explain karne ka matlab hai ki hum wahi claim karein jo study ne actually test kiya, usse aage extrapolate na karein.""", ["C04"]),

    ("TREATMENT EVIDENCE", """Agar kisi adult ko chronic insomnia disorder hai, toh treatment ke liye professional guidance important hai. American Academy of Sleep Medicine multicomponent cognitive behavioral therapy for insomnia, ya CBT-I, ki strong recommendation deti hai. Guideline sleep hygiene ko akela standalone treatment banane ke against conditional recommendation bhi deti hai. Iska matlab basic sleep habits useless hain, aisa nahi; point ye hai ki chronic insomnia ke treatment ko sirf generic sleep tips tak limit nahi karna chahiye. CBT-I ek structured treatment approach hai, aur individual suitability qualified clinician ke saath discuss honi chahiye. Ye video diagnosis nahi karta aur kisi viewer ko personal treatment prescribe nahi kar raha. Agar sleep difficulty persistent hai, daily functioning affect kar rahi hai, ya distress badh raha hai, toh healthcare professional se baat karna sensible step hai.""", ["C05"]),

    ("WHAT CBT-I EVIDENCE SAYS", """CBT-I par ek systematic review aur meta-analysis ne 15 randomized controlled trials ko examine kiya. Review mein worry ke liye moderate-to-large effects report hue, jinke Hedges g estimates approximately minus 0.41 se minus 0.71 ke beech the. Rumination ke liye effect chhota tha, approximately minus 0.13, aur reliable nahi maana gaya. Is difference ko ignore nahi karna chahiye. Worry par result dekhkar ye kehna galat hoga ki CBT-I har tarah ki repetitive thinking ko eliminate kar deti hai. Worry aur rumination ke results same strength ke nahi hain. Research ka honest summary ye hai ki CBT-I chronic insomnia ke liye recommended treatment hai, aur available review worry mein benefit suggest karta hai; rumination ke result par certainty kam hai.""", ["C05", "C06"]),

    ("TAKEAWAY", """Toh jab raat ko thoughts repeat hon, pehla step khud ko judge karna nahi, pattern ko notice karna ho sakta hai. Kya aap kisi specific problem ka next action identify kar rahe hain? Ya bina naye information ke wahi negative possibilities repeat ho rahi hain? Agar koi practical step hai, use short note mein likh sakte hain aur suitable time par address kar sakte hain. Agar problem persistent hai, sleep ko regularly disturb kar rahi hai, ya din ke kaam par effect daal rahi hai, toh professional help consider karein. Har late-night thought ko disorder samajhna bhi sahi nahi, aur chronic sleep difficulty ko sirf willpower ki kami kehna bhi sahi nahi. Research ek nuanced picture deti hai: sleep-related worry kuch sleep-problem groups mein impairment se associated ho sakti hai, lekin har insaan aur har situation ka reason same nahi hota.""", ["C01", "C02", "C05"]),
]

SHORT_SECTIONS = [
    ("HOOK", "Raat ko bed par jaate hi purani baatein aur kal ki tension yaad aane lagti hai?"),
    ("EVIDENCE", "Sleep problems wale logon par hui do studies mein nighttime sleep-related worry ka sleep impairment se consistent association mila. Ek alag study mein 507 students ke beech bedtime repetitive negative thinking aur stress-insomnia relationship ka connection dekha gaya."),
    ("QUALIFICATION", "Lekin ye prove nahi karta ki har insaan raat ko zyada overthink karta hai, ya overthinking hi insomnia ka cause hai."),
    ("TAKEAWAY", "Agar sleep problem lagataar chal rahi hai, professional help lena better hai. Har repetitive thought ko apni weakness mat samjho."),
]

def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def word_count(text):
    return len(re.findall(r"\b[\w'-]+\b", text))

def main():
    audit_path = RUN_DIR / "research_consistency_report.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    if audit.get("overall_status") != "READY_FOR_CONTROLLED_DRAFT":
        raise RuntimeError("Research gate is not ready.")

    eligible = {
        x["claim_id"] for x in audit["claim_results"]
        if x["status"] == "ELIGIBLE_FOR_DRAFT"
    }
    held = {
        x["claim_id"] for x in audit["claim_results"]
        if x["status"] == "HOLD"
    }

    if "C03" not in held:
        raise RuntimeError("C03 hold status changed. Recheck research before drafting.")

    claims = {x["claim_id"]: x for x in read_csv(WORKSPACE / "claims.csv")}
    sources = {x["source_id"]: x for x in read_csv(WORKSPACE / "sources.csv")}
    evidence = read_csv(WORKSPACE / "evidence.csv")

    used = set()
    long_lines = [
        "# Long-form documentary script — controlled draft v2",
        "",
        "Topic: Raat Ko Overthinking Kyun Hoti Hai?",
        "Language: Conversational Roman Hinglish",
        "Status: DRAFT ONLY — NOT PRODUCTION APPROVED",
        "",
    ]

    for heading, narration, claim_ids in LONG_SECTIONS:
        if not set(claim_ids).issubset(eligible):
            raise RuntimeError(f"Ineligible claim used in section: {heading}")
        used.update(claim_ids)
        long_lines += [
            f"## {heading}", "", narration, "",
            f"Claim mapping: {', '.join(claim_ids)}", "",
        ]

    long_lines += [
        "## Draft notes", "",
        "- The Riya scenario is hypothetical, not a reported study case.",
        "- Study findings retain their stated populations and limitations.",
        "- Association is not described as causation.",
        "- C03 is excluded from factual narration.",
        "- This draft is not a substitute for independent fact review.",
        "",
    ]

    short_used = {"C01", "C02"}
    short_lines = [
        "# Short-form script — controlled draft v2", "",
        "Topic: Raat Ko Overthinking Kyun Hoti Hai?",
        "Status: DRAFT ONLY — NOT PRODUCTION APPROVED", "",
    ]

    for heading, narration in SHORT_SECTIONS:
        short_lines += [f"## {heading}", "", narration, ""]

    short_lines += [
        "Claim mapping: C01, C02", "",
        "## Draft notes", "",
        "- Short narration uses the same research limitations.",
        "- Not production approved.", "",
    ]

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    out = RUN_DIR / "drafts" / timestamp
    out.mkdir(parents=True, exist_ok=False)

    long_text = "\n".join(long_lines)
    short_text = "\n".join(short_lines)

    (out / "long_video_script_draft.md").write_text(long_text, encoding="utf-8")
    (out / "short_video_script_draft.md").write_text(short_text, encoding="utf-8")

    used_all = sorted(used | short_used)
    refs = []

    for claim_id in used_all:
        for ev in evidence:
            if ev["claim_id"] != claim_id:
                continue
            src = sources.get(ev["source_id"])
            if src:
                refs.append({
                    "claim_id": claim_id,
                    "evidence_id": ev["evidence_id"],
                    "source_id": ev["source_id"],
                    "title": src["title"],
                    "url": src["url_or_doi"],
                    "source_review_note": src["notes"],
                    "evidence_note": ev["notes"],
                })

    manifest = {
        "topic_id": "E1irX9cDX8U",
        "created_at": datetime.now().astimezone().isoformat(),
        "generator": "controlled_editorial_template_v2",
        "research_audit_status": audit["overall_status"],
        "eligible_claim_ids": sorted(eligible),
        "held_claim_ids": sorted(held),
        "long_script": {
            "file": "long_video_script_draft.md",
            "narration_words": word_count("\n".join(x[1] for x in LONG_SECTIONS)),
            "claim_ids": sorted(used),
        },
        "short_script": {
            "file": "short_video_script_draft.md",
            "narration_words": word_count("\n".join(x[1] for x in SHORT_SECTIONS)),
            "claim_ids": sorted(short_used),
        },
        "references": refs,
        "safety": {
            "production_approved": False,
            "render_authorized": False,
            "upload_authorized": False,
        },
    }

    (out / "draft_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("CONTROLLED SCRIPT DRAFTS V2 CREATED")
    print("=" * 55)
    print("Output:", out)
    print("Long narration words:", manifest["long_script"]["narration_words"])
    print("Long estimated minutes:", round(manifest["long_script"]["narration_words"] / 130, 2))
    print("Short narration words:", manifest["short_script"]["narration_words"])
    print("Short estimated seconds:", round(manifest["short_script"]["narration_words"] / 130 * 60))
    print("Long claims:", ", ".join(manifest["long_script"]["claim_ids"]))
    print("Short claims:", ", ".join(manifest["short_script"]["claim_ids"]))
    print("Held claims excluded:", ", ".join(sorted(held)))
    print("Production approval: NOT GRANTED")
    print("Upload authorization: NOT GRANTED")

if __name__ == "__main__":
    main()
