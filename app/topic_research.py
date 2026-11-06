
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent

CONFIG_FILE = ROOT / "config" / "channel.yaml"
IDEAS_FILE = ROOT / "data" / "research" / "topic_ideas.yaml"

OUTPUT_DIR = ROOT / "data" / "research"
REPORT_DIR = ROOT / "reports"


def load_yaml(path):
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def calculate_relevance(tags, keywords, niche):
    tag_set = {str(tag).lower() for tag in tags}

    keyword_set = {str(word).lower() for word in keywords}
    niche_set = {str(word).lower() for word in niche}

    matched_keywords = sorted(tag_set.intersection(keyword_set))
    matched_niche = sorted(tag_set.intersection(niche_set))

    # Editorial relevance score, not a prediction of virality.
    score = min(100, len(matched_keywords) * 15 + len(matched_niche) * 20)

    return score, matched_keywords, matched_niche


def generate_report():
    config = load_yaml(CONFIG_FILE)
    idea_data = load_yaml(IDEAS_FILE)

    channel = config.get("channel", {})
    content = config.get("content", {})
    research = config.get("research", {})

    keywords = research.get("keywords", [])
    niche = content.get("niche", [])

    ideas = idea_data.get("topics", [])

    if not ideas:
        raise ValueError("No topic ideas found in topic_ideas.yaml")

    results = []

    for idea in ideas:
        tags = idea.get("tags", [])

        score, matched_keywords, matched_niche = (
            calculate_relevance(tags, keywords, niche)
        )

        results.append({
            "title": idea.get("title", ""),
            "hook": idea.get("hook", ""),
            "tags": tags,
            "relevance_score": score,
            "matched_keywords": matched_keywords,
            "matched_niche": matched_niche,
            "score_type": "niche_relevance_not_virality",
            "channel": channel.get("name", "Unknown"),
        })

    results.sort(
        key=lambda item: item["relevance_score"],
        reverse=True
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    json_file = OUTPUT_DIR / f"topics_{timestamp}.json"
    csv_file = OUTPUT_DIR / f"topics_{timestamp}.csv"
    latest_json = OUTPUT_DIR / "latest_topics.json"
    latest_csv = OUTPUT_DIR / "latest_topics.csv"

    report = {
        "channel": channel.get("name", "Unknown"),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_topics": len(results),
        "scoring_method": (
            "Editorial niche relevance. Not a trend or virality prediction."
        ),
        "topics": results,
    }

    with json_file.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)

    fieldnames = [
        "title",
        "hook",
        "tags",
        "relevance_score",
        "matched_keywords",
        "matched_niche",
        "score_type",
        "channel",
    ]

    with csv_file.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()

        for item in results:
            row = item.copy()
            row["tags"] = ", ".join(item["tags"])
            row["matched_keywords"] = ", ".join(
                item["matched_keywords"]
            )
            row["matched_niche"] = ", ".join(
                item["matched_niche"]
            )
            writer.writerow(row)

    # Latest files are convenient shortcuts.
    latest_json.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    latest_csv.write_bytes(csv_file.read_bytes())

    print("=" * 55)
    print("TOPIC RESEARCH ENGINE V1")
    print("=" * 55)
    print(f"Channel: {report['channel']}")
    print(f"Topics processed: {len(results)}")
    print("Scoring: Niche relevance only")
    print("-" * 55)

    for index, item in enumerate(results[:10], start=1):
        print(
            f"{index:02}. [{item['relevance_score']:03}/100] "
            f"{item['title']}"
        )

    print("-" * 55)
    print(f"JSON: {json_file}")
    print(f"CSV : {csv_file}")
    print("STATUS: SUCCESS")


if __name__ == "__main__":
    try:
        generate_report()
    except Exception as error:
        print(f"RESEARCH ERROR: {error}")
        raise
