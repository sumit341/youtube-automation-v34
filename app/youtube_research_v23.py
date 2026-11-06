
import csv
import json
import os
import re
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from dotenv import load_dotenv
from googleapiclient.discovery import build


ROOT = Path(r"G:\youtube automation")
CONFIG_FILE = ROOT / "config" / "channel.yaml"
RESEARCH_DIR = ROOT / "data" / "research"
ENV_FILE = Path.home() / "youtube-automation-runtime" / ".env"

CATEGORIES = {
    "Human Psychology": {
        "query": "human psychology Hindi",
        "terms": ["psychology", "human behavior", "human behaviour",
                  "mindset", "brain", "emotions", "habits",
                  "मनोविज्ञान", "व्यवहार"],
        "topics": [
            "Why do people make emotional decisions even when they know better?",
            "The hidden psychology behind everyday human behaviour"
        ]
    },
    "Money Psychology": {
        "query": "money psychology Hindi",
        "terms": ["money", "finance", "financial", "spending",
                  "saving", "wealth", "rich", "poor", "income",
                  "पैसा", "अमीर", "गरीब", "बचत"],
        "topics": [
            "Rich vs Poor: How everyday money decisions shape the future",
            "Why a higher income does not always create financial freedom"
        ]
    },
    "Power Dynamics": {
        "query": "power influence human psychology Hindi",
        "terms": ["power", "influence", "authority", "control",
                  "leadership", "status", "manipulation",
                  "शक्ति", "प्रभाव", "नेतृत्व"],
        "topics": [
            "How emotional control influences power dynamics",
            "Why influence is not always about authority"
        ]
    },
    "Success": {
        "query": "success habits mindset Hindi",
        "terms": ["success", "discipline", "productivity",
                  "motivation", "consistency", "goals",
                  "सफलता", "अनुशासन", "आदत"],
        "topics": [
            "Why delayed gratification is harder than it looks",
            "How instant gratification affects long-term success"
        ]
    },
    "Social Comparison": {
        "query": "social comparison lifestyle psychology Hindi",
        "terms": ["comparison", "social status", "lifestyle",
                  "jealousy", "friends", "society", "validation",
                  "तुलना", "दिखावा", "समाज"],
        "topics": [
            "Why seeing other people's lifestyle changes our spending",
            "The hidden cost of comparing your progress with friends"
        ]
    }
}


def parse_duration(value):
    match = re.fullmatch(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        value or ""
    )
    if not match:
        return 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def median_or_zero(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values), 2) if values else 0


def percentile_ranks(values):
    if not values:
        return []

    ordered = sorted(values)
    if len(ordered) == 1:
        return [50.0]

    return [
        round(
            (sum(1 for item in ordered if item <= value) - 1)
            / (len(ordered) - 1) * 100,
            2
        )
        for value in values
    ]


def load_configuration():
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Config missing: {CONFIG_FILE}")

    with CONFIG_FILE.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def get_youtube_client():
    load_dotenv(ENV_FILE)
    api_key = os.getenv("YOUTUBE_API_KEY")

    if not api_key:
        raise RuntimeError(
            "YOUTUBE_API_KEY nahi mili. Runtime .env check karein."
        )

    return build(
        "youtube",
        "v3",
        developerKey=api_key,
        cache_discovery=False
    )


def search_category(youtube, category_name, category_data, published_after):
    results = []

    search_modes = [
        ("recent", "date", published_after),
        ("high_views", "viewCount", None)
    ]

    for research_type, order, date_filter in search_modes:
        params = {
            "part": "snippet",
            "q": category_data["query"],
            "type": "video",
            "maxResults": 10,
            "order": order,
            "regionCode": "IN",
            "relevanceLanguage": "hi",
            "safeSearch": "moderate"
        }

        if date_filter:
            params["publishedAfter"] = date_filter

        response = youtube.search().list(**params).execute()

        for item in response.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})

            if not video_id:
                continue

            results.append({
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "channel_name": snippet.get("channelTitle", ""),
                "channel_id": snippet.get("channelId", ""),
                "published_at": snippet.get("publishedAt", ""),
                "category": category_name,
                "research_type": research_type
            })

    return results


def calculate_relevance(title, description, terms):
    title_text = (title or "").lower()
    description_text = (description or "").lower()

    title_matches = sorted({
        term for term in terms if term.lower() in title_text
    })
    description_matches = sorted({
        term for term in terms if term.lower() in description_text
    })

    score = min(len(title_matches), 3) * 25
    score += min(len(description_matches), 3) * 10

    return min(score, 100), title_matches, description_matches


def enrich_videos(youtube, raw_results):
    unique = {}

    for item in raw_results:
        video_id = item["video_id"]

        if video_id not in unique:
            unique[video_id] = item

    ids = list(unique.keys())
    details = {}

    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]

        response = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(batch)
        ).execute()

        for video in response.get("items", []):
            details[video["id"]] = video

    enriched = []
    now = datetime.now(timezone.utc)

    for video_id, original in unique.items():
        video = details.get(video_id)
        if not video:
            continue

        snippet = video.get("snippet", {})
        stats = video.get("statistics", {})
        content = video.get("contentDetails", {})

        title = snippet.get("title", original["title"])
        description = snippet.get("description", original["description"])

        matched_categories = []
        all_matched_terms = []
        relevance_scores = []

        for category_name, category_data in CATEGORIES.items():
            score, title_matches, description_matches = calculate_relevance(
                title, description, category_data["terms"]
            )

            if score >= 25:
                matched_categories.append(category_name)
                relevance_scores.append(score)
                all_matched_terms.extend(title_matches)
                all_matched_terms.extend(description_matches)

        if not matched_categories:
            continue

        views = int(stats.get("viewCount", 0))
        likes = int(stats.get("likeCount", 0))
        comments = int(stats.get("commentCount", 0))

        published_at = snippet.get(
            "publishedAt", original["published_at"]
        )

        try:
            published = datetime.fromisoformat(
                published_at.replace("Z", "+00:00")
            )
            age_days = max(
                (now - published).total_seconds() / 86400, 1
            )
        except (ValueError, TypeError):
            age_days = 1

        duration = content.get("duration", "")
        duration_seconds = parse_duration(duration)

        engagement = (
            round((likes + comments) / views * 100, 3)
            if views > 0 else 0
        )

        enriched.append({
            "video_id": video_id,
            "title": title,
            "channel_name": snippet.get(
                "channelTitle", original["channel_name"]
            ),
            "channel_id": snippet.get(
                "channelId", original["channel_id"]
            ),
            "published_at": published_at,
            "views": views,
            "likes": likes,
            "comments": comments,
            "engagement_rate_percent": engagement,
            "duration": duration,
            "duration_seconds": duration_seconds,
            "format_category": (
                "short_candidate" if duration_seconds <= 180
                else "long_form"
            ),
            "days_since_upload": round(age_days, 1),
            "views_per_day": round(views / age_days, 2),
            "relevance_score": max(relevance_scores),
            "matched_categories": matched_categories,
            "matched_terms": sorted(set(all_matched_terms)),
            "research_type": original["research_type"],
            "video_url": f"https://www.youtube.com/watch?v={video_id}"
        })

    return enriched


def build_category_analysis(videos):
    analysis = []

    for category_name in CATEGORIES:
        category_videos = [
            video for video in videos
            if category_name in video["matched_categories"]
        ]

        analysis.append({
            "category": category_name,
            "video_count": len(category_videos),
            "recent_video_count": sum(
                1 for v in category_videos
                if v["research_type"] in ("recent", "recent_and_high_views")
            ),
            "median_views": median_or_zero(
                [v["views"] for v in category_videos]
            ),
            "median_views_per_day": median_or_zero(
                [v["views_per_day"] for v in category_videos]
            ),
            "median_engagement_percent": median_or_zero(
                [v["engagement_rate_percent"] for v in category_videos]
            ),
            "short_candidate_count": sum(
                1 for v in category_videos
                if v["format_category"] == "short_candidate"
            ),
            "long_form_count": sum(
                1 for v in category_videos
                if v["format_category"] == "long_form"
            )
        })

    demand_values = [
        row["median_views_per_day"] for row in analysis
    ]
    demand_ranks = percentile_ranks(demand_values)

    for index, row in enumerate(analysis):
        row["relative_demand_percentile"] = demand_ranks[index]

        sample_penalty = min(row["video_count"] * 5, 30)
        row["research_opportunity_signal"] = round(
            demand_ranks[index] * 0.8
            + (30 - sample_penalty) * 0.2,
            2
        )

    return sorted(
        analysis,
        key=lambda row: row["research_opportunity_signal"],
        reverse=True
    )


def build_topic_candidates(category_analysis):
    category_map = {
        row["category"]: row for row in category_analysis
    }
    candidates = []

    for category_name, category_data in CATEGORIES.items():
        evidence = category_map[category_name]

        for topic in category_data["topics"]:
            candidates.append({
                "topic": topic,
                "category": category_name,
                "evidence_video_count": evidence["video_count"],
                "median_views_per_day": evidence["median_views_per_day"],
                "recent_video_count": evidence["recent_video_count"],
                "relative_demand_percentile": evidence[
                    "relative_demand_percentile"
                ],
                "research_opportunity_signal": evidence[
                    "research_opportunity_signal"
                ]
            })

    candidates.sort(
        key=lambda row: (
            row["research_opportunity_signal"],
            row["recent_video_count"],
            row["median_views_per_day"]
        ),
        reverse=True
    )

    return candidates[:10]


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields = list(rows[0].keys())

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

    config = load_configuration()
    youtube = get_youtube_client()

    now = datetime.now(timezone.utc)
    published_after = (
        now - timedelta(days=180)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")

    print("\nYOUTUBE RESEARCH ENGINE V2.3", flush=True)
    print("=" * 48, flush=True)
    print("Recent window: last 180 days", flush=True)
    print("Categories:", len(CATEGORIES), flush=True)
    print("Search requests: maximum 10\n", flush=True)

    raw_results = []

    for category_name, category_data in CATEGORIES.items():
        print(f"Searching: {category_name}", flush=True)

        results = search_category(
            youtube, category_name, category_data, published_after
        )
        raw_results.extend(results)

    print("\nSearch collection complete.", flush=True)
    print("Raw search results:", len(raw_results), flush=True)

    videos = enrich_videos(youtube, raw_results)
    category_analysis = build_category_analysis(videos)
    topic_candidates = build_topic_candidates(category_analysis)

    short_videos = [
        v for v in videos if v["format_category"] == "short_candidate"
    ]
    long_videos = [
        v for v in videos if v["format_category"] == "long_form"
    ]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report = {
        "engine": "YouTube Research Engine V2.3",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "channel_name": config.get("channel", {}).get("name", ""),
        "research_window_days": 180,
        "search_requests_maximum": 10,
        "total_unique_relevant_videos": len(videos),
        "short_candidate_count": len(short_videos),
        "long_form_count": len(long_videos),
        "category_analysis": category_analysis,
        "top_10_topic_candidates": topic_candidates,
        "videos": videos,
        "methodology_notes": [
            "Recent search covers the last 180 days.",
            "High-view search is a separate lifetime view-count search.",
            "Duplicate video IDs are merged.",
            "Relevance uses title and description matches.",
            "Short candidate means duration is 180 seconds or less; it does not confirm YouTube Shorts eligibility.",
            "Views per day is a historical average, not real-time velocity.",
            "Opportunity signal is a small-sample heuristic, not a competition measurement.",
            "Public engagement does not reveal audience retention or subscriber conversion."
        ]
    }

    files = {
        "json": RESEARCH_DIR / f"youtube_research_v23_{timestamp}.json",
        "videos": RESEARCH_DIR / f"youtube_research_v23_{timestamp}.csv",
        "categories": RESEARCH_DIR / f"category_analysis_v23_{timestamp}.csv",
        "topics": RESEARCH_DIR / f"top10_topic_candidates_v23_{timestamp}.csv",
        "shorts": RESEARCH_DIR / f"short_candidates_v23_{timestamp}.csv",
        "long": RESEARCH_DIR / f"long_form_v23_{timestamp}.csv"
    }

    files["json"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    write_csv(files["videos"], videos)
    write_csv(files["categories"], category_analysis)
    write_csv(files["topics"], topic_candidates)
    write_csv(files["shorts"], short_videos)
    write_csv(files["long"], long_videos)

    latest_names = {
        "json": "latest_youtube_research_v23.json",
        "videos": "latest_youtube_research_v23.csv",
        "categories": "latest_category_analysis_v23.csv",
        "topics": "latest_top10_topic_candidates_v23.csv",
        "shorts": "latest_short_candidates_v23.csv",
        "long": "latest_long_form_v23.csv"
    }

    for key, source in files.items():
        destination = RESEARCH_DIR / latest_names[key]
        destination.write_bytes(source.read_bytes())

    print("\n" + "=" * 48)
    print("V2.3 RESEARCH SUMMARY")
    print("=" * 48)
    print("Relevant unique videos:", len(videos))
    print("Short candidates:", len(short_videos))
    print("Long-form videos:", len(long_videos))

    print("\nCATEGORY RANKING")
    for index, row in enumerate(category_analysis, start=1):
        print(
            f"{index}. {row['category']} | "
            f"Videos: {row['video_count']} | "
            f"Median views/day: {row['median_views_per_day']} | "
            f"Recent: {row['recent_video_count']} | "
            f"Opportunity signal: {row['research_opportunity_signal']}"
        )

    print("\nTOP 10 TOPIC CANDIDATES")
    for index, row in enumerate(topic_candidates, start=1):
        print(
            f"{index}. {row['topic']} "
            f"[{row['category']}] | "
            f"Evidence: {row['evidence_video_count']} videos"
        )

    print("\nOUTPUT FILES")
    for path in files.values():
        print(path)

    print("\nSTATUS: SUCCESS", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            "\nRESEARCH ENGINE ERROR:",
            type(error).__name__,
            str(error),
            flush=True
        )
        raise
