import os
import argparse
import re
import json
import csv
import sqlite3
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict, Counter

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ============================================================
# YOUTUBE UNIVERSE SCANNER V3.2
# CHECKPOINT + RESUME + QUOTA CONTROL
# ============================================================

ROOT = Path(r"G:\youtube automation")

RUNTIME_ENV = (
    Path.home()
    / "youtube-automation-runtime"
    / ".env"
)

OUTPUT_DIR = (
    ROOT
    / "data"
    / "research"
    / "youtube_universe_v32"
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

DATABASE = OUTPUT_DIR / "youtube_universe.db"

MAX_SEARCH_CALLS = 10
MAX_DETAIL_CALLS = 10
MAX_PAGES_PER_SEARCH = 2
RESULTS_PER_PAGE = 50
RECENT_DAYS = 365


CATEGORIES = {
    "Human Psychology": {
        "queries": {
            "Hindi": ["human psychology Hindi"],
            "Hinglish": ["insani behaviour psychology"],
            "English": ["human psychology behavior"]
        },
        "terms": [
            "psychology", "human psychology",
            "human behavior", "human behaviour",
            "mind", "brain", "emotions",
            "behavior", "behaviour", "personality",
            "habits", "मानसिक", "मनोविज्ञान", "व्यवहार"
        ]
    },

    "Money Psychology": {
        "queries": {
            "Hindi": ["money psychology Hindi"],
            "Hinglish": ["paise ki psychology"],
            "English": ["money psychology personal finance behavior"]
        },
        "terms": [
            "money", "wealth", "finance", "financial",
            "rich", "poor", "spending", "saving",
            "investing", "income", "greed",
            "पैसा", "अमीर", "गरीब", "दौलत"
        ]
    },

    "Power Dynamics": {
        "queries": {
            "Hindi": ["power dynamics psychology Hindi"],
            "Hinglish": ["influence power psychology"],
            "English": ["power dynamics influence psychology"]
        },
        "terms": [
            "power", "influence", "authority",
            "dominance", "persuasion", "control",
            "manipulation", "leadership", "status",
            "शक्ति", "प्रभाव", "नेतृत्व"
        ]
    },

    "Success": {
        "queries": {
            "Hindi": ["success habits mindset Hindi"],
            "Hinglish": ["success mindset habits Hindi"],
            "English": ["success psychology habits"]
        },
        "terms": [
            "success", "mindset", "discipline",
            "motivation", "productivity", "goals",
            "growth", "achievement", "focus",
            "सफलता", "आदत", "अनुशासन"
        ]
    },

    "Social Comparison": {
        "queries": {
            "Hindi": ["social comparison psychology Hindi"],
            "Hinglish": ["dusron se comparison psychology"],
            "English": ["social comparison psychology lifestyle"]
        },
        "terms": [
            "comparison", "social status", "lifestyle",
            "jealousy", "envy", "peer pressure",
            "social media", "self worth", "status",
            "तुलना", "दिखावा", "जलन"
        ]
    }
}


# ============================================================
# HELPERS
# ============================================================

def log(*messages):
    print(*messages, flush=True)


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
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        return None


def median(values):
    values = [
        float(value)
        for value in values
        if value is not None
    ]

    if not values:
        return 0

    return round(statistics.median(values), 2)


def json_list(value):
    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) else []
    except (ValueError, TypeError):
        return []


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
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


# ============================================================
# DATABASE
# ============================================================

def connect_database():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row

    connection.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            channel_id TEXT,
            channel_title TEXT,
            published_at TEXT,
            duration_seconds INTEGER DEFAULT 0,
            view_count INTEGER DEFAULT 0,
            like_count INTEGER DEFAULT 0,
            comment_count INTEGER DEFAULT 0,
            category TEXT,
            language TEXT,
            search_query TEXT,
            search_mode TEXT,
            relevance_score REAL DEFAULT 0,
            relevance_flags TEXT,
            views_per_day REAL DEFAULT 0,
            video_url TEXT,
            collected_at TEXT
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS search_jobs (
            job_key TEXT PRIMARY KEY,
            category TEXT,
            language TEXT,
            mode TEXT,
            query TEXT,
            next_page_token TEXT,
            pages_completed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            updated_at TEXT
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS search_pages (
            job_key TEXT,
            page_num INTEGER,
            next_page_token TEXT,
            result_count INTEGER DEFAULT 0,
            completed_at TEXT,
            PRIMARY KEY (job_key, page_num)
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS discovered_videos (
            video_id TEXT PRIMARY KEY,
            category TEXT,
            language TEXT,
            search_query TEXT,
            search_mode TEXT,
            discovered_at TEXT
        )
    """)

    connection.execute("""
        CREATE TABLE IF NOT EXISTS scan_runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT,
            completed_at TEXT,
            search_calls INTEGER DEFAULT 0,
            detail_calls INTEGER DEFAULT 0,
            status TEXT,
            message TEXT
        )
    """)

    connection.commit()

    return connection


def save_video(connection, video):
    connection.execute("""
        INSERT INTO videos (
            video_id,
            title,
            description,
            channel_id,
            channel_title,
            published_at,
            duration_seconds,
            view_count,
            like_count,
            comment_count,
            category,
            language,
            search_query,
            search_mode,
            relevance_score,
            relevance_flags,
            views_per_day,
            video_url,
            collected_at
        )
        VALUES (
            :video_id,
            :title,
            :description,
            :channel_id,
            :channel_title,
            :published_at,
            :duration_seconds,
            :view_count,
            :like_count,
            :comment_count,
            :category,
            :language,
            :search_query,
            :search_mode,
            :relevance_score,
            :relevance_flags,
            :views_per_day,
            :video_url,
            :collected_at
        )
        ON CONFLICT(video_id) DO UPDATE SET
            title = excluded.title,
            description = excluded.description,
            channel_id = excluded.channel_id,
            channel_title = excluded.channel_title,
            published_at = excluded.published_at,
            duration_seconds = excluded.duration_seconds,
            view_count = excluded.view_count,
            like_count = excluded.like_count,
            comment_count = excluded.comment_count,
            relevance_score = excluded.relevance_score,
            relevance_flags = excluded.relevance_flags,
            views_per_day = excluded.views_per_day,
            collected_at = excluded.collected_at
    """, video)


def export_database(connection):
    rows = connection.execute("""
        SELECT *
        FROM videos
        ORDER BY relevance_score DESC, view_count DESC
    """).fetchall()

    videos = [dict(row) for row in rows]

    write_csv(
        OUTPUT_DIR / "youtube_universe_all_videos.csv",
        videos
    )

    json_path = OUTPUT_DIR / "youtube_universe_all_videos.json"

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(
            videos,
            file,
            ensure_ascii=False,
            indent=2
        )

    return videos
# ============================================================
# SEARCH QUERY ENGINE
# ============================================================

def build_jobs():
    jobs = []

    for category, category_data in CATEGORIES.items():
        for language, queries in category_data["queries"].items():
            for query in queries:
                for mode in ("recent", "popular"):
                    job_key = "|".join([
                        category,
                        language,
                        mode,
                        query
                    ])

                    jobs.append({
                        "job_key": job_key,
                        "category": category,
                        "language": language,
                        "mode": mode,
                        "query": query
                    })

    return jobs


def initialize_jobs(connection):
    now = datetime.now(timezone.utc).isoformat()

    for job in build_jobs():
        connection.execute("""
            INSERT OR IGNORE INTO search_jobs (
                job_key,
                category,
                language,
                mode,
                query,
                next_page_token,
                pages_completed,
                status,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, '', 0, 'pending', ?)
        """, (
            job["job_key"],
            job["category"],
            job["language"],
            job["mode"],
            job["query"],
            now
        ))

    connection.commit()


def get_pending_jobs(connection):
    rows = connection.execute("""
        SELECT *
        FROM search_jobs
        WHERE status != 'completed'
        ORDER BY category, language, mode
    """).fetchall()

    return [dict(row) for row in rows]


def search_youtube(
    youtube,
    job,
    page_token=None
):
    published_after = None

    if job["mode"] == "recent":
        published_after = (
            datetime.now(timezone.utc)
            - timedelta(days=RECENT_DAYS)
        ).isoformat().replace("+00:00", "Z")

    request_args = {
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

    if published_after:
        request_args["publishedAfter"] = published_after

    if page_token:
        request_args["pageToken"] = page_token

    return youtube.search().list(
        **request_args
    ).execute()


# ============================================================
# RELEVANCE ENGINE
# ============================================================

def calculate_relevance(
    title,
    description,
    category
):
    text = (
        (title or "") + " " + (description or "")
    ).lower()

    terms = CATEGORIES[category]["terms"]

    matched = []
    score = 0

    title_lower = (title or "").lower()

    for term in terms:
        term_lower = term.lower()

        if term_lower in text:
            matched.append(term)

            if term_lower in title_lower:
                score += 3
            else:
                score += 1

    if len(matched) >= 5:
        score += 3
    elif len(matched) >= 3:
        score += 2
    elif len(matched) >= 1:
        score += 1

    flags = []

    if not title:
        flags.append("MISSING_TITLE")

    if not description:
        flags.append("MISSING_DESCRIPTION")

    if not matched:
        flags.append("NO_CATEGORY_KEYWORD_MATCH")

    return {
        "score": score,
        "matched_terms": matched,
        "flags": flags
    }


# ============================================================
# VIDEO DETAILS
# ============================================================

def fetch_video_details(
    youtube,
    video_ids
):
    if not video_ids:
        return []

    response = youtube.videos().list(
        part="snippet,contentDetails,statistics",
        id=",".join(video_ids),
        maxResults=50
    ).execute()

    return response.get("items", [])


def make_video_record(
    item,
    metadata
):
    snippet = item.get("snippet", {})
    statistics_data = item.get("statistics", {})
    content = item.get("contentDetails", {})

    title = snippet.get("title", "")
    description = snippet.get("description", "")

    category = metadata["category"]

    relevance = calculate_relevance(
        title,
        description,
        category
    )

    duration = parse_duration(
        content.get("duration", "")
    )

    views = int(
        statistics_data.get("viewCount", 0) or 0
    )

    likes = int(
        statistics_data.get("likeCount", 0) or 0
    )

    comments = int(
        statistics_data.get("commentCount", 0) or 0
    )

    published_at = snippet.get("publishedAt", "")

    published_date = parse_date(published_at)

    if published_date:
        now = datetime.now(timezone.utc)

        if published_date.tzinfo is None:
            published_date = published_date.replace(
                tzinfo=timezone.utc
            )

        age_days = max(
            (now - published_date).total_seconds() / 86400,
            1
        )

        views_per_day = round(
            views / age_days,
            2
        )
    else:
        views_per_day = 0

    video_id = item.get("id", "")

    return {
        "video_id": video_id,
        "title": title,
        "description": description,
        "channel_id": snippet.get("channelId", ""),
        "channel_title": snippet.get("channelTitle", ""),
        "published_at": published_at,
        "duration_seconds": duration,
        "view_count": views,
        "like_count": likes,
        "comment_count": comments,
        "category": category,
        "language": metadata["language"],
        "search_query": metadata["query"],
        "search_mode": metadata["mode"],
        "relevance_score": relevance["score"],
        "relevance_flags": json.dumps(
            relevance["flags"],
            ensure_ascii=False
        ),
        "views_per_day": views_per_day,
        "video_url": (
            f"https://www.youtube.com/watch?v={video_id}"
        ),
        "collected_at": datetime.now(
            timezone.utc
        ).isoformat()
    }
import os
import re
import json
import csv
import sqlite3
import argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone
from collections import defaultdict, Counter
from statistics import median as get_median

from dotenv import load_dotenv
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# ============================================================
# YOUTUBE UNIVERSE SCANNER V3.2
# RESUMABLE + CHECKPOINTED + QUOTA CONTROLLED
# ============================================================

ROOT = Path(r"G:\youtube automation")
RUNTIME_ENV = Path.home() / "youtube-automation-runtime" / ".env"

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


CATEGORIES = {
    "Human Psychology": {
        "queries": {
            "Hindi": ["human psychology Hindi"],
            "Hinglish": ["insani behaviour psychology"],
            "English": ["human psychology behavior"]
        },
        "terms": [
            "psychology", "human psychology", "human behavior",
            "human behaviour", "mind", "brain", "emotions",
            "personality", "habits", "मनोविज्ञान", "व्यवहार"
        ]
    },
    "Money Psychology": {
        "queries": {
            "Hindi": ["money psychology Hindi"],
            "Hinglish": ["paise ki psychology"],
            "English": ["money psychology personal finance behavior"]
        },
        "terms": [
            "money", "wealth", "finance", "financial", "rich",
            "poor", "spending", "saving", "investing", "income",
            "पैसा", "अमीर", "गरीब", "दौलत"
        ]
    },
    "Power Dynamics": {
        "queries": {
            "Hindi": ["power dynamics psychology Hindi"],
            "Hinglish": ["influence power psychology"],
            "English": ["power dynamics influence psychology"]
        },
        "terms": [
            "power", "influence", "authority", "dominance",
            "persuasion", "control", "manipulation", "leadership",
            "status", "शक्ति", "प्रभाव", "नेतृत्व"
        ]
    },
    "Success": {
        "queries": {
            "Hindi": ["success habits mindset Hindi"],
            "Hinglish": ["success mindset habits Hindi"],
            "English": ["success psychology habits"]
        },
        "terms": [
            "success", "mindset", "discipline", "motivation",
            "productivity", "goals", "growth", "achievement",
            "focus", "सफलता", "आदत", "अनुशासन"
        ]
    },
    "Social Comparison": {
        "queries": {
            "Hindi": ["social comparison psychology Hindi"],
            "Hinglish": ["dusron se comparison psychology"],
            "English": ["social comparison psychology lifestyle"]
        },
        "terms": [
            "comparison", "social status", "lifestyle", "jealousy",
            "envy", "peer pressure", "social media", "self worth",
            "तुलना", "दिखावा", "जलन"
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


def load_api_key():
    if not RUNTIME_ENV.exists():
        raise FileNotFoundError(
            f"Runtime .env file not found: {RUNTIME_ENV}"
        )

    load_dotenv(RUNTIME_ENV)
    key = os.getenv("YOUTUBE_API_KEY")

    if not key:
        raise ValueError(
            "YOUTUBE_API_KEY is missing in runtime .env"
        )

    return key


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
        parsed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError):
        return None


def safe_int(value):
    try:
        return int(value or 0)
    except (ValueError, TypeError):
        return 0


def safe_json_list(value):
    try:
        result = json.loads(value or "[]")
        return result if isinstance(result, list) else []
    except (ValueError, TypeError):
        return []


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return

    fields = list(rows[0].keys())

    with path.open(
        "w", newline="", encoding="utf-8-sig"
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fields,
            extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(rows)


# ============================================================
# DATABASE
# ============================================================

def connect_database():
    connection = sqlite3.connect(DATABASE)
    connection.row_factory = sqlite3.Row

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


def merge_discovered_video(connection, video_id, job):
    row = connection.execute("""
        SELECT categories, languages, search_queries,
               first_discovered_at
        FROM discovered_videos
        WHERE video_id = ?
    """, (video_id,)).fetchone()

    now = utc_now()

    if row:
        categories = set(safe_json_list(row["categories"]))
        languages = set(safe_json_list(row["languages"]))
        queries = safe_json_list(row["search_queries"])
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
            video_id, categories, languages, search_queries,
            first_discovered_at, last_discovered_at
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
    connection, job, job_key, page_num,
    page_token, response
):
    items = response.get("items", [])
    next_token = response.get("nextPageToken", "")

    # Save page response and discovered IDs in one transaction.
    connection.execute("""
        INSERT OR REPLACE INTO search_pages (
            job_key, page_num, job_json, page_token,
            next_page_token, raw_count, response_json, created_at
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
        video_id = (
            item.get("id", {}).get("videoId")
        )
        if video_id:
            merge_discovered_video(
                connection, video_id, job
            )

    connection.commit()
    return len(items), next_token


def get_saved_page(connection, job_key, page_num):
    return connection.execute("""
        SELECT next_page_token
        FROM search_pages
        WHERE job_key = ? AND page_num = ?
    """, (job_key, page_num)).fetchone()


def get_discovered(connection):
    rows = connection.execute("""
        SELECT video_id, categories, languages, search_queries
        FROM discovered_videos
        ORDER BY video_id
    """).fetchall()

    result = {}

    for row in rows:
        result[row["video_id"]] = {
            "categories": safe_json_list(row["categories"]),
            "languages": safe_json_list(row["languages"]),
            "queries": safe_json_list(row["search_queries"])
        }

    return result


def save_video(connection, video):
    existing = connection.execute("""
        SELECT category_matches, languages, search_queries,
               first_seen_at, scan_count
        FROM videos
        WHERE video_id = ?
    """, (video["video_id"],)).fetchone()

    now = utc_now()

    if existing:
        categories = set(
            safe_json_list(existing["category_matches"])
        )
        languages = set(
            safe_json_list(existing["languages"])
        )
        queries = safe_json_list(existing["search_queries"])

        first_seen = existing["first_seen_at"]
        scan_count = safe_int(existing["scan_count"]) + 1
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
            video_id, title, description, channel_id, channel_name,
            published_at, duration_seconds, views, likes, comments,
            views_per_day, engagement_rate, category_matches,
            languages, search_queries, relevance_score,
            relevance_status, first_seen_at, last_seen_at, scan_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?)
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
        json.dumps(sorted(categories), ensure_ascii=False),
        json.dumps(sorted(languages), ensure_ascii=False),
        json.dumps(queries[-100:], ensure_ascii=False),
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
                        category, language, mode, query
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
            "date" if job["mode"] == "recent"
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
            published_after.isoformat().replace("+00:00", "Z")
        )

    if page_token:
        args["pageToken"] = page_token

    return youtube.search().list(**args).execute()


# ============================================================
# RELEVANCE SCORING
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

    return score, status, matched


# ============================================================
# VIDEO DETAILS
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
        score, status, _ = calculate_relevance(
            title, description, category
        )

        if score > best_score:
            best_score = score
            best_status = status

    views = safe_int(stats.get("viewCount"))
    likes = safe_int(stats.get("likeCount"))
    comments = safe_int(stats.get("commentCount"))

    published_at = snippet.get("publishedAt", "")
    published_date = parse_date(published_at)

    if published_date:
        age_days = max(
            (datetime.now(timezone.utc) - published_date)
            .total_seconds() / 86400,
            1
        )
    else:
        age_days = 1

    views_per_day = round(views / age_days, 2)

    engagement_rate = (
        round(((likes + comments) / views) * 100, 2)
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


def is_quota_error(error):
    message = str(error).lower()

    return any(term in message for term in [
        "quotaexceeded",
        "dailylimitexceeded",
        "quota exceeded"
    ])


# ============================================================
# ANALYSIS
# ============================================================

def median_value(values):
    clean = [
        float(value or 0)
        for value in values
        if value is not None
    ]

    return round(get_median(clean), 2) if clean else 0


def category_analysis(videos):
    results = []

    for category in CATEGORIES:
        selected = [
            video for video in videos
            if category in safe_json_list(
                video.get("category_matches")
            )
        ]

        channels = {
            video["channel_id"]
            for video in selected
            if video.get("channel_id")
        }

        results.append({
            "category": category,
            "video_count": len(selected),
            "unique_channels": len(channels),
            "median_views": median_value([
                video["views"] for video in selected
            ]),
            "median_views_per_day": median_value([
                video["views_per_day"] for video in selected
            ]),
            "median_engagement_percent": median_value([
                video["engagement_rate"] for video in selected
            ])
        })

    return results


def channel_analysis(videos):
    groups = defaultdict(list)

    for video in videos:
        channel_id = video.get("channel_id")

        if channel_id:
            groups[channel_id].append(video)

    results = []

    for channel_id, items in groups.items():
        names = Counter(
            item["channel_name"] for item in items
        )

        categories = sorted({
            category
            for item in items
            for category in safe_json_list(
                item.get("category_matches")
            )
        })

        results.append({
            "channel_id": channel_id,
            "channel_name": (
                names.most_common(1)[0][0] if names else ""
            ),
            "video_count": len(items),
            "categories": categories,
            "median_views": median_value([
                item["views"] for item in items
            ]),
            "median_views_per_day": median_value([
                item["views_per_day"] for item in items
            ])
        })

    return sorted(
        results,
        key=lambda row: (
            row["video_count"],
            row["median_views_per_day"]
        ),
        reverse=True
    )


def prepare_video_exports(videos):
    output = []

    for original in videos:
        video = dict(original)

        video["category_matches"] = safe_json_list(
            video.get("category_matches")
        )
        video["languages"] = safe_json_list(
            video.get("languages")
        )
        video["search_queries"] = safe_json_list(
            video.get("search_queries")
        )

        duration = safe_int(video.get("duration_seconds"))

        video["format_category"] = (
            "short_candidate"
            if duration <= 180
            else "long_form"
        )

        video["video_url"] = (
            "https://www.youtube.com/watch?v="
            + video["video_id"]
        )

        output.append(video)

    return output

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

    categories = category_analysis(all_videos)
    channels = channel_analysis(all_videos)

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
        "new_video_details_saved_this_run": len(saved_this_run),
        "master_database_total": len(all_videos),
        "relevance_summary_this_run": {
            "relevant_candidates": sum(
                1 for v in saved_this_run
                if v["relevance_status"] == "RELEVANT_CANDIDATE"
            ),
            "review": sum(
                1 for v in saved_this_run
                if v["relevance_status"] == "REVIEW"
            ),
            "low_relevance": sum(
                1 for v in saved_this_run
                if v["relevance_status"] == "LOW_RELEVANCE"
            )
        },
        "category_analysis": categories,
        "top_channels": channels[:50],
        "search_audit": search_audit,
        "stop_reason": stop_reason,
        "limitations": [
            "YouTube Search API does not expose every YouTube video.",
            "Search results are ranked and incomplete.",
            "Videos of 180 seconds or less are only short candidates, not confirmed Shorts.",
            "Relevance scoring is keyword-based and needs human review.",
            "Views per day is not true growth velocity.",
            "A video may match more than one category.",
            "The database contains only videos discovered by this scanner."
        ]
    }

    report_path = (
        OUTPUT_DIR / f"universe_report_v32_{timestamp}.json"
    )
    current_csv = (
        OUTPUT_DIR / f"current_scan_videos_v32_{timestamp}.csv"
    )
    master_csv = (
        OUTPUT_DIR / f"master_universe_videos_v32_{timestamp}.csv"
    )
    category_csv = (
        OUTPUT_DIR / f"category_analysis_v32_{timestamp}.csv"
    )
    channel_csv = (
        OUTPUT_DIR / f"channel_analysis_v32_{timestamp}.csv"
    )
    audit_csv = (
        OUTPUT_DIR / f"search_audit_v32_{timestamp}.csv"
    )

    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    write_csv(current_csv, saved_this_run)
    write_csv(master_csv, all_videos)
    write_csv(category_csv, categories)
    write_csv(channel_csv, channels)
    write_csv(audit_csv, search_audit)

    latest_files = {
        "latest_universe_report_v32.json": report_path,
        "latest_current_scan_videos_v32.csv": current_csv,
        "latest_master_universe_videos_v32.csv": master_csv,
        "latest_category_analysis_v32.csv": category_csv,
        "latest_channel_analysis_v32.csv": channel_csv,
        "latest_search_audit_v32.csv": audit_csv
    }

    for latest_name, source_path in latest_files.items():
        destination = OUTPUT_DIR / latest_name
        destination.write_bytes(source_path.read_bytes())

    completed = datetime.now(timezone.utc)

    connection.execute("""
        INSERT OR REPLACE INTO scan_runs (
            run_id, started_at, completed_at,
            search_calls, detail_calls, discovered_total,
            database_total, status
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
# MAIN RUNNER
# ============================================================

def run():
    parser = argparse.ArgumentParser(
        description="Resumable YouTube niche research scanner"
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
        help="Process saved discoveries without making search calls"
    )

    args = parser.parse_args()

    if args.max_search_calls < 0 or args.max_detail_calls < 0:
        raise ValueError("API call limits cannot be negative")

    started = datetime.now(timezone.utc)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    search_calls = 0
    detail_calls = 0
    raw_results = 0
    saved_this_run = []

    stop_reason = "All available work processed"

    log("")
    log("=" * 65)
    log("YOUTUBE UNIVERSE SCANNER V3.2")
    log("RESUMABLE CHECKPOINT MODE")
    log("=" * 65)
    log("Search API call limit:", args.max_search_calls)
    log("Video details call limit:", args.max_detail_calls)
    log("Database:", DATABASE)

    api_key = load_api_key()

    youtube = build(
        "youtube",
        "v3",
        developerKey=api_key,
        cache_discovery=False
    )

    connection = connect_database()

    # --------------------------------------------------------
    # PHASE 1: SEARCH WITH PAGE CHECKPOINTS
    # --------------------------------------------------------

    log("")
    log("PHASE 1: YOUTUBE DISCOVERY")

    if args.skip_search:
        log("Search skipped. Existing discoveries will be processed.")

    else:
        jobs = build_jobs()

        for job_number, job in enumerate(jobs, start=1):

            job_key = (
                f"{job_number:03d}_"
                + job["job_key"]
            )

            previous_next_token = None

            for page_num in range(1, MAX_PAGES_PER_SEARCH + 1):

                saved_page = get_saved_page(
                    connection,
                    job_key,
                    page_num
                )

                # Already completed page: reuse its saved token.
                if saved_page:
                    previous_next_token = (
                        saved_page["next_page_token"] or None
                    )
                    continue

                # Page 2 cannot run without a page 1 next token.
                if page_num > 1 and not previous_next_token:
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
                        f"{count} results | CHECKPOINT SAVED"
                    )

                    previous_next_token = next_token or None

                    if not previous_next_token:
                        break

                except HttpError as error:
                    log("SEARCH API ERROR:", str(error)[:500])

                    if is_quota_error(error):
                        stop_reason = (
                            "YouTube API quota exhausted. "
                            "Saved pages are preserved."
                        )
                    else:
                        stop_reason = (
                            "Search API error. "
                            "Saved pages are preserved."
                        )

                    break

                except Exception as error:
                    log(
                        "SEARCH ERROR:",
                        type(error).__name__,
                        str(error)[:400]
                    )

                    stop_reason = (
                        "Search error. Completed checkpoints are preserved."
                    )
                    break

            if stop_reason != "All available work processed":
                break

    # --------------------------------------------------------
    # PHASE 2: FETCH DETAILS IN SMALL BATCHES
    # --------------------------------------------------------

    discovered = get_discovered(connection)

    log("")
    log("PHASE 2: VIDEO DETAILS")
    log("Unique discovered video IDs:", len(discovered))

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

    log("Videos waiting for details:", len(pending_ids))

    for start_index in range(0, len(pending_ids), 50):

        if detail_calls >= args.max_detail_calls:
            if start_index < len(pending_ids):
                stop_reason = (
                    "Video details call limit reached. "
                    "Remaining videos will resume next run."
                )
            break

        batch = pending_ids[start_index:start_index + 50]

        try:
            response = youtube.videos().list(
                part="snippet,statistics,contentDetails",
                id=",".join(batch),
                maxResults=50
            ).execute()

            detail_calls += 1

            returned_items = response.get("items", [])

            for item in returned_items:
                video_id = item.get("id")

                metadata = discovered.get(video_id)

                if not metadata:
                    continue

                video = make_video_record(
                    video_id,
                    item,
                    metadata
                )

                save_video(connection, video)
                saved_this_run.append(video)

            # Commit each batch immediately.
            connection.commit()

            log(
                f"[Details {detail_calls}/"
                f"{args.max_detail_calls}] "
                f"Received {len(returned_items)} videos. "
                f"Saved this run: {len(saved_this_run)}"
            )

        except HttpError as error:
            log("DETAIL API ERROR:", str(error)[:500])

            if is_quota_error(error):
                stop_reason = (
                    "YouTube API quota exhausted during details. "
                    "Completed batches are saved."
                )
            else:
                stop_reason = (
                    "Video details API error. "
                    "Completed batches are saved."
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
                "Completed batches are saved."
            )
            break

    # --------------------------------------------------------
    # PHASE 3: REPORTS
    # --------------------------------------------------------

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

    saved_pages = connection.execute(
        "SELECT COUNT(*) FROM search_pages"
    ).fetchone()[0]

    log("")
    log("=" * 65)
    log("SCANNER RUN SUMMARY")
    log("=" * 65)
    log("Search API calls this run:", search_calls)
    log("Details API calls this run:", detail_calls)
    log("Raw search results this run:", raw_results)
    log("Unique discovered video IDs:", len(discovered))
    log("New video details saved:", len(saved_this_run))
    log("Total master database videos:", len(all_videos))
    log("Saved search page checkpoints:", saved_pages)
    log("Stop reason:", stop_reason)
    log("Database:", DATABASE)
    log("Reports:", OUTPUT_DIR)
    log("STATUS: CHECKPOINTS AND REPORTS SAVED")

    connection.close()


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        print("\nStopped by user. Saved checkpoints will be available next run.")
    except Exception as error:
        print(
            "\nFATAL ERROR:",
            type(error).__name__,
            str(error)
        )
        raise