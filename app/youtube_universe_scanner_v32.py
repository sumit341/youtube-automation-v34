import os
import re
import json
import csv
import math
import sqlite3
import argparse

from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ============================================================
# YOUTUBE UNIVERSE SCANNER V3.2
# CLEAN VERSION
# CHECKPOINT + RESUME + QUOTA CONTROL
# FORMAT + RELEVANCE + PERFORMANCE ANALYSIS
# ============================================================

ROOT = Path(r"G:\youtube automation")

RUNTIME_ENV = (
    Path.home()
    / "youtube-automation-runtime"
    / ".env"
)

OUTPUT_DIR = (
    ROOT / "data" / "research" / "youtube_universe_v32"
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DATABASE = OUTPUT_DIR / "youtube_universe.db"

MAX_PAGES_PER_SEARCH = 2
RESULTS_PER_PAGE = 50
RECENT_DAYS = 365

DEFAULT_SEARCH_LIMIT = 10
DEFAULT_DETAIL_LIMIT = 10


# ============================================================
# CATEGORY CONFIGURATION
# ============================================================

CATEGORIES = {
    "Human Psychology": {
        "queries": {
            "Hindi": ["human psychology Hindi"],
            "Hinglish": [
                "insani behaviour psychology",
                "human behaviour facts Hindi"
            ],
            "English": ["human psychology behavior"]
        },
        "terms": [
            "psychology", "human psychology",
            "human behavior", "human behaviour",
            "mind", "brain", "emotions",
            "behavior", "behaviour", "personality",
            "habits", "overthinking", "subconscious",
            "mental", "people", "human nature",
            "मानसिक", "मनोविज्ञान", "व्यवहार"
        ]
    },

    "Money Psychology": {
        "queries": {
            "Hindi": ["money psychology Hindi"],
            "Hinglish": [
                "paise ki psychology",
                "money mindset Hindi"
            ],
            "English": [
                "money psychology personal finance behavior"
            ]
        },
        "terms": [
            "money", "wealth", "finance", "financial",
            "rich", "poor", "spending", "saving",
            "investing", "income", "greed",
            "money mindset", "financial psychology",
            "wealth psychology", "poverty",
            "पैसा", "अमीर", "गरीब", "दौलत"
        ]
    },

    "Power Dynamics": {
        "queries": {
            "Hindi": ["power dynamics psychology Hindi"],
            "Hinglish": [
                "influence power psychology",
                "social power dynamics Hindi"
            ],
            "English": ["power dynamics influence psychology"]
        },
        "terms": [
            "power", "influence", "authority",
            "dominance", "persuasion", "control",
            "manipulation", "leadership", "status",
            "social power", "respect", "negotiation",
            "शक्ति", "प्रभाव", "नेतृत्व"
        ]
    },

    "Success": {
        "queries": {
            "Hindi": ["success habits mindset Hindi"],
            "Hinglish": [
                "success mindset habits Hindi",
                "discipline productivity Hindi"
            ],
            "English": ["success psychology habits"]
        },
        "terms": [
            "success", "mindset", "discipline",
            "motivation", "productivity", "goals",
            "growth", "achievement", "focus",
            "consistency", "self improvement",
            "personal development",
            "सफलता", "आदत", "अनुशासन"
        ]
    },

    "Social Comparison": {
        "queries": {
            "Hindi": ["social comparison psychology Hindi"],
            "Hinglish": [
                "dusron se comparison psychology",
                "social status lifestyle Hindi"
            ],
            "English": ["social comparison psychology lifestyle"]
        },
        "terms": [
            "comparison", "social status", "lifestyle",
            "jealousy", "envy", "peer pressure",
            "social media", "self worth", "status",
            "social comparison", "validation",
            "दिखावा", "जलन", "तुलना"
        ]
    }
}


# ============================================================
# COMMON HELPERS
# ============================================================

def log(*args):
    print(*args, flush=True)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_int(value):
    try:
        return int(value or 0)
    except (ValueError, TypeError):
        return 0


def safe_float(value):
    try:
        return float(value or 0)
    except (ValueError, TypeError):
        return 0.0


def safe_json_list(value):
    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) else []
    except (ValueError, TypeError):
        return []


def parse_duration(value):
    if not value:
        return 0

    match = re.fullmatch(
        r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
        value
    )

    if not match:
        return 0

    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)

    return hours * 3600 + minutes * 60 + seconds


def parse_date(value):
    if not value:
        return None

    try:
        result = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)

        return result

    except (ValueError, TypeError):
        return None


def load_api_key():
    if not RUNTIME_ENV.exists():
        raise FileNotFoundError(
            f"Runtime .env not found: {RUNTIME_ENV}"
        )

    load_dotenv(RUNTIME_ENV)

    key = os.getenv("YOUTUBE_API_KEY")

    if not key:
        raise ValueError(
            "YOUTUBE_API_KEY missing in runtime .env"
        )

    return key


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return

    fields = list(rows[0].keys())

    with path.open(
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


def save_json(path, data):
    path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


# ============================================================
# FORMAT CLASSIFICATION
# ============================================================

def classify_format(duration):
    duration = safe_int(duration)

    if duration <= 0:
        return "UNKNOWN"

    if duration <= 60:
        return "SHORTS_CANDIDATE"

    if duration <= 180:
        return "SHORT_FORM"

    if duration <= 480:
        return "MEDIUM_FORM"

    if duration <= 3600:
        return "DOCUMENTARY"

    return "AUDIOBOOK_OR_VERY_LONG"


def short_suitability(duration):
    duration = safe_int(duration)

    if duration <= 0:
        return 0

    if duration <= 60:
        return 100

    if duration <= 180:
        return 75

    if duration <= 480:
        return 20

    return 0


def short_form_suitability(duration):
    duration = safe_int(duration)

    if duration <= 0:
        return 0

    if duration <= 60:
        return 75

    if duration <= 180:
        return 100

    if duration <= 480:
        return 55

    return 0


def documentary_suitability(duration):
    duration = safe_int(duration)

    if duration <= 0:
        return 0

    if duration <= 60:
        return 0

    if duration <= 180:
        return 15

    if duration <= 480:
        return 65

    if duration <= 3600:
        return 100

    return 80


# ============================================================
# SCORING ENGINE
# ============================================================

def calculate_relevance(title, description, category):
    title_text = (title or "").lower()

    full_text = (
        (title or "") + " " + (description or "")
    ).lower()

    terms = CATEGORIES[category]["terms"]

    matched = []
    score = 0

    for term in terms:
        term_lower = term.lower()

        if term_lower in full_text:
            matched.append(term)

            if term_lower in title_text:
                score += 3
            else:
                score += 1

    if len(matched) >= 5:
        score += 3
    elif len(matched) >= 3:
        score += 2
    elif len(matched) >= 1:
        score += 1

    if score >= 5:
        status = "RELEVANT_CANDIDATE"
    elif score >= 2:
        status = "REVIEW"
    else:
        status = "LOW_RELEVANCE"

    relevance_percent = min(100, score * 5)

    return {
        "score": score,
        "relevance_percent": relevance_percent,
        "status": status,
        "matched_terms": matched
    }


def calculate_performance_score(views, views_per_day, engagement):
    views = max(0, safe_int(views))
    views_per_day = max(0, safe_float(views_per_day))
    engagement = max(0, safe_float(engagement))

    velocity_score = min(
        50,
        math.log10(views_per_day + 1) * 12
    )

    total_views_score = min(
        25,
        math.log10(views + 1) * 5
    )

    engagement_score = min(
        25,
        engagement * 5
    )

    return round(
        velocity_score
        + total_views_score
        + engagement_score,
        2
    )


# ============================================================
# DATABASE
# ============================================================

def connect_database():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row

    # Existing V3.1/V3.2-compatible schema.
    # CREATE IF NOT EXISTS preserves existing saved data.

    connection.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            channel_id TEXT,
            channel_name TEXT,
            published_at TEXT,
            duration_seconds INTEGER DEFAULT 0,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            views_per_day REAL DEFAULT 0,
            engagement_rate REAL DEFAULT 0,
            category_matches TEXT,
            languages TEXT,
            search_queries TEXT,
            relevance_score INTEGER DEFAULT 0,
            relevance_status TEXT,
            first_seen_at TEXT,
            last_seen_at TEXT,
            scan_count INTEGER DEFAULT 1
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS search_pages (
            job_key TEXT NOT NULL,
            page_num INTEGER NOT NULL,
            job_json TEXT NOT NULL,
            page_token TEXT,
            next_page_token TEXT,
            raw_count INTEGER DEFAULT 0,
            response_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (job_key, page_num)
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS discovered_videos (
            video_id TEXT PRIMARY KEY,
            categories TEXT NOT NULL,
            languages TEXT NOT NULL,
            search_queries TEXT NOT NULL,
            first_discovered_at TEXT NOT NULL,
            last_discovered_at TEXT NOT NULL
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS scan_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT,
            completed_at TEXT,
            search_calls INTEGER DEFAULT 0,
            detail_calls INTEGER DEFAULT 0,
            discovered_total INTEGER DEFAULT 0,
            database_total INTEGER DEFAULT 0,
            status TEXT
        )
    """)

    connection.commit()

    return connection


# ============================================================
# SEARCH JOBS
# ============================================================

def build_jobs():
    jobs = []

    for category, data in CATEGORIES.items():
        for language, queries in data["queries"].items():
            for query in queries:
                for mode in ("recent", "popular"):

                    job = {
                        "category": category,
                        "language": language,
                        "query": query,
                        "mode": mode
                    }

                    job["job_key"] = "|".join([
                        category,
                        language,
                        mode,
                        query
                    ])

                    jobs.append(job)

    return jobs


def search_youtube(youtube, job, page_token=None):
    args = {
        "part": "snippet",
        "q": job["query"],
        "type": "video",
        "maxResults": RESULTS_PER_PAGE,
        "order": (
            "date"
            if job["mode"] == "recent"
            else "viewCount"
        ),
        "safeSearch": "moderate"
    }

    if job["mode"] == "recent":
        published_after = (
            datetime.now(timezone.utc)
            - timedelta(days=RECENT_DAYS)
        )

        args["publishedAfter"] = (
            published_after.isoformat().replace(
                "+00:00", "Z"
            )
        )

    if page_token:
        args["pageToken"] = page_token

    return youtube.search().list(**args).execute()


# ============================================================
# DISCOVERY CHECKPOINTS
# ============================================================

def merge_discovered_video(connection, video_id, job):
    row = connection.execute("""
        SELECT categories, languages, search_queries,
               first_discovered_at
        FROM discovered_videos
        WHERE video_id = ?
    """, (video_id,)).fetchone()

    now = utc_now()

    if row:
        categories = set(
            safe_json_list(row["categories"])
        )

        languages = set(
            safe_json_list(row["languages"])
        )

        queries = safe_json_list(
            row["search_queries"]
        )

        first_seen = row["first_discovered_at"]

    else:
        categories = set()
        languages = set()
        queries = []
        first_seen = now

    categories.add(job["category"])
    languages.add(job["language"])

    if job["query"] not in queries:
        queries.append(job["query"])

    connection.execute("""
        INSERT OR REPLACE INTO discovered_videos (
            video_id,
            categories,
            languages,
            search_queries,
            first_discovered_at,
            last_discovered_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        video_id,
        json.dumps(sorted(categories), ensure_ascii=False),
        json.dumps(sorted(languages), ensure_ascii=False),
        json.dumps(queries[-100:], ensure_ascii=False),
        first_seen,
        now
    ))


def save_search_page(
    connection,
    job,
    job_key,
    page_num,
    page_token,
    response
):
    items = response.get("items", [])

    next_token = response.get(
        "nextPageToken", ""
    )

    connection.execute("""
        INSERT OR REPLACE INTO search_pages (
            job_key,
            page_num,
            job_json,
            page_token,
            next_page_token,
            raw_count,
            response_json,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job_key,
        page_num,
        json.dumps(job, ensure_ascii=False),
        page_token or "",
        next_token or "",
        len(items),
        json.dumps(response, ensure_ascii=False),
        utc_now()
    ))

    for item in items:
        video_id = item.get(
            "id", {}
        ).get("videoId")

        if video_id:
            merge_discovered_video(
                connection,
                video_id,
                job
            )

    connection.commit()

    return len(items), next_token


def get_saved_page(connection, job_key, page_num):
    return connection.execute("""
        SELECT next_page_token
        FROM search_pages
        WHERE job_key = ? AND page_num = ?
    """, (
        job_key,
        page_num
    )).fetchone()


def get_discovered(connection):
    rows = connection.execute("""
        SELECT video_id, categories, languages,
               search_queries
        FROM discovered_videos
        ORDER BY video_id
    """).fetchall()

    result = {}

    for row in rows:
        result[row["video_id"]] = {
            "categories": safe_json_list(
                row["categories"]
            ),
            "languages": safe_json_list(
                row["languages"]
            ),
            "queries": safe_json_list(
                row["search_queries"]
            )
        }

    return result


# ============================================================
# VIDEO DETAIL RECORD
# ============================================================

def make_video_record(video_id, item, metadata):
    snippet = item.get("snippet", {})
    stats = item.get("statistics", {})
    content = item.get("contentDetails", {})

    title = snippet.get("title", "")
    description = snippet.get("description", "")

    categories = metadata["categories"]

    best_score = 0
    best_status = "LOW_RELEVANCE"

    for category in categories:
        if category not in CATEGORIES:
            continue

        result = calculate_relevance(
            title,
            description,
            category
        )

        if result["score"] > best_score:
            best_score = result["score"]
            best_status = result["status"]

    views = safe_int(stats.get("viewCount"))
    likes = safe_int(stats.get("likeCount"))
    comments = safe_int(stats.get("commentCount"))

    published_at = snippet.get("publishedAt", "")
    published_date = parse_date(published_at)

    if published_date:
        age_days = max(
            (
                datetime.now(timezone.utc)
                - published_date
            ).total_seconds() / 86400,
            1
        )
    else:
        age_days = 1

    views_per_day = round(
        views / age_days,
        2
    )

    engagement_rate = (
        round(
            ((likes + comments) / views) * 100,
            2
        )
        if views > 0 else 0
    )

    return {
        "video_id": video_id,
        "title": title,
        "description": description,
        "channel_id": snippet.get("channelId", ""),
        "channel_name": snippet.get("channelTitle", ""),
        "published_at": published_at,
        "duration_seconds": parse_duration(
            content.get("duration", "")
        ),
        "views": views,
        "likes": likes,
        "comments": comments,
        "views_per_day": views_per_day,
        "engagement_rate": engagement_rate,
        "category_matches": categories,
        "languages": metadata["languages"],
        "search_queries": metadata["queries"],
        "relevance_score": best_score,
        "relevance_status": best_status,
        "video_url": (
            f"https://www.youtube.com/watch?v={video_id}"
        )
    }


# ============================================================
# DATABASE SAVE
# ============================================================

def save_video(connection, video):
    existing = connection.execute("""
        SELECT category_matches, languages,
               search_queries, first_seen_at, scan_count
        FROM videos
        WHERE video_id = ?
    """, (
        video["video_id"],
    )).fetchone()

    now = utc_now()

    if existing:
        categories = set(
            safe_json_list(existing["category_matches"])
        )

        languages = set(
            safe_json_list(existing["languages"])
        )

        queries = safe_json_list(
            existing["search_queries"]
        )

        first_seen = existing["first_seen_at"]

        scan_count = (
            safe_int(existing["scan_count"]) + 1
        )

    else:
        categories = set()
        languages = set()
        queries = []
        first_seen = now
        scan_count = 1

    categories.update(video["category_matches"])
    languages.update(video["languages"])

    for query in video["search_queries"]:
        if query not in queries:
            queries.append(query)

    connection.execute("""
        INSERT OR REPLACE INTO videos (
            video_id,
            title,
            description,
            channel_id,
            channel_name,
            published_at,
            duration_seconds,
            views,
            likes,
            comments,
            views_per_day,
            engagement_rate,
            category_matches,
            languages,
            search_queries,
            relevance_score,
            relevance_status,
            first_seen_at,
            last_seen_at,
            scan_count
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
    """, (
        video["video_id"],
        video["title"],
        video["description"],
        video["channel_id"],
        video["channel_name"],
        video["published_at"],
        video["duration_seconds"],
        video["views"],
        video["likes"],
        video["comments"],
        video["views_per_day"],
        video["engagement_rate"],
        json.dumps(
            sorted(categories),
            ensure_ascii=False
        ),
        json.dumps(
            sorted(languages),
            ensure_ascii=False
        ),
        json.dumps(
            queries[-100:],
            ensure_ascii=False
        ),
        video["relevance_score"],
        video["relevance_status"],
        first_seen,
        now,
        scan_count
    ))


def export_database(connection):
    rows = connection.execute("""
        SELECT *
        FROM videos
        ORDER BY views DESC
    """).fetchall()

    return [dict(row) for row in rows]


# ============================================================
# VIDEO ANALYSIS
# ============================================================

def prepare_video_exports(videos):
    output = []

    for original in videos:
        video = dict(original)

        duration = safe_int(
            video.get("duration_seconds")
        )

        views = safe_int(video.get("views"))

        views_per_day = safe_float(
            video.get("views_per_day")
        )

        engagement = safe_float(
            video.get("engagement_rate")
        )

        video["category_matches"] = safe_json_list(
            video.get("category_matches")
        )

        video["languages"] = safe_json_list(
            video.get("languages")
        )

        video["search_queries"] = safe_json_list(
            video.get("search_queries")
        )

        video["format_category"] = classify_format(
            duration
        )

        video["topic_relevance_score"] = min(
            100,
            safe_int(video.get("relevance_score")) * 5
        )

        video["performance_score"] = (
            calculate_performance_score(
                views,
                views_per_day,
                engagement
            )
        )

        video["shorts_suitability"] = (
            short_suitability(duration)
        )

        video["short_form_suitability"] = (
            short_form_suitability(duration)
        )

        video["documentary_suitability"] = (
            documentary_suitability(duration)
        )

        video["duration_minutes"] = round(
            duration / 60,
            2
        )

        video["video_url"] = (
            "https://www.youtube.com/watch?v="
            + video["video_id"]
        )

        output.append(video)

    return output


def median_value(values):
    clean = [
        safe_float(value)
        for value in values
        if value is not None
    ]

    if not clean:
        return 0

    clean.sort()

    middle = len(clean) // 2

    if len(clean) % 2:
        return round(clean[middle], 2)

    return round(
        (clean[middle - 1] + clean[middle]) / 2,
        2
    )


# ============================================================
# CATEGORY ANALYSIS
# ============================================================

def category_analysis(videos):
    results = []

    for category in CATEGORIES:
        selected = [
            video for video in videos
            if category in video.get(
                "category_matches", []
            )
        ]

        channels = {
            video.get("channel_id")
            for video in selected
            if video.get("channel_id")
        }

        results.append({
            "category": category,
            "video_count": len(selected),
            "unique_channels": len(channels),
            "median_views": median_value([
                video.get("views", 0)
                for video in selected
            ]),
            "median_views_per_day": median_value([
                video.get("views_per_day", 0)
                for video in selected
            ]),
            "median_performance_score": median_value([
                video.get("performance_score", 0)
                for video in selected
            ]),
            "median_documentary_suitability": median_value([
                video.get("documentary_suitability", 0)
                for video in selected
            ])
        })

    return results


# ============================================================
# CHANNEL ANALYSIS
# ============================================================

def channel_analysis(videos):
    groups = defaultdict(list)

    for video in videos:
        channel_id = video.get("channel_id")

        if channel_id:
            groups[channel_id].append(video)

    results = []

    for channel_id, items in groups.items():
        names = Counter(
            item.get("channel_name", "")
            for item in items
        )

        categories = sorted({
            category
            for item in items
            for category in item.get(
                "category_matches", []
            )
        })

        results.append({
            "channel_id": channel_id,
            "channel_name": (
                names.most_common(1)[0][0]
                if names else ""
            ),
            "video_count": len(items),
            "categories": categories,
            "median_views": median_value([
                item.get("views", 0)
                for item in items
            ]),
            "median_views_per_day": median_value([
                item.get("views_per_day", 0)
                for item in items
            ]),
            "median_performance_score": median_value([
                item.get("performance_score", 0)
                for item in items
            ])
        })

    return sorted(
        results,
        key=lambda row: (
            row["video_count"],
            row["median_performance_score"]
        ),
        reverse=True
    )


# ============================================================
# DURATION ANALYSIS
# ============================================================

def duration_analysis(videos):
    counts = Counter(
        video.get("format_category", "UNKNOWN")
        for video in videos
    )

    order = [
        "SHORTS_CANDIDATE",
        "SHORT_FORM",
        "MEDIUM_FORM",
        "DOCUMENTARY",
        "AUDIOBOOK_OR_VERY_LONG",
        "UNKNOWN"
    ]

    return [
        {
            "format": name,
            "video_count": counts.get(name, 0)
        }
        for name in order
    ]


# ============================================================
# REPORT GENERATION
# ============================================================

def generate_reports(
    connection,
    timestamp,
    started,
    search_calls,
    detail_calls,
    raw_results,
    discovered_count,
    saved_this_run,
    stop_reason
):
    all_videos = prepare_video_exports(
        export_database(connection)
    )

    current_videos = prepare_video_exports(
        saved_this_run
    )

    categories = category_analysis(all_videos)
    channels = channel_analysis(all_videos)
    formats = duration_analysis(all_videos)

    page_rows = connection.execute("""
        SELECT job_json, page_num, raw_count, created_at
        FROM search_pages
        ORDER BY job_key, page_num
    """).fetchall()

    search_audit = []

    for row in page_rows:
        job = json.loads(row["job_json"])

        search_audit.append({
            "category": job["category"],
            "language": job["language"],
            "query": job["query"],
            "mode": job["mode"],
            "page": row["page_num"],
            "results": row["raw_count"],
            "checkpoint_time": row["created_at"]
        })

    report = {
        "engine": "YouTube Universe Scanner V3.2",
        "generated_at": utc_now(),
        "started_at": started.isoformat(),
        "recent_window_days": RECENT_DAYS,

        "search_calls_this_run": search_calls,
        "detail_calls_this_run": detail_calls,

        "search_jobs_planned": len(build_jobs()),

        "raw_search_results_this_run": raw_results,
        "unique_discovered_total": discovered_count,

        "new_video_details_saved_this_run": len(
            saved_this_run
        ),

        "master_database_total": len(all_videos),

        "relevance_summary": {
            "relevant_candidates": sum(
                1 for video in all_videos
                if video.get("relevance_status")
                == "RELEVANT_CANDIDATE"
            ),
            "review": sum(
                1 for video in all_videos
                if video.get("relevance_status")
                == "REVIEW"
            ),
            "low_relevance": sum(
                1 for video in all_videos
                if video.get("relevance_status")
                == "LOW_RELEVANCE"
            )
        },

        "duration_analysis": formats,
        "category_analysis": categories,
        "top_channels": channels[:50],

        "top_documentary_candidates": sorted(
            [
                video for video in all_videos
                if video["documentary_suitability"] > 0
            ],
            key=lambda video: (
                video["topic_relevance_score"],
                video["performance_score"],
                video["documentary_suitability"]
            ),
            reverse=True
        )[:100],

        "top_shorts_candidates": sorted(
            [
                video for video in all_videos
                if video["shorts_suitability"] > 0
            ],
            key=lambda video: (
                video["topic_relevance_score"],
                video["performance_score"],
                video["shorts_suitability"]
            ),
            reverse=True
        )[:100],

        "search_audit": search_audit,
        "stop_reason": stop_reason,

        "limitations": [
            "YouTube Search API does not expose every YouTube video.",
            "Search results are ranked and incomplete.",
            "Duration alone cannot confirm official YouTube Shorts status.",
            "Shorts suitability is a duration-based estimate.",
            "Performance score is an estimate based on public metrics.",
            "Views per day is not true growth velocity.",
            "Public metrics do not reveal audience retention.",
            "Keyword relevance requires human review.",
            "Videos can match multiple categories.",
            "The database only contains discovered videos."
        ]
    }

    report_path = (
        OUTPUT_DIR
        / f"universe_report_v32_{timestamp}.json"
    )

    current_csv = (
        OUTPUT_DIR
        / f"current_scan_videos_v32_{timestamp}.csv"
    )

    master_csv = (
        OUTPUT_DIR
        / f"master_universe_videos_v32_{timestamp}.csv"
    )

    category_csv = (
        OUTPUT_DIR
        / f"category_analysis_v32_{timestamp}.csv"
    )

    channel_csv = (
        OUTPUT_DIR
        / f"channel_analysis_v32_{timestamp}.csv"
    )

    audit_csv = (
        OUTPUT_DIR
        / f"search_audit_v32_{timestamp}.csv"
    )

    duration_csv = (
        OUTPUT_DIR
        / f"duration_analysis_v32_{timestamp}.csv"
    )

    save_json(report_path, report)

    write_csv(current_csv, current_videos)
    write_csv(master_csv, all_videos)
    write_csv(category_csv, categories)
    write_csv(channel_csv, channels)
    write_csv(audit_csv, search_audit)
    write_csv(duration_csv, formats)

    latest_files = {
        "latest_universe_report_v32.json": report_path,
        "latest_current_scan_videos_v32.csv": current_csv,
        "latest_master_universe_videos_v32.csv": master_csv,
        "latest_category_analysis_v32.csv": category_csv,
        "latest_channel_analysis_v32.csv": channel_csv,
        "latest_search_audit_v32.csv": audit_csv,
        "latest_duration_analysis_v32.csv": duration_csv
    }

    for latest_name, source_path in latest_files.items():
        destination = OUTPUT_DIR / latest_name
        destination.write_bytes(
            source_path.read_bytes()
        )

    completed = datetime.now(timezone.utc)

    connection.execute("""
        INSERT OR REPLACE INTO scan_runs (
            run_id,
            started_at,
            completed_at,
            search_calls,
            detail_calls,
            discovered_total,
            database_total,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        timestamp,
        started.isoformat(),
        completed.isoformat(),
        search_calls,
        detail_calls,
        discovered_count,
        len(all_videos),
        stop_reason
    ))

    connection.commit()

    return all_videos


# ============================================================
# QUOTA ERROR DETECTION
# ============================================================

def is_quota_error(error):
    message = str(error).lower()

    return any(term in message for term in [
        "quotaexceeded",
        "dailylimitexceeded",
        "quota exceeded"
    ])


# ============================================================
# MAIN RUNNER
# ============================================================

def run():
    parser = argparse.ArgumentParser(
        description="YouTube Universe Scanner V3.2"
    )

    parser.add_argument(
        "--max-search-calls",
        type=int,
        default=DEFAULT_SEARCH_LIMIT
    )

    parser.add_argument(
        "--max-detail-calls",
        type=int,
        default=DEFAULT_DETAIL_LIMIT
    )

    parser.add_argument(
        "--skip-search",
        action="store_true",
        help="Do not make YouTube search API calls"
    )

    args = parser.parse_args()

    if (
        args.max_search_calls < 0
        or args.max_detail_calls < 0
    ):
        raise ValueError(
            "API call limits cannot be negative"
        )

    started = datetime.now(timezone.utc)

    timestamp = datetime.now().strftime(
        "%Y%m%d_%H%M%S"
    )

    search_calls = 0
    detail_calls = 0
    raw_results = 0

    saved_this_run = []

    stop_reason = "All available work processed"

    log("")
    log("=" * 65)
    log("YOUTUBE UNIVERSE SCANNER V3.2")
    log("CLEAN RESUMABLE CHECKPOINT MODE")
    log("=" * 65)

    log("Search API limit:", args.max_search_calls)
    log("Details API limit:", args.max_detail_calls)
    log("Database:", DATABASE)
    log("Output folder:", OUTPUT_DIR)

    connection = connect_database()

    try:
        # ----------------------------------------------------
        # API CLIENT
        # ----------------------------------------------------

        youtube = None

        if (
            not args.skip_search
            or args.max_detail_calls > 0
        ):
            api_key = load_api_key()

            youtube = build(
                "youtube",
                "v3",
                developerKey=api_key,
                cache_discovery=False
            )

        # ----------------------------------------------------
        # PHASE 1: SEARCH
        # ----------------------------------------------------

        log("")
        log("PHASE 1: YOUTUBE DISCOVERY")

        if args.skip_search:
            log("Search skipped. No search API calls.")

        else:
            jobs = build_jobs()

            for job_number, job in enumerate(
                jobs,
                start=1
            ):
                job_key = (
                    f"{job_number:03d}_"
                    + job["job_key"]
                )

                previous_next_token = None

                for page_num in range(
                    1,
                    MAX_PAGES_PER_SEARCH + 1
                ):
                    saved_page = get_saved_page(
                        connection,
                        job_key,
                        page_num
                    )

                    if saved_page:
                        previous_next_token = (
                            saved_page["next_page_token"]
                            or None
                        )
                        continue

                    if (
                        page_num > 1
                        and not previous_next_token
                    ):
                        break

                    if search_calls >= args.max_search_calls:
                        stop_reason = (
                            "Search call limit reached. "
                            "Run again later to resume."
                        )
                        break

                    try:
                        response = search_youtube(
                            youtube,
                            job,
                            previous_next_token
                        )

                        search_calls += 1

                        count, next_token = save_search_page(
                            connection,
                            job,
                            job_key,
                            page_num,
                            previous_next_token,
                            response
                        )

                        raw_results += count

                        log(
                            f"[Search {search_calls}/"
                            f"{args.max_search_calls}] "
                            f"{job['category']} | "
                            f"{job['language']} | "
                            f"{job['mode']} | "
                            f"Page {page_num} | "
                            f"{count} results | "
                            f"CHECKPOINT SAVED"
                        )

                        previous_next_token = (
                            next_token or None
                        )

                        if not previous_next_token:
                            break

                    except HttpError as error:
                        log(
                            "SEARCH API ERROR:",
                            str(error)[:500]
                        )

                        if is_quota_error(error):
                            stop_reason = (
                                "YouTube API quota exhausted. "
                                "Saved checkpoints preserved."
                            )
                        else:
                            stop_reason = (
                                "Search API error. "
                                "Saved checkpoints preserved."
                            )

                        break

                    except Exception as error:
                        log(
                            "SEARCH ERROR:",
                            type(error).__name__,
                            str(error)[:400]
                        )

                        stop_reason = (
                            "Search error. "
                            "Saved checkpoints preserved."
                        )

                        break

                if stop_reason != "All available work processed":
                    break

        # ----------------------------------------------------
        # PHASE 2: VIDEO DETAILS
        # ----------------------------------------------------

        discovered = get_discovered(connection)

        log("")
        log("PHASE 2: VIDEO DETAILS")

        log(
            "Unique discovered video IDs:",
            len(discovered)
        )

        existing_ids = {
            row["video_id"]
            for row in connection.execute(
                "SELECT video_id FROM videos"
            ).fetchall()
        }

        pending_ids = [
            video_id
            for video_id in discovered
            if video_id not in existing_ids
        ]

        log(
            "Videos waiting for details:",
            len(pending_ids)
        )

        if args.max_detail_calls == 0:
            log("Video details API calls disabled.")

        else:
            for start_index in range(
                0,
                len(pending_ids),
                50
            ):
                if detail_calls >= args.max_detail_calls:
                    if start_index < len(pending_ids):
                        stop_reason = (
                            "Video details call limit reached. "
                            "Remaining videos will resume later."
                        )
                    break

                batch = pending_ids[
                    start_index:start_index + 50
                ]

                try:
                    response = youtube.videos().list(
                        part=(
                            "snippet,"
                            "statistics,"
                            "contentDetails"
                        ),
                        id=",".join(batch),
                        maxResults=50
                    ).execute()

                    detail_calls += 1

                    returned_items = response.get(
                        "items", []
                    )

                    for item in returned_items:
                        video_id = item.get("id")

                        metadata = discovered.get(
                            video_id
                        )

                        if not metadata:
                            continue

                        video = make_video_record(
                            video_id,
                            item,
                            metadata
                        )

                        save_video(
                            connection,
                            video
                        )

                        saved_this_run.append(video)

                    connection.commit()

                    log(
                        f"[Details {detail_calls}/"
                        f"{args.max_detail_calls}] "
                        f"Received {len(returned_items)} "
                        f"| Saved {len(saved_this_run)}"
                    )

                except HttpError as error:
                    log(
                        "DETAIL API ERROR:",
                        str(error)[:500]
                    )

                    if is_quota_error(error):
                        stop_reason = (
                            "YouTube API quota exhausted "
                            "during details. "
                            "Completed batches preserved."
                        )
                    else:
                        stop_reason = (
                            "Video details API error. "
                            "Completed batches preserved."
                        )

                    break

                except Exception as error:
                    log(
                        "DETAIL ERROR:",
                        type(error).__name__,
                        str(error)[:400]
                    )

                    stop_reason = (
                        "Video details error. "
                        "Completed batches preserved."
                    )

                    break

        # ----------------------------------------------------
        # PHASE 3: REPORT GENERATION
        # ----------------------------------------------------

        log("")
        log("PHASE 3: REPORT GENERATION")

        all_videos = generate_reports(
            connection=connection,
            timestamp=timestamp,
            started=started,
            search_calls=search_calls,
            detail_calls=detail_calls,
            raw_results=raw_results,
            discovered_count=len(discovered),
            saved_this_run=saved_this_run,
            stop_reason=stop_reason
        )

        saved_pages = connection.execute("""
            SELECT COUNT(*) FROM search_pages
        """).fetchone()[0]

        log("")
        log("=" * 65)
        log("SCANNER RUN SUMMARY")
        log("=" * 65)

        log("Search API calls:", search_calls)
        log("Details API calls:", detail_calls)
        log("Raw search results:", raw_results)
        log("Unique discovered IDs:", len(discovered))
        log("New details saved:", len(saved_this_run))
        log("Master database videos:", len(all_videos))
        log("Saved page checkpoints:", saved_pages)

        log("Stop reason:", stop_reason)
        log("Database:", DATABASE)
        log("Reports:", OUTPUT_DIR)

        log("STATUS: REPORTS AND CHECKPOINTS SAVED")

    finally:
        connection.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        run()

    except KeyboardInterrupt:
        print(
            "\nStopped by user. "
            "Saved checkpoints will be available next run."
        )

    except Exception as error:
        print(
            "\nFATAL ERROR:",
            type(error).__name__,
            str(error)
        )
        raise