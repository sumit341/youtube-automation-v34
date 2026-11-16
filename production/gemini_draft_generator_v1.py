from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
TOPIC_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

LONG_REQUIRED = {"HOOK", "CONTEXT", "TAKEAWAY"}
SHORT_REQUIRED = {"HOOK", "EVIDENCE", "QUALIFICATION", "TAKEAWAY"}


def validate_topic_id(topic_id):
    if not isinstance(topic_id, str) or not TOPIC_RE.fullmatch(topic_id):
        raise ValueError("Invalid topic ID.")
    return topic_id


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def locate_workspace(topic_id):
    for claims_path in (ROOT / "data" / "research").rglob("claims.csv"):
        if claims_path.parent.name == topic_id:
            folder = claims_path.parent
            if all((folder / name).is_file() for name in
                   ("claims.csv", "sources.csv", "evidence.csv")):
                return folder
    raise FileNotFoundError(f"Complete research workspace missing for {topic_id}")


def collect_research(topic_id):
    run_dir = ROOT / "production" / "runs" / topic_id
    audit_path = run_dir / "research_consistency_report.json"
    if not audit_path.is_file():
        raise FileNotFoundError(f"Research audit missing: {audit_path}")

    audit = read_json(audit_path)
    if audit.get("topic_id") != topic_id:
        raise RuntimeError("Research audit topic ID mismatch.")
    if audit.get("overall_status") != "READY_FOR_CONTROLLED_DRAFT":
        raise RuntimeError("Research gate is not READY_FOR_CONTROLLED_DRAFT.")

    workspace = locate_workspace(topic_id)
    claims = {x["claim_id"]: x for x in read_csv(workspace / "claims.csv")}
    sources = {x["source_id"]: x for x in read_csv(workspace / "sources.csv")}
    evidence = read_csv(workspace / "evidence.csv")

    eligible = []
    held = []
    references = []

    for result in audit.get("claim_results", []):
        cid = result.get("claim_id")
        if not cid:
            continue
        if result.get("status") == "HOLD":
            held.append(cid)
            continue
        if result.get("status") != "ELIGIBLE_FOR_DRAFT":
            continue
        if cid not in claims:
            raise RuntimeError(f"Eligible claim {cid} missing from claims.csv.")

        linked = []
        evidence_ids = set(result.get("evidence_ids", []))
        for ev in evidence:
            if ev.get("claim_id") != cid or ev.get("evidence_id") not in evidence_ids:
                continue
            src = sources.get(ev.get("source_id"), {})
            if (
                ev.get("evidence_relation", "").upper() == "SUPPORTS"
                and ev.get("review_status", "").upper() == "REVIEWED"
                and src.get("source_review_status", "").upper() == "REVIEWED"
                and ev.get("evidence_summary", "").strip()
                and src.get("title", "").strip()
                and src.get("url_or_doi", "").strip()
            ):
                item = {
                    "evidence_id": ev["evidence_id"],
                    "summary": ev["evidence_summary"],
                    "evidence_notes": ev.get("notes", ""),
                    "source_id": ev["source_id"],
                    "source_title": src["title"],
                    "source_type": src.get("source_type", ""),
                    "source_url": src["url_or_doi"],
                    "source_notes": src.get("notes", ""),
                }
                linked.append(item)
                references.append({"claim_id": cid, **item})

        if not linked:
            raise RuntimeError(f"Eligible claim {cid} has no reviewed supporting evidence.")

        eligible.append({
            "claim_id": cid,
            "claim_text": claims[cid].get("claim_text", ""),
            "claim_type": claims[cid].get("claim_type", ""),
            "limitations": claims[cid].get("limitations", ""),
            "importance": claims[cid].get("importance", ""),
            "evidence": linked,
        })

    if not eligible:
        raise RuntimeError("No eligible, evidence-backed claims found.")

    return audit, eligible, sorted(set(held)), references


def call_gemini(topic_id, eligible, held):
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY missing.")

    prompt = f"""
You are a careful US-audience documentary scriptwriter.
Write in natural, clear American English for US viewers interested in
human psychology, money, power and self-improvement.

TOPIC ID: {topic_id}

RESEARCH CLAIMS (the only factual basis you may use):
{json.dumps(eligible, ensure_ascii=False)}

HELD CLAIM IDS — NEVER USE:
{json.dumps(held)}

Return ONLY valid JSON with this exact structure:
{{
  "long_video": {{
    "title": "specific documentary title",
    "sections": [
      {{"heading":"HOOK","narration":"...","claim_ids":["C01"],"visual_direction":"..."}},
      {{"heading":"CONTEXT","narration":"...","claim_ids":["C01"],"visual_direction":"..."}},
      {{"heading":"...","narration":"...","claim_ids":["C01"],"visual_direction":"..."}},
      {{"heading":"TAKEAWAY","narration":"...","claim_ids":["C01"],"visual_direction":"..."}}
    ]
  }},
  "short_video": {{
    "title": "...",
    "sections": [
      {{"heading":"HOOK","narration":"...","claim_ids":["C01"],"visual_direction":"..."}},
      {{"heading":"EVIDENCE","narration":"...","claim_ids":["C01"],"visual_direction":"..."}},
      {{"heading":"QUALIFICATION","narration":"...","claim_ids":["C01"],"visual_direction":"..."}},
      {{"heading":"TAKEAWAY","narration":"...","claim_ids":["C01"],"visual_direction":"..."}}
    ]
  }},
  "thumbnail_concepts": [
    {{"concept":"...","composition":"..."}},
    {{"concept":"...","composition":"..."}}
  ],
  "title_ideas": ["...", "...", "..."]
}}

Rules:
- Every section must map only claims that directly support its factual statements.
- Every claim ID must be from the eligible claims list. Never use held claims.
- Do not invent statistics, study details, quotations, people, events, or sources.
- Keep each claim's population, limitations and uncertainty intact.
- Association is not causation. Do not turn observational findings into causal claims.
- Clearly distinguish hypothetical examples from real research.
- Long-form length is determined by completeness and natural pacing.
  There is NO fixed 8-minute or fixed word-count requirement.
- Short-form script must be concise, understandable and self-contained.
- Long sections must include HOOK, CONTEXT and TAKEAWAY.
- Short sections must include HOOK, EVIDENCE, QUALIFICATION and TAKEAWAY.
- Use distinct, specific visual directions for each scene.
- Avoid generic filler, repetition, sensational medical claims and fake certainty.
- Do not include markdown fences or commentary outside the JSON.
"""

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.45,
            "responseMimeType": "application/json",
            "maxOutputTokens": 8192,
        },
    }

    last_error = None
    for attempt in range(2):
        try:
            response = requests.post(
                API_URL,
                params={"key": key},
                json=body,
                timeout=(15, 120),
            )
            if response.status_code in (429, 400, 401, 403, 404):
                raise RuntimeError(
                    f"GEMINI_API_ERROR_{response.status_code}: "
                    f"{response.text[:700]}"
                )
            if response.status_code in (500, 502, 503, 504):
                last_error = f"GEMINI_TRANSIENT_{response.status_code}"
                if attempt == 0:
                    time.sleep(3)
                    continue
                raise RuntimeError(last_error)

            response.raise_for_status()
            payload = response.json()
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
            result = json.loads(text)
            return result

        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt == 0:
                time.sleep(3)
                continue
            raise RuntimeError("Gemini connection failed: " + last_error) from exc

    raise RuntimeError("Gemini generation failed: " + str(last_error))


def validate_output(data, eligible, held):
    if not isinstance(data, dict):
        raise ValueError("Gemini output is not a JSON object.")

    allowed = {x["claim_id"] for x in eligible}
    held = set(held)

    for key, required in (
        ("long_video", LONG_REQUIRED),
        ("short_video", SHORT_REQUIRED),
    ):
        obj = data.get(key) or {}
        sections = obj.get("sections")
        if not isinstance(sections, list) or not sections:
            raise ValueError(f"{key} sections missing.")

        headings = set()
        for section in sections:
            heading = str(section.get("heading", "")).strip().upper()
            narration = str(section.get("narration", "")).strip()
            ids = set(section.get("claim_ids") or [])
            if not heading or not narration or not ids:
                raise ValueError(f"Invalid {key} section: {heading}")
            if not ids.issubset(allowed):
                raise ValueError(f"Ineligible claim mapping in {key}/{heading}: {ids-allowed}")
            if ids & held:
                raise ValueError(f"Held claim used in {key}/{heading}.")
            section["heading"] = heading
            headings.add(heading)

        missing = required - headings
        if missing:
            raise ValueError(f"{key} missing required sections: {sorted(missing)}")

    thumbs = data.get("thumbnail_concepts")
    if not isinstance(thumbs, list) or len(thumbs) < 2:
        raise ValueError("At least two thumbnail concepts are required.")

    for title in data.get("title_ideas", []):
        if not isinstance(title, str) or not title.strip():
            raise ValueError("Invalid title idea.")

    return data


def word_count(text):
    return len(re.findall(r"\b[\w'-]+\b", text))


def build_draft(topic_id, audit, eligible, held, references, data):
    run_dir = ROOT / "production" / "runs" / topic_id
    stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
    out = run_dir / "drafts" / stamp
    out.mkdir(parents=True, exist_ok=False)

    long_obj = data["long_video"]
    short_obj = data["short_video"]

    long_lines = [
        "# Long-form documentary script",
        "",
        f"Topic: {long_obj.get('title', topic_id)}",
        "Language: American English",
        "Status: DRAFT ONLY — NOT PRODUCTION APPROVED",
        "",
    ]
    short_lines = [
        "# Short-form documentary script",
        "",
        f"Topic: {short_obj.get('title', topic_id)}",
        "Language: American English",
        "Status: DRAFT ONLY — NOT PRODUCTION APPROVED",
        "",
    ]

    long_scenes, short_scenes = [], []
    long_claims, short_claims = set(), set()

    for index, section in enumerate(long_obj["sections"], 1):
        heading = section["heading"]
        narration = section["narration"].strip()
        ids = sorted(set(section["claim_ids"]))
        long_claims.update(ids)
        long_lines.extend([
            f"## {heading}", "", narration, "",
            "Claim mapping: " + ", ".join(ids), "",
        ])
        long_scenes.append({
            "scene_id": f"L{index:02d}",
            "section": heading,
            "claim_ids": ids,
            "visual_direction": section.get("visual_direction", ""),
            "narration_excerpt": narration[:650],
        })

    for index, section in enumerate(short_obj["sections"], 1):
        heading = section["heading"]
        narration = section["narration"].strip()
        ids = sorted(set(section["claim_ids"]))
        short_claims.update(ids)
        short_lines.extend([
            f"## {heading}", "", narration, "",
            "Claim mapping: " + ", ".join(ids), "",
        ])
        short_scenes.append({
            "scene_id": f"S{index:02d}",
            "section": heading,
            "claim_ids": ids,
            "visual_direction": section.get("visual_direction", ""),
            "narration_excerpt": narration[:500],
        })

    long_lines.extend([
        "## Draft notes", "",
        "- Generated from the topic's reviewed research workspace.",
        "- Claim mappings are explicit and held claims are excluded.",
        "- This is an automated draft, not a scientific guarantee.",
        "- Human review is not represented as completed.",
        "",
    ])
    short_lines.extend([
        "## Draft notes", "",
        "- Generated from the same reviewed research evidence.",
        "- Held claims are excluded; factual claims retain qualifications.",
        "- This is an automated draft, not a scientific guarantee.",
        "",
    ])

    long_text = "\n".join(long_lines)
    short_text = "\n".join(short_lines)
    (out / "long_video_script_draft.md").write_text(long_text, encoding="utf-8")
    (out / "short_video_script_draft.md").write_text(short_text, encoding="utf-8")

    creative = {
        "topic_id": topic_id,
        "generator": "gemini_draft_generator_v1",
        "long_video": {
            "title": long_obj.get("title", ""),
            "scenes": long_scenes,
            "thumbnail_concepts": data["thumbnail_concepts"],
        },
        "short_video": {
            "title": short_obj.get("title", ""),
            "scenes": short_scenes,
        },
    }
    (out / "creative_package.json").write_text(
        json.dumps(creative, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    manifest = {
        "topic_id": topic_id,
        "created_at": datetime.now().astimezone().isoformat(),
        "generator": "gemini_draft_generator_v1",
        "model": MODEL,
        "research_audit_status": audit.get("overall_status"),
        "eligible_claim_ids": sorted(x["claim_id"] for x in eligible),
        "held_claim_ids": held,
        "long_script": {
            "file": "long_video_script_draft.md",
            "narration_words": word_count(
                "\n".join(x["narration"] for x in long_obj["sections"])
            ),
            "claim_ids": sorted(long_claims),
        },
        "short_script": {
            "file": "short_video_script_draft.md",
            "narration_words": word_count(
                "\n".join(x["narration"] for x in short_obj["sections"])
            ),
            "claim_ids": sorted(short_claims),
        },
        "references": references,
        "title_ideas": data.get("title_ideas", []),
        "creative_package": "creative_package.json",
        "safety": {
            "production_approved": False,
            "render_authorized": False,
            "upload_authorized": False,
            "public_upload_authorized": False,
        },
    }
    (out / "draft_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out, manifest


def self_test():
    assert validate_topic_id("E1irX9cDX8U")
    try:
        validate_topic_id("../escape")
    except ValueError:
        pass
    else:
        raise AssertionError("Path traversal was not rejected.")
    assert word_count("This is a test.") == 4
    assert LONG_REQUIRED.issubset({"HOOK", "CONTEXT", "TAKEAWAY"})
    print("[PASS] Gemini generator self-tests: 4 checks")
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic-id", default="E1irX9cDX8U")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    topic_id = validate_topic_id(args.topic_id)
    audit, eligible, held, references = collect_research(topic_id)
    data = call_gemini(topic_id, eligible, held)
    data = validate_output(data, eligible, held)
    out, manifest = build_draft(topic_id, audit, eligible, held, references, data)

    print("GEMINI TOPIC-BASED DRAFT GENERATION")
    print("=" * 55)
    print("Topic:", topic_id)
    print("Model:", MODEL)
    print("Draft:", out)
    print("Long narration words:", manifest["long_script"]["narration_words"])
    print("Short narration words:", manifest["short_script"]["narration_words"])
    print("Eligible claims:", ", ".join(manifest["eligible_claim_ids"]))
    print("Held claims excluded:", ", ".join(held) or "None")
    print("Creative package: CREATED")
    print("Production approval: False")
    print("Render authorization: False")
    print("Upload authorization: False")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("[HOLD]", type(exc).__name__ + ":", str(exc))
        raise SystemExit(1)
