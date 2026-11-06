
import argparse
import csv
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DB = (
    ROOT / "data" / "research"
    / "youtube_universe_v33" / "youtube_universe.db"
)

DEFAULT_OUTPUT = (
    ROOT / "data" / "research"
    / "youtube_universe_v33"
)

ENGINE_VERSION = "V33.1-RELEVANCE"

# Generic words are intentionally given lower weight.
CATEGORY_TERMS = {
    "Human Psychology": [
        "psychology", "human psychology", "human behavior",
        "human behaviour", "behavior", "behaviour",
        "human nature", "emotions", "personality",
        "overthinking", "subconscious", "mental",
        "brain", "mind", "habits", "people",
        "मनोविज्ञान", "व्यवहार", "मानसिक"
    ],
    "Money Psychology": [
        "money psychology", "financial psychology",
        "wealth psychology", "money mindset",
        "money", "wealth", "finance", "financial",
        "spending", "saving", "investing",
        "greed", "income", "poverty",
        "पैसा", "अमीर", "गरीब", "दौलत"
    ],
    "Power Dynamics": [
        "power dynamics", "social power",
        "power", "influence", "authority",
        "dominance", "persuasion", "control",
        "manipulation", "leadership", "status",
        "negotiation", "शक्ति", "प्रभाव", "नेतृत्व"
    ],
    "Success": [
        "success", "success mindset",
        "personal development", "self improvement",
        "discipline", "motivation", "productivity",
        "goals", "growth", "achievement",
        "focus", "consistency", "सफलता",
        "अनुशासन"
    ],
    "Social Comparison": [
        "social comparison", "social status",
        "peer pressure", "self worth",
        "social media", "comparison",
        "lifestyle", "jealousy", "envy",
        "validation", "दिखावा", "जलन", "तुलना"
    ]
}

# More specific concepts provide contextual evidence.
CONTEXT_TERMS = {
    "Human Psychology": [
        "emotional intelligence", "human nature",
        "social behavior", "social behaviour",
        "cognitive bias", "decision making",
        "body language", "self awareness",
        "relationship psychology", "mental habits"
    ],
    "Money Psychology": [
        "financial decisions", "spending habits",
        "wealth building", "money decisions",
        "financial behavior", "financial behaviour",
        "scarcity mindset", "rich mindset"
    ],
    "Power Dynamics": [
        "social influence", "power structure",
        "psychological manipulation", "social hierarchy",
        "negotiation skills", "authority bias"
    ],
    "Success": [
        "habit formation", "long term goals",
        "self discipline", "time management",
        "personal growth", "goal setting"
    ],
    "Social Comparison": [
        "upward comparison", "downward comparison",
        "social validation", "status anxiety",
        "fear of missing out", "peer influence"
    ]
}

CATEGORY_ANCHORS = {
    "Human Psychology": [
        "human psychology", "psychology",
        "human behavior", "human behaviour",
        "मनोविज्ञान"
    ],
    "Money Psychology": [
        "money psychology", "financial psychology",
        "wealth psychology", "money mindset"
    ],
    "Power Dynamics": [
        "power dynamics", "social power",
        "influence", "authority"
    ],
    "Success": [
        "success", "success mindset",
        "personal development"
    ],
    "Social Comparison": [
        "social comparison", "social status",
        "peer pressure"
    ]
}

PROMOTIONAL_PATTERNS = [
    r"copyright disclaimer.*",
    r"disclaimer under sec.*",
    r"fair use.*",
    r"subscribe to.*",
    r"like and subscribe.*",
    r"follow us.*",
    r"contact us.*",
    r"business enquiries.*",
    r"business inquiries.*",
    r"for sponsorship.*",
    r"watch more videos.*",
    r"share this video.*"
]

GENERIC_TERMS = {
    "mind", "brain", "people", "mental",
    "behavior", "behaviour", "habits"
}


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat()


def parse_json_list(value):
    if isinstance(value, list):
        return value

    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) else []
    except (ValueError, TypeError):
        return []


def normalize_text(text):
    text = str(text or "").lower()
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", " ", text)
    text = re.sub(r"#\w+", " ", text)
    text = re.sub(r"@\w+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_description(description):
    lines = str(description or "").splitlines()
    kept = []

    for line in lines:
        raw = line.strip()

        if not raw:
            continue

        lower = raw.lower()

        if lower.startswith(("http://", "https://", "www.")):
            continue

        if re.match(r"^[#@]", raw):
            continue

        if any(
            re.search(pattern, lower)
            for pattern in PROMOTIONAL_PATTERNS
        ):
            continue

        if len(raw) < 3:
            continue

        # Hashtag-heavy promotional lines are discarded.
        hashtags = len(re.findall(r"#\w+", raw))

        if hashtags >= 2:
            continue

        kept.append(raw)

    return normalize_text(" ".join(kept))


def contains_term(text, term):
    text = normalize_text(text)
    term = normalize_text(term)

    if not text or not term:
        return False

    pattern = (
        r"(?<!\w)" + re.escape(term) + r"(?!\w)"
    )

    return re.search(pattern, text) is not None


def find_matches(text, terms):
    return [
        term for term in terms
        if contains_term(text, term)
    ]


def calculate_relevance(title, description, categories):
    title_clean = normalize_text(title)
    description_clean = clean_description(description)

    category_names = [
        c for c in categories
        if c in CATEGORY_TERMS
    ]

    if not category_names:
        return {
            "relevance_score": None,
            "relevance_status": "HUMAN_REVIEW",
            "relevance_confidence": "LOW",
            "relevance_reason": "No recognized category metadata",
            "relevance_category": "",
            "title_score": 0,
            "description_score": 0,
            "category_score": 0,
            "context_score": 0,
            "title_matches": [],
            "description_matches": [],
            "context_matches": []
        }

    results = []

    for category in category_names:
        terms = CATEGORY_TERMS[category]

        title_matches = find_matches(
            title_clean, terms
        )

        description_matches = find_matches(
            description_clean, terms
        )

        title_specific = [
            t for t in title_matches
            if t not in GENERIC_TERMS
        ]

        description_specific = [
            t for t in description_matches
            if t not in GENERIC_TERMS
        ]

        # Title: maximum 50 points.
        title_score = min(
            50,
            len(title_specific) * 17
            + len(title_matches) * 3
        )

        # Description: maximum 20 points.
        description_score = min(
            20,
            len(description_specific) * 4
            + len(description_matches)
        )

        # Category anchor: maximum 20 points.
        anchors = CATEGORY_ANCHORS[category]

        title_anchor = find_matches(
            title_clean, anchors
        )

        description_anchor = find_matches(
            description_clean, anchors
        )

        if title_anchor:
            category_score = 20
        elif description_anchor:
            category_score = 10
        else:
            category_score = 0

        # Contextual relevance: maximum 10 points.
        context_matches = find_matches(
            title_clean + " " + description_clean,
            CONTEXT_TERMS[category]
        )

        context_score = min(
            10, len(context_matches) * 5
        )

        total = round(
            title_score
            + description_score
            + category_score
            + context_score,
            2
        )

        results.append({
            "category": category,
            "score": min(100, total),
            "title_score": title_score,
            "description_score": description_score,
            "category_score": category_score,
            "context_score": context_score,
            "title_matches": title_matches,
            "description_matches": description_matches,
            "context_matches": context_matches
        })

    # Keep the strongest category as primary.
    best = max(
        results,
        key=lambda x: (
            x["score"],
            x["title_score"],
            x["category"]
        )
    )

    score = best["score"]

    if score >= 75:
        status = "HIGH_RELEVANCE"
    elif score >= 40:
        status = "REVIEW_RELEVANCE"
    else:
        status = "LOW_RELEVANCE"

    if best["title_score"] >= 17:
        confidence = "HIGH"
    elif best["title_score"] > 0:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    reason_parts = []

    if best["title_matches"]:
        reason_parts.append(
            "Title matches: "
            + ", ".join(best["title_matches"])
        )

    if best["description_matches"]:
        reason_parts.append(
            "Description matches: "
            + ", ".join(best["description_matches"])
        )

    if best["context_matches"]:
        reason_parts.append(
            "Context matches: "
            + ", ".join(best["context_matches"])
        )

    if not reason_parts:
        reason_parts.append(
            "No meaningful category terms detected"
        )

    return {
        "relevance_score": score,
        "relevance_status": status,
        "relevance_confidence": confidence,
        "relevance_reason": " | ".join(reason_parts),
        "relevance_category": best["category"],
        "title_score": best["title_score"],
        "description_score": best["description_score"],
        "category_score": best["category_score"],
        "context_score": best["context_score"],
        "title_matches": best["title_matches"],
        "description_matches": best["description_matches"],
        "context_matches": best["context_matches"]
    }


def load_videos(connection):
    connection.row_factory = sqlite3.Row

    rows = connection.execute(
        "SELECT * FROM videos ORDER BY video_id"
    ).fetchall()

    return [dict(row) for row in rows]


def score_videos(videos):
    output = []

    for original in videos:
        video = dict(original)

        categories = parse_json_list(
            video.get("category_matches")
        )

        result = calculate_relevance(
            video.get("title"),
            video.get("description"),
            categories
        )

        video.update(result)

        video["video_url"] = (
            "https://www.youtube.com/watch?v="
            + str(video.get("video_id", ""))
        )

        output.append(video)

    return output


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return

    fields = []

    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)

    with path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
            extrasaction="ignore"
        )

        writer.writeheader()

        for row in rows:
            clean = {}

            for key, value in row.items():
                if isinstance(value, (list, dict)):
                    clean[key] = json.dumps(
                        value,
                        ensure_ascii=False
                    )
                else:
                    clean[key] = value

            writer.writerow(clean)


def main():
    parser = argparse.ArgumentParser(
        description="YouTube Universe V3.3 Relevance Engine"
    )

    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB)
    )

    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT)
    )

    args = parser.parse_args()

    db_path = Path(args.db)
    output_dir = Path(args.output)

    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found: {db_path}"
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 60)
    print("YOUTUBE UNIVERSE SCANNER V3.3")
    print("RELEVANCE ENGINE")
    print("=" * 60)

    connection = sqlite3.connect(
        f"file:{db_path.as_posix()}?mode=ro",
        uri=True
    )

    try:
        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if integrity != "ok":
            raise RuntimeError(
                f"Database integrity failed: {integrity}"
            )

        videos = load_videos(connection)

    finally:
        connection.close()

    print("Database integrity:", integrity)
    print("Input videos:", len(videos))

    scored = score_videos(videos)

    high = [
        v for v in scored
        if v["relevance_status"] == "HIGH_RELEVANCE"
    ]

    review = [
        v for v in scored
        if v["relevance_status"] == "REVIEW_RELEVANCE"
    ]

    low = [
        v for v in scored
        if v["relevance_status"] == "LOW_RELEVANCE"
    ]

    human = [
        v for v in scored
        if v["relevance_status"] == "HUMAN_REVIEW"
    ]

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    master_path = (
        output_dir
        / f"master_scored_videos_v33_{timestamp}.csv"
    )

    high_path = (
        output_dir
        / f"high_relevance_videos_v33_{timestamp}.csv"
    )

    review_path = (
        output_dir
        / f"relevance_review_v33_{timestamp}.csv"
    )

    low_path = (
        output_dir
        / f"low_relevance_videos_v33_{timestamp}.csv"
    )

    audit_path = (
        output_dir
        / f"relevance_audit_v33_{timestamp}.csv"
    )

    write_csv(master_path, scored)
    write_csv(high_path, high)
    write_csv(review_path, review + human)
    write_csv(low_path, low)

    audit = []

    for video in scored:
        audit.append({
            "video_id": video.get("video_id"),
            "title": video.get("title"),
            "category": video.get("relevance_category"),
            "score": video.get("relevance_score"),
            "status": video.get("relevance_status"),
            "confidence": video.get("relevance_confidence"),
            "title_score": video.get("title_score"),
            "description_score": video.get("description_score"),
            "category_score": video.get("category_score"),
            "context_score": video.get("context_score"),
            "reason": video.get("relevance_reason")
        })

    write_csv(audit_path, audit)

    category_counts = Counter(
        v["relevance_category"]
        for v in scored
        if v["relevance_category"]
    )

    report = {
        "engine": "YouTube Universe Scanner V3.3",
        "engine_version": ENGINE_VERSION,
        "generated_at": utc_timestamp(),
        "database": str(db_path),
        "database_read_only": True,
        "api_calls": 0,
        "input_video_count": len(scored),
        "high_relevance_count": len(high),
        "review_count": len(review),
        "low_relevance_count": len(low),
        "human_review_count": len(human),
        "category_distribution": dict(category_counts),
        "scoring_weights": {
            "title": 50,
            "description": 20,
            "category_anchor": 20,
            "contextual_keywords": 10
        },
        "thresholds": {
            "high_relevance": 75,
            "review_relevance": 40,
            "low_relevance": 0
        },
        "limitations": [
            "Metadata-based relevance is not transcript verification.",
            "Keyword matching cannot fully understand semantic context.",
            "Description keyword stuffing is reduced but not eliminated.",
            "Search category metadata is not independent proof of relevance.",
            "Human review is required before final topic selection.",
            "Current database has only Human Psychology category records."
        ],
        "files": {
            "master": master_path.name,
            "high_relevance": high_path.name,
            "review": review_path.name,
            "low_relevance": low_path.name,
            "audit": audit_path.name
        }
    }

    report_path = (
        output_dir
        / f"relevance_report_v33_{timestamp}.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    latest_files = {
        "latest_master_scored_videos_v33.csv": master_path,
        "latest_high_relevance_videos_v33.csv": high_path,
        "latest_relevance_review_v33.csv": review_path,
        "latest_low_relevance_videos_v33.csv": low_path,
        "latest_relevance_audit_v33.csv": audit_path,
        "latest_relevance_report_v33.json": report_path
    }

    for latest_name, source in latest_files.items():
        (output_dir / latest_name).write_bytes(
            source.read_bytes()
        )

    print("\nSCORING SUMMARY")
    print("Total:", len(scored))
    print("High relevance:", len(high))
    print("Review:", len(review))
    print("Low relevance:", len(low))
    print("Human review:", len(human))

    print("\nCATEGORY DISTRIBUTION")
    for category, count in category_counts.items():
        print(category, ":", count)

    print("\nOUTPUT FILES")
    for name in latest_files:
        path = output_dir / name
        print(
            "PASS" if path.exists() else "FAIL",
            name,
            path.stat().st_size if path.exists() else 0
        )

    print("\nAPI CALLS: 0")
    print("DATABASE MODIFIED: NO")
    print("STATUS: COMPLETED")


if __name__ == "__main__":
    main()




import argparse
import csv
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DB = (
    ROOT / "data" / "research"
    / "youtube_universe_v33" / "youtube_universe.db"
)

DEFAULT_OUTPUT = (
    ROOT / "data" / "research"
    / "youtube_universe_v33"
)

ENGINE_VERSION = "V33.1-RELEVANCE"

# Generic words are intentionally given lower weight.
CATEGORY_TERMS = {
    "Human Psychology": [
        "psychology", "human psychology", "human behavior",
        "human behaviour", "behavior", "behaviour",
        "human nature", "emotions", "personality",
        "overthinking", "subconscious", "mental",
        "brain", "mind", "habits", "people",
        "मनोविज्ञान", "व्यवहार", "मानसिक"
    ],
    "Money Psychology": [
        "money psychology", "financial psychology",
        "wealth psychology", "money mindset",
        "money", "wealth", "finance", "financial",
        "spending", "saving", "investing",
        "greed", "income", "poverty",
        "पैसा", "अमीर", "गरीब", "दौलत"
    ],
    "Power Dynamics": [
        "power dynamics", "social power",
        "power", "influence", "authority",
        "dominance", "persuasion", "control",
        "manipulation", "leadership", "status",
        "negotiation", "शक्ति", "प्रभाव", "नेतृत्व"
    ],
    "Success": [
        "success", "success mindset",
        "personal development", "self improvement",
        "discipline", "motivation", "productivity",
        "goals", "growth", "achievement",
        "focus", "consistency", "सफलता",
        "अनुशासन"
    ],
    "Social Comparison": [
        "social comparison", "social status",
        "peer pressure", "self worth",
        "social media", "comparison",
        "lifestyle", "jealousy", "envy",
        "validation", "दिखावा", "जलन", "तुलना"
    ]
}

# More specific concepts provide contextual evidence.
CONTEXT_TERMS = {
    "Human Psychology": [
        "emotional intelligence", "human nature",
        "social behavior", "social behaviour",
        "cognitive bias", "decision making",
        "body language", "self awareness",
        "relationship psychology", "mental habits"
    ],
    "Money Psychology": [
        "financial decisions", "spending habits",
        "wealth building", "money decisions",
        "financial behavior", "financial behaviour",
        "scarcity mindset", "rich mindset"
    ],
    "Power Dynamics": [
        "social influence", "power structure",
        "psychological manipulation", "social hierarchy",
        "negotiation skills", "authority bias"
    ],
    "Success": [
        "habit formation", "long term goals",
        "self discipline", "time management",
        "personal growth", "goal setting"
    ],
    "Social Comparison": [
        "upward comparison", "downward comparison",
        "social validation", "status anxiety",
        "fear of missing out", "peer influence"
    ]
}

CATEGORY_ANCHORS = {
    "Human Psychology": [
        "human psychology", "psychology",
        "human behavior", "human behaviour",
        "मनोविज्ञान"
    ],
    "Money Psychology": [
        "money psychology", "financial psychology",
        "wealth psychology", "money mindset"
    ],
    "Power Dynamics": [
        "power dynamics", "social power",
        "influence", "authority"
    ],
    "Success": [
        "success", "success mindset",
        "personal development"
    ],
    "Social Comparison": [
        "social comparison", "social status",
        "peer pressure"
    ]
}

PROMOTIONAL_PATTERNS = [
    r"copyright disclaimer.*",
    r"disclaimer under sec.*",
    r"fair use.*",
    r"subscribe to.*",
    r"like and subscribe.*",
    r"follow us.*",
    r"contact us.*",
    r"business enquiries.*",
    r"business inquiries.*",
    r"for sponsorship.*",
    r"watch more videos.*",
    r"share this video.*"
]

GENERIC_TERMS = {
    "mind", "brain", "people", "mental",
    "behavior", "behaviour", "habits"
}


def utc_timestamp():
    return datetime.now(timezone.utc).isoformat()


def parse_json_list(value):
    if isinstance(value, list):
        return value

    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) else []
    except (ValueError, TypeError):
        return []


def normalize_text(text):
    text = str(text or "").lower()
    text = re.sub(r"https?://\S+|www\.\S+", " ", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.\w+", " ", text)
    text = re.sub(r"#\w+", " ", text)
    text = re.sub(r"@\w+", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_description(description):
    lines = str(description or "").splitlines()
    kept = []

    for line in lines:
        raw = line.strip()

        if not raw:
            continue

        lower = raw.lower()

        if lower.startswith(("http://", "https://", "www.")):
            continue

        if re.match(r"^[#@]", raw):
            continue

        if any(
            re.search(pattern, lower)
            for pattern in PROMOTIONAL_PATTERNS
        ):
            continue

        if len(raw) < 3:
            continue

        # Hashtag-heavy promotional lines are discarded.
        hashtags = len(re.findall(r"#\w+", raw))

        if hashtags >= 2:
            continue

        kept.append(raw)

    return normalize_text(" ".join(kept))


def contains_term(text, term):
    text = normalize_text(text)
    term = normalize_text(term)

    if not text or not term:
        return False

    pattern = (
        r"(?<!\w)" + re.escape(term) + r"(?!\w)"
    )

    return re.search(pattern, text) is not None


def find_matches(text, terms):
    return [
        term for term in terms
        if contains_term(text, term)
    ]


def calculate_relevance(title, description, categories):
    title_clean = normalize_text(title)
    description_clean = clean_description(description)

    category_names = [
        c for c in categories
        if c in CATEGORY_TERMS
    ]

    if not category_names:
        return {
            "relevance_score": None,
            "relevance_status": "HUMAN_REVIEW",
            "relevance_confidence": "LOW",
            "relevance_reason": "No recognized category metadata",
            "relevance_category": "",
            "title_score": 0,
            "description_score": 0,
            "category_score": 0,
            "context_score": 0,
            "title_matches": [],
            "description_matches": [],
            "context_matches": []
        }

    results = []

    for category in category_names:
        terms = CATEGORY_TERMS[category]

        title_matches = find_matches(
            title_clean, terms
        )

        description_matches = find_matches(
            description_clean, terms
        )

        title_specific = [
            t for t in title_matches
            if t not in GENERIC_TERMS
        ]

        description_specific = [
            t for t in description_matches
            if t not in GENERIC_TERMS
        ]

        # Title: maximum 50 points.
        title_score = min(
            50,
            len(title_specific) * 17
            + len(title_matches) * 3
        )

        # Description: maximum 20 points.
        description_score = min(
            20,
            len(description_specific) * 4
            + len(description_matches)
        )

        # Category anchor: maximum 20 points.
        anchors = CATEGORY_ANCHORS[category]

        title_anchor = find_matches(
            title_clean, anchors
        )

        description_anchor = find_matches(
            description_clean, anchors
        )

        if title_anchor:
            category_score = 20
        elif description_anchor:
            category_score = 10
        else:
            category_score = 0

        # Contextual relevance: maximum 10 points.
        context_matches = find_matches(
            title_clean + " " + description_clean,
            CONTEXT_TERMS[category]
        )

        context_score = min(
            10, len(context_matches) * 5
        )

        total = round(
            title_score
            + description_score
            + category_score
            + context_score,
            2
        )

        results.append({
            "category": category,
            "score": min(100, total),
            "title_score": title_score,
            "description_score": description_score,
            "category_score": category_score,
            "context_score": context_score,
            "title_matches": title_matches,
            "description_matches": description_matches,
            "context_matches": context_matches
        })

    # Keep the strongest category as primary.
    best = max(
        results,
        key=lambda x: (
            x["score"],
            x["title_score"],
            x["category"]
        )
    )

    score = best["score"]

    if score >= 75:
        status = "HIGH_RELEVANCE"
    elif score >= 40:
        status = "REVIEW_RELEVANCE"
    else:
        status = "LOW_RELEVANCE"

    if best["title_score"] >= 17:
        confidence = "HIGH"
    elif best["title_score"] > 0:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    reason_parts = []

    if best["title_matches"]:
        reason_parts.append(
            "Title matches: "
            + ", ".join(best["title_matches"])
        )

    if best["description_matches"]:
        reason_parts.append(
            "Description matches: "
            + ", ".join(best["description_matches"])
        )

    if best["context_matches"]:
        reason_parts.append(
            "Context matches: "
            + ", ".join(best["context_matches"])
        )

    if not reason_parts:
        reason_parts.append(
            "No meaningful category terms detected"
        )

    return {
        "relevance_score": score,
        "relevance_status": status,
        "relevance_confidence": confidence,
        "relevance_reason": " | ".join(reason_parts),
        "relevance_category": best["category"],
        "title_score": best["title_score"],
        "description_score": best["description_score"],
        "category_score": best["category_score"],
        "context_score": best["context_score"],
        "title_matches": best["title_matches"],
        "description_matches": best["description_matches"],
        "context_matches": best["context_matches"]
    }


def load_videos(connection):
    connection.row_factory = sqlite3.Row

    rows = connection.execute(
        "SELECT * FROM videos ORDER BY video_id"
    ).fetchall()

    return [dict(row) for row in rows]


def score_videos(videos):
    output = []

    for original in videos:
        video = dict(original)

        categories = parse_json_list(
            video.get("category_matches")
        )

        result = calculate_relevance(
            video.get("title"),
            video.get("description"),
            categories
        )

        video.update(result)

        video["video_url"] = (
            "https://www.youtube.com/watch?v="
            + str(video.get("video_id", ""))
        )

        output.append(video)

    return output


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return

    fields = []

    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)

    with path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
            extrasaction="ignore"
        )

        writer.writeheader()

        for row in rows:
            clean = {}

            for key, value in row.items():
                if isinstance(value, (list, dict)):
                    clean[key] = json.dumps(
                        value,
                        ensure_ascii=False
                    )
                else:
                    clean[key] = value

            writer.writerow(clean)


def main():
    parser = argparse.ArgumentParser(
        description="YouTube Universe V3.3 Relevance Engine"
    )

    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB)
    )

    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT)
    )

    args = parser.parse_args()

    db_path = Path(args.db)
    output_dir = Path(args.output)

    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found: {db_path}"
        )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    print("=" * 60)
    print("YOUTUBE UNIVERSE SCANNER V3.3")
    print("RELEVANCE ENGINE")
    print("=" * 60)

    connection = sqlite3.connect(
        f"file:{db_path.as_posix()}?mode=ro",
        uri=True
    )

    try:
        integrity = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0]

        if integrity != "ok":
            raise RuntimeError(
                f"Database integrity failed: {integrity}"
            )

        videos = load_videos(connection)

    finally:
        connection.close()

    print("Database integrity:", integrity)
    print("Input videos:", len(videos))

    scored = score_videos(videos)

    high = [
        v for v in scored
        if v["relevance_status"] == "HIGH_RELEVANCE"
    ]

    review = [
        v for v in scored
        if v["relevance_status"] == "REVIEW_RELEVANCE"
    ]

    low = [
        v for v in scored
        if v["relevance_status"] == "LOW_RELEVANCE"
    ]

    human = [
        v for v in scored
        if v["relevance_status"] == "HUMAN_REVIEW"
    ]

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    master_path = (
        output_dir
        / f"master_scored_videos_v33_{timestamp}.csv"
    )

    high_path = (
        output_dir
        / f"high_relevance_videos_v33_{timestamp}.csv"
    )

    review_path = (
        output_dir
        / f"relevance_review_v33_{timestamp}.csv"
    )

    low_path = (
        output_dir
        / f"low_relevance_videos_v33_{timestamp}.csv"
    )

    audit_path = (
        output_dir
        / f"relevance_audit_v33_{timestamp}.csv"
    )

    write_csv(master_path, scored)
    write_csv(high_path, high)
    write_csv(review_path, review + human)
    write_csv(low_path, low)

    audit = []

    for video in scored:
        audit.append({
            "video_id": video.get("video_id"),
            "title": video.get("title"),
            "category": video.get("relevance_category"),
            "score": video.get("relevance_score"),
            "status": video.get("relevance_status"),
            "confidence": video.get("relevance_confidence"),
            "title_score": video.get("title_score"),
            "description_score": video.get("description_score"),
            "category_score": video.get("category_score"),
            "context_score": video.get("context_score"),
            "reason": video.get("relevance_reason")
        })

    write_csv(audit_path, audit)

    category_counts = Counter(
        v["relevance_category"]
        for v in scored
        if v["relevance_category"]
    )

    report = {
        "engine": "YouTube Universe Scanner V3.3",
        "engine_version": ENGINE_VERSION,
        "generated_at": utc_timestamp(),
        "database": str(db_path),
        "database_read_only": True,
        "api_calls": 0,
        "input_video_count": len(scored),
        "high_relevance_count": len(high),
        "review_count": len(review),
        "low_relevance_count": len(low),
        "human_review_count": len(human),
        "category_distribution": dict(category_counts),
        "scoring_weights": {
            "title": 50,
            "description": 20,
            "category_anchor": 20,
            "contextual_keywords": 10
        },
        "thresholds": {
            "high_relevance": 75,
            "review_relevance": 40,
            "low_relevance": 0
        },
        "limitations": [
            "Metadata-based relevance is not transcript verification.",
            "Keyword matching cannot fully understand semantic context.",
            "Description keyword stuffing is reduced but not eliminated.",
            "Search category metadata is not independent proof of relevance.",
            "Human review is required before final topic selection.",
            "Current database has only Human Psychology category records."
        ],
        "files": {
            "master": master_path.name,
            "high_relevance": high_path.name,
            "review": review_path.name,
            "low_relevance": low_path.name,
            "audit": audit_path.name
        }
    }

    report_path = (
        output_dir
        / f"relevance_report_v33_{timestamp}.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    latest_files = {
        "latest_master_scored_videos_v33.csv": master_path,
        "latest_high_relevance_videos_v33.csv": high_path,
        "latest_relevance_review_v33.csv": review_path,
        "latest_low_relevance_videos_v33.csv": low_path,
        "latest_relevance_audit_v33.csv": audit_path,
        "latest_relevance_report_v33.json": report_path
    }

    for latest_name, source in latest_files.items():
        (output_dir / latest_name).write_bytes(
            source.read_bytes()
        )

    print("\nSCORING SUMMARY")
    print("Total:", len(scored))
    print("High relevance:", len(high))
    print("Review:", len(review))
    print("Low relevance:", len(low))
    print("Human review:", len(human))

    print("\nCATEGORY DISTRIBUTION")
    for category, count in category_counts.items():
        print(category, ":", count)

    print("\nOUTPUT FILES")
    for name in latest_files:
        path = output_dir / name
        print(
            "PASS" if path.exists() else "FAIL",
            name,
            path.stat().st_size if path.exists() else 0
        )

    print("\nAPI CALLS: 0")
    print("DATABASE MODIFIED: NO")
    print("STATUS: COMPLETED")


if __name__ == "__main__":
    main()

