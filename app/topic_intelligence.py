
import csv
import json
from datetime import datetime
from pathlib import Path
from statistics import median


# ==================================================
# PATHS
# ==================================================

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "research"

INPUT_FILE = DATA_DIR / "latest_youtube_research_v21.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)


# ==================================================
# EDITORIAL TOPIC DIRECTIONS
# ==================================================

TOPIC_IDEAS = {
    "psychology": [
        "Why do people make emotional decisions even when they know better?",
        "The hidden psychology behind everyday human behaviour"
    ],

    "money": [
        "Rich vs Poor: How everyday money decisions shape the future",
        "Why a higher income does not always create financial freedom"
    ],

    "success": [
        "Why delayed gratification is harder than it looks",
        "How instant gratification affects long-term success"
    ],

    "power": [
        "How emotional control influences power dynamics",
        "Why influence is not always about authority"
    ],

    "social_comparison": [
        "Why seeing other people's lifestyle changes our spending",
        "The hidden cost of comparing your progress with friends"
    ]
}


CATEGORY_NAMES = {
    "psychology": "Human Psychology",
    "money": "Money Psychology",
    "success": "Success",
    "power": "Power Dynamics",
    "social_comparison": "Social Comparison"
}


# ==================================================
# HELPERS
# ==================================================

def safe_number(value):
    try:
        if value is None:
            return None
        return float(value)
    except (ValueError, TypeError):
        return None


def median_of(values):
    clean = [
        safe_number(value)
        for value in values
        if safe_number(value) is not None
    ]

    return round(median(clean), 2) if clean else None


def percentile_scores(videos, field):
    values = [
        safe_number(video.get(field))
        for video in videos
    ]

    valid = [value for value in values if value is not None]

    scores = []

    for value in values:
        if value is None or not valid:
            scores.append(None)
        else:
            score = (
                sum(1 for item in valid if item <= value)
                / len(valid)
            ) * 100

            scores.append(round(score, 2))

    return scores


def write_csv(path, rows, fields):
    with open(
        path,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=fields,
            extrasaction="ignore"
        )

        writer.writeheader()
        writer.writerows(rows)


def age_group(days):
    if days is None:
        return "unknown"

    if days <= 90:
        return "recent"

    if days <= 365:
        return "established"

    return "evergreen"


# ==================================================
# LOAD DATA
# ==================================================

def load_research():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            "V2.1 research report not found: "
            + str(INPUT_FILE)
        )

    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        report = json.load(file)

    videos = report.get("videos", [])

    if not videos:
        raise ValueError(
            "No relevant videos found in V2.1 report."
        )

    return report, videos


# ==================================================
# VIDEO PERFORMANCE ANALYSIS
# ==================================================

def analyse_videos(videos):
    velocity_scores = percentile_scores(
        videos,
        "views_per_day"
    )

    engagement_scores = percentile_scores(
        videos,
        "engagement_rate_percent"
    )

    analysed = []

    for index, original in enumerate(videos):
        video = dict(original)

        velocity = velocity_scores[index]
        engagement = engagement_scores[index]

        if velocity is not None and engagement is not None:
            performance = (
                velocity * 0.70
                + engagement * 0.30
            )
        elif velocity is not None:
            performance = velocity
        else:
            performance = None

        video["velocity_percentile"] = velocity
        video["engagement_percentile"] = engagement

        video["performance_index"] = (
            round(performance, 2)
            if performance is not None else None
        )

        video["age_group"] = age_group(
            safe_number(video.get("days_since_upload"))
        )

        analysed.append(video)

    analysed.sort(
        key=lambda item: (
            item.get("performance_index") is not None,
            item.get("performance_index") or 0
        ),
        reverse=True
    )

    return analysed


# ==================================================
# CATEGORY ANALYSIS
# ==================================================

def analyse_categories(videos):
    groups = {}

    for video in videos:
        categories = [
            category.strip()
            for category in video.get(
                "matched_categories", ""
            ).split(",")
            if category.strip()
        ]

        for category in categories:
            groups.setdefault(category, []).append(video)

    results = []

    for category, items in groups.items():
        recent_count = sum(
            1 for item in items
            if item["age_group"] == "recent"
        )

        results.append({
            "category": category,
            "category_name": CATEGORY_NAMES.get(
                category, category
            ),
            "video_count": len(items),
            "median_views": median_of([
                item.get("views") for item in items
            ]),
            "median_views_per_day": median_of([
                item.get("views_per_day") for item in items
            ]),
            "median_engagement_percent": median_of([
                item.get("engagement_rate_percent")
                for item in items
            ]),
            "median_performance_index": median_of([
                item.get("performance_index")
                for item in items
            ]),
            "recent_video_count": recent_count,
            "recent_video_share_percent": round(
                recent_count / len(items) * 100, 2
            )
        })

    results.sort(
        key=lambda item: (
            item["median_performance_index"] is not None,
            item["median_performance_index"] or 0
        ),
        reverse=True
    )

    for rank, item in enumerate(results, start=1):
        item["rank"] = rank

    return results


# ==================================================
# FORMAT ANALYSIS
# ==================================================

def analyse_formats(videos):
    groups = {}

    for video in videos:
        fmt = video.get("format_category", "unknown")
        groups.setdefault(fmt, []).append(video)

    results = []

    for fmt, items in groups.items():
        results.append({
            "format": fmt,
            "video_count": len(items),
            "median_views": median_of([
                item.get("views") for item in items
            ]),
            "median_views_per_day": median_of([
                item.get("views_per_day") for item in items
            ]),
            "median_engagement_percent": median_of([
                item.get("engagement_rate_percent")
                for item in items
            ]),
            "median_performance_index": median_of([
                item.get("performance_index")
                for item in items
            ])
        })

    return results


# ==================================================
# AGE ANALYSIS
# ==================================================

def analyse_age_groups(videos):
    groups = {}

    for video in videos:
        group = video.get("age_group", "unknown")
        groups.setdefault(group, []).append(video)

    results = []

    for group, items in groups.items():
        results.append({
            "age_group": group,
            "video_count": len(items),
            "median_views": median_of([
                item.get("views") for item in items
            ]),
            "median_views_per_day": median_of([
                item.get("views_per_day") for item in items
            ]),
            "median_engagement_percent": median_of([
                item.get("engagement_rate_percent")
                for item in items
            ])
        })

    return results


# ==================================================
# TOP 10 EDITORIAL DIRECTIONS
# ==================================================

def generate_topic_directions(categories):
    category_lookup = {
        item["category"]: item
        for item in categories
    }

    directions = []

    for category, ideas in TOPIC_IDEAS.items():
        evidence = category_lookup.get(category)

        if not evidence:
            continue

        for idea in ideas:
            directions.append({
                "topic_direction": idea,
                "category": category,
                "category_name": CATEGORY_NAMES[category],
                "category_performance_index": (
                    evidence["median_performance_index"]
                ),
                "evidence_video_count": evidence["video_count"],
                "median_views_per_day": (
                    evidence["median_views_per_day"]
                )
            })

    directions.sort(
        key=lambda item: (
            item["category_performance_index"] is not None,
            item["category_performance_index"] or 0
        ),
        reverse=True
    )

    return directions[:10]


# ==================================================
# SAVE REPORTS
# ==================================================

def save_reports(
    source_report,
    videos,
    categories,
    formats,
    age_groups,
    topic_directions
):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report = {
        "version": "2.2",
        "generated_at": datetime.now().isoformat(),
        "source_report": str(INPUT_FILE),
        "total_videos_analysed": len(videos),
        "source_search_queries": source_report.get(
            "search_queries", []
        ),
        "category_ranking": categories,
        "format_analysis": formats,
        "age_group_analysis": age_groups,
        "top_10_topic_directions": topic_directions,
        "top_performing_videos": videos[:10],
        "limitations": [
            "Performance index is a relative comparison within this dataset.",
            "Views per day is a historical average, not a future prediction.",
            "Engagement uses available public likes and comments only.",
            "Category scores are not proof of audience demand.",
            "Topic directions are editorial suggestions, not validated viral topics.",
            "Short candidates are not confirmed YouTube Shorts."
        ]
    }

    json_path = DATA_DIR / f"topic_intelligence_{timestamp}.json"
    video_path = DATA_DIR / f"video_performance_{timestamp}.csv"
    category_path = DATA_DIR / f"category_ranking_{timestamp}.csv"
    format_path = DATA_DIR / f"format_analysis_{timestamp}.csv"
    age_path = DATA_DIR / f"age_analysis_{timestamp}.csv"
    topics_path = DATA_DIR / f"top10_topic_directions_{timestamp}.csv"

    with open(json_path, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    write_csv(
        video_path,
        videos,
        list(videos[0].keys()) if videos else []
    )

    write_csv(
        category_path,
        categories,
        list(categories[0].keys()) if categories else [
            "rank", "category", "category_name", "video_count"
        ]
    )

    write_csv(
        format_path,
        formats,
        list(formats[0].keys()) if formats else [
            "format", "video_count"
        ]
    )

    write_csv(
        age_path,
        age_groups,
        list(age_groups[0].keys()) if age_groups else [
            "age_group", "video_count"
        ]
    )

    write_csv(
        topics_path,
        topic_directions,
        [
            "topic_direction",
            "category",
            "category_name",
            "category_performance_index",
            "evidence_video_count",
            "median_views_per_day"
        ]
    )

    # Latest V2.2 JSON is separate from all V2.1 reports.
    latest_json = DATA_DIR / "latest_topic_intelligence.json"

    with open(latest_json, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)

    return {
        "json": json_path,
        "video_csv": video_path,
        "category_csv": category_path,
        "format_csv": format_path,
        "age_csv": age_path,
        "topic_csv": topics_path
    }


# ==================================================
# MAIN
# ==================================================

def main():
    print("=" * 60)
    print("TOPIC INTELLIGENCE ENGINE V2.2")
    print("=" * 60)

    source_report, raw_videos = load_research()

    print("Source videos:", len(raw_videos))

    videos = analyse_videos(raw_videos)

    categories = analyse_categories(videos)
    formats = analyse_formats(videos)
    age_groups = analyse_age_groups(videos)

    topic_directions = generate_topic_directions(categories)

    files = save_reports(
        source_report,
        videos,
        categories,
        formats,
        age_groups,
        topic_directions
    )

    print("\n" + "=" * 60)
    print("CATEGORY PERFORMANCE RANKING")
    print("=" * 60)

    for item in categories:
        print(
            f"{item['rank']}. {item['category_name']}"
            f" | Videos: {item['video_count']}"
            f" | Median views/day: {item['median_views_per_day']}"
            f" | Performance index: {item['median_performance_index']}"
        )

    print("\n" + "=" * 60)
    print("FORMAT COMPARISON")
    print("=" * 60)

    for item in formats:
        print(
            f"{item['format']}"
            f" | Videos: {item['video_count']}"
            f" | Median views/day: {item['median_views_per_day']}"
        )

    print("\n" + "=" * 60)
    print("RECENT VS EVERGREEN")
    print("=" * 60)

    for item in age_groups:
        print(
            f"{item['age_group']}"
            f" | Videos: {item['video_count']}"
            f" | Median views/day: {item['median_views_per_day']}"
        )

    print("\n" + "=" * 60)
    print("TOP 10 EDITORIAL TOPIC DIRECTIONS")
    print("=" * 60)

    for index, item in enumerate(topic_directions, start=1):
        print(f"\n{index}. {item['topic_direction']}")
        print("   Category:", item["category_name"])
        print("   Evidence videos:", item["evidence_video_count"])
        print(
            "   Category performance:",
            item["category_performance_index"]
        )

    print("\n" + "=" * 60)
    print("REPORT FILES")
    print("=" * 60)

    for name, path in files.items():
        print(f"{name.upper()}: {path}")

    print("\nSTATUS: SUCCESS")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()

    except Exception as error:
        print("\nTOPIC INTELLIGENCE ERROR:")
        print(type(error).__name__ + ":", error)
