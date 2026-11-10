
from pathlib import Path
from datetime import datetime
import json
import re

ROOT = Path(__file__).resolve().parent.parent
RUN_DIR = ROOT / "production/runs/E1irX9cDX8U"


def latest_draft():
    folders = [
        p for p in (RUN_DIR / "drafts").iterdir()
        if p.is_dir()
        and (p / "draft_manifest.json").exists()
        and (p / "fact_review_report.json").exists()
    ]
    if not folders:
        raise RuntimeError("No draft with a fact-review packet found.")
    return max(folders, key=lambda p: p.name)


def parse_sections(text):
    sections = []
    current = None
    narration = []

    def save():
        if current and narration:
            body = " ".join(narration).strip()
            if body:
                sections.append({
                    "heading": current,
                    "narration": body,
                    "claim_ids": current_claims[:],
                })

    current_claims = []

    for line in text.splitlines():
        if line.startswith("## "):
            save()
            current = line[3:].strip()
            narration = []
            current_claims = []
            continue

        if current is None or current.lower() == "draft notes":
            continue

        match = re.match(r"\s*Claim mapping:\s*(.*)", line, re.I)
        if match:
            current_claims = re.findall(r"\bC\d{2}\b", match.group(1).upper())
            continue

        if line.strip():
            narration.append(line.strip())

    save()
    return sections


def split_sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def chunk_sentences(text, max_groups=3):
    sentences = split_sentences(text)
    if not sentences:
        return [text]

    groups = [[] for _ in range(min(max_groups, len(sentences)))]
    for index, sentence in enumerate(sentences):
        groups[index % len(groups)].append(sentence)

    return [" ".join(group) for group in groups if group]


def visual_direction(heading, narration):
    h = heading.lower()

    if h == "hook":
        return (
            "Cinematic bedroom at night, person awake in bed, subtle city "
            "light through window, close-up of clock and thoughtful expression. "
            "Realistic, restrained, no exaggerated distress."
        )
    if h == "context":
        return (
            "Minimal cinematic split-screen: practical planning notes on one "
            "side and a repeating thought loop represented by subtle graphic "
            "lines on the other. No readable fake study data."
        )
    if h in {"study one", "study two"}:
        return (
            "Research-documentary visual: quiet study desk, anonymized paper "
            "notes, neutral data visualization and sample-size typography only "
            "where explicitly stated in narration. Do not invent charts."
        )
    if h == "illustrative example":
        return (
            "Clearly illustrative office scenario: a person sees a short "
            "work message on a phone, then pauses thoughtfully at home. "
            "Avoid showing a real company or identifiable person."
        )
    if h == "sleep and emotion":
        return (
            "Abstract sleep and emotion visualization: night-to-morning "
            "transition, restrained color and simple animated mood indicators. "
            "No unsupported medical graphics."
        )
    if h in {"treatment evidence", "what cbt-i evidence says"}:
        return (
            "Calm clinical documentary aesthetic: consultation room, notebook, "
            "structured routine cards and evidence summary graphics. Do not "
            "depict guaranteed recovery or a cure."
        )
    if h in {"takeaway", "practical takeaway"}:
        return (
            "Quiet morning scene, person writing a short practical note, "
            "closing notebook and preparing for the day. Calm, hopeful, realistic."
        )

    return (
        "Premium documentary b-roll relevant to the narration, with subtle "
        "motion graphics. Avoid unsupported statistics, medical symbols "
        "or fabricated research imagery."
    )


def overlay_for(heading):
    labels = {
        "HOOK": "Why does the mind stay awake?",
        "CONTEXT": "Thinking vs. repetitive thinking",
        "STUDY ONE": "Nighttime sleep-related worry",
        "STUDY TWO": "507 undergraduate students",
        "ILLUSTRATIVE EXAMPLE": "A hypothetical example",
        "SLEEP AND EMOTION": "Sleep loss and emotional effects",
        "TREATMENT EVIDENCE": "CBT-I: clinical guideline",
        "WHAT CBT-I EVIDENCE SAYS": "Worry and rumination: different results",
        "TAKEAWAY": "Notice the pattern. Don't self-blame.",
        "PRACTICAL TAKEAWAY": "Notice the pattern. Don't self-blame.",
    }
    return labels.get(heading.upper(), "")


def main():
    draft_dir = latest_draft()

    manifest = json.loads(
        (draft_dir / "draft_manifest.json").read_text(encoding="utf-8")
    )
    fact_report = json.loads(
        (draft_dir / "fact_review_report.json").read_text(encoding="utf-8")
    )

    if fact_report.get("review_status") != "PENDING_HUMAN_REVIEW":
        raise RuntimeError("Unexpected fact-review state. Inspect report first.")

    held = set(manifest.get("held_claim_ids", []))
    eligible = set(manifest.get("eligible_claim_ids", []))

    long_text = (draft_dir / "long_video_script_draft.md").read_text(
        encoding="utf-8"
    )
    short_text = (draft_dir / "short_video_script_draft.md").read_text(
        encoding="utf-8"
    )

    long_sections = parse_sections(long_text)
    short_sections = parse_sections(short_text)

    scenes = []
    scene_number = 1

    for section in long_sections:
        claim_ids = set(section["claim_ids"])

        if claim_ids & held:
            raise RuntimeError(
                f"Held claim found in section {section['heading']}: "
                f"{sorted(claim_ids & held)}"
            )

        if not claim_ids.issubset(eligible):
            raise RuntimeError(
                f"Unknown or ineligible claim in {section['heading']}"
            )

        beats = chunk_sentences(section["narration"], 3)
        total_words = len(re.findall(r"\b[\w'-]+\b", section["narration"]))

        beat_word_counts = [
            len(re.findall(r"\b[\w'-]+\b", beat)) for beat in beats
        ]
        total_beat_words = max(1, sum(beat_word_counts))

        for beat_index, beat in enumerate(beats):
            words = beat_word_counts[beat_index]
            duration = round((words / total_beat_words) * (total_words / 130 * 60), 1)

            scenes.append({
                "scene_id": f"L{scene_number:02d}",
                "section": section["heading"],
                "beat": beat_index + 1,
                "estimated_duration_seconds": duration,
                "narration_excerpt": beat,
                "visual_direction": visual_direction(
                    section["heading"], beat
                ),
                "on_screen_text": (
                    overlay_for(section["heading"])
                    if beat_index == 0 else ""
                ),
                "claim_ids": sorted(claim_ids),
                "fact_review_status": "PENDING",
                "asset_status": "NOT_CREATED",
            })
            scene_number += 1

    titles = [
        {
            "title": "Raat Ko Overthinking Kyun Hoti Hai?",
            "angle": "Direct question; clear topic match",
            "risk": "Low",
        },
        {
            "title": "Raat Mein Dimaag Itna Active Kyun Ho Jaata Hai?",
            "angle": "Relatable curiosity",
            "risk": "Low",
        },
        {
            "title": "Bedtime Overthinking: Research Kya Kehti Hai?",
            "angle": "Evidence-led documentary positioning",
            "risk": "Low",
        },
    ]

    thumbnails = [
        {
            "concept": "Awake at 11:30 PM",
            "composition": (
                "One person awake in bed on the right; dark quiet bedroom; "
                "clock showing 11:30; subtle thought-loop graphic on left."
            ),
            "text": "RAAT KO KYUN?",
            "image_prompt": (
                "Premium realistic documentary YouTube thumbnail, 16:9. "
                "A single person awake in bed at night, cinematic low-key "
                "lighting, subtle city light, a simple abstract thought-loop "
                "graphic, strong readable composition, empty space on left "
                "for Hindi text, no logos, no fake medical symbols, no extra "
                "text, natural human proportions."
            ),
            "risk": "Do not imply a medical diagnosis.",
        },
        {
            "concept": "Mind vs. Sleep",
            "composition": (
                "Split composition: peaceful sleeping environment on one side, "
                "awake thoughtful face on the other; restrained contrast."
            ),
            "text": "DIMAAG BAND KYUN NAHI?",
            "image_prompt": (
                "Premium cinematic documentary thumbnail, 16:9 split "
                "composition contrasting a quiet bedroom and a thoughtful "
                "awake adult, realistic photography style, restrained "
                "dark-blue night atmosphere, clear negative space for "
                "headline, no text rendered inside image, no logos."
            ),
            "risk": "Avoid portraying the brain as literally damaged or abnormal.",
        },
        {
            "concept": "Repeating Thought Loop",
            "composition": (
                "Close-up thoughtful face with a subtle circular line motif; "
                "minimal background and high contrast."
            ),
            "text": "EK HI SOCH, BAAR-BAAR",
            "image_prompt": (
                "High-end editorial documentary thumbnail, 16:9, close-up "
                "of a thoughtful adult at night, subtle abstract circular "
                "line motif suggesting repetitive thoughts, realistic skin "
                "and lighting, uncluttered composition, space for large "
                "headline, no text, no logos."
            ),
            "risk": "Keep the thought-loop graphic abstract, not a medical scan.",
        },
    ]

    short_scenes = []
    short_number = 1

    for section in short_sections:
        for beat in chunk_sentences(section["narration"], 2):
            short_scenes.append({
                "scene_id": f"S{short_number:02d}",
                "section": section["heading"],
                "narration_excerpt": beat,
                "visual_direction": visual_direction(
                    section["heading"], beat
                ),
                "claim_ids": (
                    ["C01", "C02"]
                    if section["heading"].upper() in {"EVIDENCE", "QUALIFICATION"}
                    else []
                ),
                "fact_review_status": "PENDING",
                "asset_status": "NOT_CREATED",
            })
            short_number += 1

    package = {
        "package_version": "1.0",
        "created_at": datetime.now().astimezone().isoformat(),
        "topic_id": "E1irX9cDX8U",
        "draft_folder": str(draft_dir),
        "research_gate": manifest.get("research_audit_status"),
        "fact_review_status": "PENDING_HUMAN_REVIEW",
        "long_video": {
            "titles": titles,
            "thumbnail_concepts": thumbnails,
            "scene_count": len(scenes),
            "scenes": scenes,
        },
        "short_video": {
            "scene_count": len(short_scenes),
            "scenes": short_scenes,
        },
        "approval": {
            "title_approved": False,
            "thumbnail_approved": False,
            "visual_plan_approved": False,
            "assets_created": False,
            "production_approved": False,
            "render_authorized": False,
            "upload_authorized": False,
        },
        "notes": [
            "Titles and thumbnail text are proposals, not performance predictions.",
            "Scene directions are production briefs, not generated assets.",
            "All research-related scenes remain subject to fact review.",
            "No unsupported statistics or held claims may be added.",
        ],
    }

    json_path = draft_dir / "creative_package.json"
    md_path = draft_dir / "creative_package.md"

    json_path.write_text(
        json.dumps(package, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    lines = [
        "# Creative Package",
        "",
        f"- Topic: {package['topic_id']}",
        f"- Draft: {draft_dir.name}",
        "- Fact review: PENDING",
        "- Production approval: NOT GRANTED",
        "- Upload authorization: NOT GRANTED",
        "",
        "## Title options",
        "",
    ]

    for index, item in enumerate(titles, 1):
        lines += [
            f"{index}. **{item['title']}**",
            f"   - Angle: {item['angle']}",
            f"   - Risk: {item['risk']}",
            "",
        ]

    lines += ["## Thumbnail concepts", ""]

    for index, item in enumerate(thumbnails, 1):
        lines += [
            f"### {index}. {item['concept']}",
            f"- Text: **{item['text']}**",
            f"- Composition: {item['composition']}",
            f"- Image prompt: {item['image_prompt']}",
            f"- Risk: {item['risk']}",
            "",
        ]

    lines += ["## Long-video scene plan", ""]

    for scene in scenes:
        lines += [
            f"### {scene['scene_id']} — {scene['section']}",
            f"- Estimated duration: {scene['estimated_duration_seconds']} sec",
            f"- Narration: {scene['narration_excerpt']}",
            f"- Visual: {scene['visual_direction']}",
            f"- On-screen text: {scene['on_screen_text'] or 'None'}",
            f"- Claim IDs: {', '.join(scene['claim_ids']) or 'None'}",
            "- Fact review: PENDING",
            "",
        ]

    lines += ["## Short-video scene plan", ""]

    for scene in short_scenes:
        lines += [
            f"### {scene['scene_id']} — {scene['section']}",
            f"- Narration: {scene['narration_excerpt']}",
            f"- Visual: {scene['visual_direction']}",
            f"- Claim IDs: {', '.join(scene['claim_ids']) or 'None'}",
            "",
        ]

    md_path.write_text("\n".join(lines), encoding="utf-8")

    print("CREATIVE PACKAGE CREATED")
    print("=" * 55)
    print("Draft:", draft_dir)
    print("Long scenes:", len(scenes))
    print("Short scenes:", len(short_scenes))
    print("Title options:", len(titles))
    print("Thumbnail concepts:", len(thumbnails))
    print("JSON:", json_path)
    print("Markdown:", md_path)
    print("Fact review: PENDING")
    print("Production approval: NOT GRANTED")
    print("Upload authorization: NOT GRANTED")


if __name__ == "__main__":
    main()
