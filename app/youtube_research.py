
import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ==================================================
# PATHS AND SETTINGS
# ==================================================

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "channel.yaml"
OUTPUT_DIR = ROOT / "data" / "research"

ENV_FILE = Path(
    r"C:\Users\sumit\youtube-automation-runtime\.env"
)

MAX_SEARCH_QUERIES = 5
RESULTS_PER_QUERY = 10

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# ==================================================
# RELEVANCE KEYWORDS
# ==================================================

TOPIC_KEYWORDS = {
    "psychology": [
        "psychology", "psychological", "human behavior",
        "human behaviour", "behavioral psychology",
        "behavioural psychology", "social psychology",
        "dark psychology", "psychological facts",
        "psychology facts", "cognitive bias",
        "cognitive biases", "decision making",
        "mental models", "मनोविज्ञान", "मानसिकता"
    ],

    "money": [
        "money psychology", "psychology of money",
        "rich vs poor", "poor vs rich",
        "rich mindset", "poor mindset",
        "financial behavior", "financial behaviour",
        "financial decisions", "emotional spending",
        "lifestyle inflation", "money habits",
        "spending habits", "money", "finance",
        "financial", "wealth", "gareeb", "ameer",
        "paisa", "paise", "गरीब", "अमीर", "पैसा"
    ],

    "success": [
        "success habits", "success mindset",
        "delayed gratification", "instant gratification",
        "growth mindset", "self improvement",
        "self-improvement", "personal development",
        "discipline", "productivity", "success",
        "successful", "consistency", "सफलता"
    ],

    "power": [
        "power dynamics", "48 laws of power",
        "robert greene", "social influence",
        "social status", "human manipulation",
        "dark psychology", "persuasion",
        "dominance", "authority", "influence",
        "manipulation", "power"
    ],

    "social_comparison": [
        "social comparison", "stop comparing",
        "compare yourself", "comparison",
        "peer pressure", "social validation",
        "status symbols", "friends influence",
        "keeping up with the joneses",
        "दूसरों से तुलना"
    ]
}

RELEVANCE_THRESHOLD = 35


# ==================================================
# VIDEO DURATION
# ==================================================

def parse_duration(duration):
    """
    Convert ISO 8601 duration such as PT1H2M10S
    into total seconds.
    """

    match = re.fullmatch(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        duration or ""
    )

    if not match:
        return 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)

    return hours * 3600 + minutes * 60 + seconds


def classify_format(duration_seconds):
    if duration_seconds <= 180:
        return "short_candidate"

    return "long_form"


# ==================================================
# CONFIGURATION
# ==================================================

def load_settings():
    load_dotenv(ENV_FILE)

    api_key = os.getenv("YOUTUBE_API_KEY")

    if not api_key or "PASTE_" in api_key:
        raise RuntimeError("YouTube API key is missing.")

    with open(CONFIG_FILE, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    return api_key, config


def get_search_queries(config):
    keywords = config.get("research", {}).get("keywords", [])

    return [
        f"{keyword} Hindi"
        for keyword in keywords[:MAX_SEARCH_QUERIES]
    ]


# ==================================================
# YOUTUBE SEARCH
# ==================================================

def search_videos(youtube, queries):
    found_videos = {}

    for number, query in enumerate(queries, start=1):
        print(f"\nSearching {number}/{len(queries)}: {query}")

        response = youtube.search().list(
            part="snippet",
            q=query,
            type="video",
            maxResults=RESULTS_PER_QUERY,
            order="viewCount",
            regionCode="IN",
            relevanceLanguage="hi"
        ).execute()

        for item in response.get("items", []):
            video_id = item["id"]["videoId"]
            snippet = item.get("snippet", {})

            if video_id not in found_videos:
                found_videos[video_id] = {
                    "video_id": video_id,
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "channel_name": snippet.get("channelTitle", ""),
                    "search_queries": []
                }

            if query not in found_videos[video_id]["search_queries"]:
                found_videos[video_id]["search_queries"].append(query)

    return found_videos


# ==================================================
# RELEVANCE SCORING
# ==================================================

def calculate_relevance(title, description, search_queries):
    title_text = title.casefold()
    description_text = description.casefold()
    query_text = " ".join(search_queries).casefold()

    title_matches = []
    description_matches = []
    query_matches = []
    matched_categories = []

    for category, keywords in TOPIC_KEYWORDS.items():
        category_matched = False

        for keyword in keywords:
            term = keyword.casefold()

            if term in title_text:
                title_matches.append(term)
                category_matched = True

            elif term in description_text:
                description_matches.append(term)
                category_matched = True

            if term in query_text:
                query_matches.append(term)

        if category_matched:
            matched_categories.append(category)

    # Title matches carry the most weight.
    # Description and search query provide supporting evidence.
    score = (
        min(len(set(title_matches)), 2) * 35
        + min(len(set(description_matches)), 2) * 10
        + min(len(set(query_matches)), 1) * 10
    )

    score = min(score, 100)

    matched_terms = list(dict.fromkeys(
        title_matches + description_matches
    ))

    return {
        "relevance_score": score,
        "matched_categories": matched_categories,
        "matched_terms": matched_terms,
        "is_relevant": score >= RELEVANCE_THRESHOLD
    }


# ==================================================
# VIDEO DETAILS
# ==================================================

def get_video_details(youtube, found_videos):
    video_ids = list(found_videos.keys())

    if not video_ids:
        return []

    results = []

    # YouTube videos.list accepts up to 50 IDs per request.
    for start in range(0, len(video_ids), 50):
        batch_ids = video_ids[start:start + 50]

        response = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(batch_ids),
            maxResults=50
        ).execute()

        now = datetime.now(timezone.utc)

        for video in response.get("items", []):
            video_id = video["id"]

            snippet = video.get("snippet", {})
            statistics = video.get("statistics", {})
            details = video.get("contentDetails", {})

            search_data = found_videos[video_id]

            title = snippet.get("title", "")
            description = snippet.get("description", "")

            relevance = calculate_relevance(
                title,
                description,
                search_data["search_queries"]
            )

            published_at = snippet.get("publishedAt", "")

            try:
                published_date = datetime.fromisoformat(
                    published_at.replace("Z", "+00:00")
                )

                days_old = max(
                    (now - published_date).total_seconds() / 86400,
                    1
                )

            except (ValueError, TypeError):
                days_old = None

            views = int(statistics.get("viewCount", 0))

            likes_value = statistics.get("likeCount")
            comments_value = statistics.get("commentCount")

            likes = (
                int(likes_value)
                if likes_value is not None else None
            )

            comments = (
                int(comments_value)
                if comments_value is not None else None
            )

            duration = details.get("duration", "")
            duration_seconds = parse_duration(duration)

            views_per_day = (
                round(views / days_old, 2)
                if days_old is not None else None
            )

            if (
                likes is not None
                and comments is not None
                and views > 0
            ):
                engagement_rate = round(
                    ((likes + comments) / views) * 100,
                    3
                )
            else:
                engagement_rate = None

            results.append({
                "video_id": video_id,
                "title": title,
                "channel_name": snippet.get("channelTitle", ""),
                "published_at": published_at,
                "views": views,
                "likes": likes,
                "comments": comments,
                "engagement_rate_percent": engagement_rate,
                "duration": duration,
                "duration_seconds": duration_seconds,
                "format_category": classify_format(duration_seconds),
                "days_since_upload": (
                    round(days_old, 1)
                    if days_old is not None else None
                ),
                "views_per_day": views_per_day,
                "relevance_score": relevance["relevance_score"],
                "matched_categories": ", ".join(
                    relevance["matched_categories"]
                ),
                "matched_terms": ", ".join(
                    relevance["matched_terms"]
                ),
                "search_queries": " | ".join(
                    search_data["search_queries"]
                ),
                "video_url": (
                    f"https://www.youtube.com/watch?v={video_id}"
                )
            })

    return results


# ==================================================
# SAVE REPORTS
# ==================================================

FIELDNAMES = [
    "video_id",
    "title",
    "channel_name",
    "published_at",
    "views",
    "likes",
    "comments",
    "engagement_rate_percent",
    "duration",
    "duration_seconds",
    "format_category",
    "days_since_upload",
    "views_per_day",
    "relevance_score",
    "matched_categories",
    "matched_terms",
    "search_queries",
    "video_url"
]


def save_csv(path, videos):
    with open(
        path,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=FIELDNAMES
        )

        writer.writeheader()
        writer.writerows(videos)


def save_results(all_results, relevant_results, queries):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    short_candidates = [
        video for video in relevant_results
        if video["format_category"] == "short_candidate"
    ]

    long_form = [
        video for video in relevant_results
        if video["format_category"] == "long_form"
    ]

    # Sort by relevance first, then historical views per day.
    sort_key = lambda video: (
        video["relevance_score"],
        video["views_per_day"] or 0
    )

    relevant_results.sort(key=sort_key, reverse=True)
    short_candidates.sort(key=sort_key, reverse=True)
    long_form.sort(key=sort_key, reverse=True)

    report = {
        "generated_at": datetime.now().isoformat(),
        "search_queries": queries,
        "videos_found_before_filtering": len(all_results),
        "relevant_videos": len(relevant_results),
        "filtered_out_videos": (
            len(all_results) - len(relevant_results)
        ),
        "short_candidates": len(short_candidates),
        "long_form_videos": len(long_form),
        "relevance_threshold": RELEVANCE_THRESHOLD,
        "notes": [
            "Relevance score is a keyword-based estimate, not AI fact-checking.",
            "Views per day is a historical average, not a future prediction.",
            "Short candidates are duration-based and are not confirmed Shorts.",
            "Hidden like or comment counts may be unavailable."
        ],
        "videos": relevant_results
    }

    json_file = OUTPUT_DIR / f"youtube_research_v21_{timestamp}.json"
    csv_file = OUTPUT_DIR / f"youtube_research_v21_{timestamp}.csv"

    short_file = OUTPUT_DIR / f"short_candidates_{timestamp}.csv"
    long_file = OUTPUT_DIR / f"long_form_{timestamp}.csv"

    latest_json = OUTPUT_DIR / "latest_youtube_research_v21.json"
    latest_csv = OUTPUT_DIR / "latest_youtube_research_v21.csv"

    latest_short = OUTPUT_DIR / "latest_short_candidates.csv"
    latest_long = OUTPUT_DIR / "latest_long_form.csv"

    for path in (json_file, latest_json):
        with open(path, "w", encoding="utf-8") as file:
            json.dump(report, file, ensure_ascii=False, indent=2)

    save_csv(csv_file, relevant_results)
    save_csv(latest_csv, relevant_results)

    save_csv(short_file, short_candidates)
    save_csv(latest_short, short_candidates)

    save_csv(long_file, long_form)
    save_csv(latest_long, long_form)

    return {
        "json": json_file,
        "csv": csv_file,
        "short": short_file,
        "long": long_file
    }, short_candidates, long_form


# ==================================================
# MAIN
# ==================================================

def main():
    print("=" * 60)
    print("YOUTUBE RESEARCH ENGINE V2.1")
    print("=" * 60)

    api_key, config = load_settings()

    print("Channel:", config["channel"]["name"])

    queries = get_search_queries(config)

    print("Search queries:", len(queries))
    print("Results per query:", RESULTS_PER_QUERY)

    youtube = build(
        "youtube",
        "v3",
        developerKey=api_key,
        cache_discovery=False
    )

    found_videos = search_videos(youtube, queries)

    print("\nUnique videos found:", len(found_videos))

    all_results = get_video_details(youtube, found_videos)

    relevant_results = [
        video for video in all_results
        if video["relevance_score"] >= RELEVANCE_THRESHOLD
    ]

    files, short_candidates, long_form = save_results(
        all_results,
        relevant_results,
        queries
    )

    print("\n" + "=" * 60)
    print("RESEARCH FILTER SUMMARY")
    print("=" * 60)

    print("Videos collected:", len(all_results))
    print("Relevant videos:", len(relevant_results))
    print("Filtered out:", len(all_results) - len(relevant_results))
    print("Short candidates:", len(short_candidates))
    print("Long-form videos:", len(long_form))

    print("\nTOP 10 RELEVANT VIDEOS")

    for index, video in enumerate(relevant_results[:10], start=1):
        print(f"\n{index}. {video['title']}")
        print("   Channel:", video["channel_name"])
        print("   Views:", f"{video['views']:,}")
        print("   Views/day:", video["views_per_day"])
        print("   Relevance:", video["relevance_score"], "/100")
        print("   Category:", video["matched_categories"])
        print("   Format:", video["format_category"])

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

    except HttpError as error:
        print("\nYOUTUBE API ERROR:")
        print(error)

    except Exception as error:
        print("\nRESEARCH ENGINE ERROR:")
        print(type(error).__name__ + ":", error)
