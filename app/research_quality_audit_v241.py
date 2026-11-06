
import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(r"G:\youtube automation")
RESEARCH_DIR = ROOT / "data" / "research"
SOURCE_FILE = RESEARCH_DIR / "latest_youtube_research_v23.json"

CATEGORIES = [
    "Human Psychology",
    "Money Psychology",
    "Power Dynamics",
    "Success",
    "Social Comparison"
]


def median(values):
    values = [float(v) for v in values if v is not None]
    return round(statistics.median(values), 2) if values else 0


def safe_date(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def write_csv(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields = list(rows[0].keys())

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()

        for row in rows:
            clean = {}
            for key, value in row.items():
                clean[key] = (
                    json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (list, dict))
                    else value
                )
            writer.writerow(clean)


def load_source():
    if not SOURCE_FILE.exists():
        raise FileNotFoundError(str(SOURCE_FILE))

    with SOURCE_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if not isinstance(data.get("videos"), list):
        raise ValueError("Source videos list missing.")

    return data


def audit_video_quality(videos):
    audited = []
    issues = []

    for video in videos:
        title = str(video.get("title") or "").strip()
        channel = str(video.get("channel_name") or "").strip()
        video_id = str(video.get("video_id") or "").strip()
        channel_id = str(video.get("channel_id") or "").strip()
        categories = video.get("matched_categories") or []

        flags = []
        score = 100

        if not video_id:
            score -= 30
            flags.append("missing_video_id")

        if not title:
            score -= 25
            flags.append("missing_title")

        if not channel:
            score -= 15
            flags.append("missing_channel_name")

        if not channel_id:
            score -= 10
            flags.append("missing_channel_id")

        if not video.get("published_at"):
            score -= 10
            flags.append("missing_publish_date")

        try:
            views = int(video.get("views"))
            if views <= 0:
                score -= 10
                flags.append("zero_or_missing_views")
        except (TypeError, ValueError):
            score -= 10
            flags.append("zero_or_missing_views")

        if not categories:
            score -= 10
            flags.append("missing_category")

        if len(title) < 12:
            score -= 10
            flags.append("very_short_title")

        score = max(score, 0)

        if flags:
            status = "REVIEW"
        elif score >= 80:
            status = "PASS"
        else:
            status = "LOW_QUALITY"

        row = dict(video)
        row["quality_score"] = score
        row["quality_flags"] = flags
        row["quality_status"] = status

        audited.append(row)

        if flags:
            issues.append({
                "video_id": video_id,
                "title": title,
                "channel_name": channel,
                "channel_id": channel_id,
                "quality_score": score,
                "quality_status": status,
                "quality_flags": flags
            })

    return audited, issues


def analyze_duplicates(videos):
    counts = Counter(
        video.get("video_id")
        for video in videos
        if video.get("video_id")
    )

    duplicates = {
        key: value for key, value in counts.items()
        if value > 1
    }

    return {
        "total_records": len(videos),
        "unique_video_ids": len(counts),
        "duplicate_video_ids": len(duplicates),
        "extra_duplicate_records": sum(
            value - 1 for value in duplicates.values()
        ),
        "duplicate_details": duplicates
    }


def analyze_categories(videos, now):
    rows = []

    for category in CATEGORIES:
        selected = [
            video for video in videos
            if category in (video.get("matched_categories") or [])
        ]

        channels = defaultdict(list)

        for video in selected:
            channel_id = str(video.get("channel_id") or "").strip()

            # Missing IDs ko ek competitor na samjhein.
            if channel_id:
                channels[channel_id].append(video)

        channel_counts = Counter(
            str(video.get("channel_id") or "").strip()
            for video in selected
            if str(video.get("channel_id") or "").strip()
        )

        top_three_count = sum(
            count for _, count in channel_counts.most_common(3)
        )

        total = len(selected)
        unique_channels = len(channels)

        recent = []
        established = []
        evergreen = []

        for video in selected:
            published = safe_date(video.get("published_at"))
            if not published:
                continue

            age_days = max(
                (now - published).total_seconds() / 86400, 0
            )

            if age_days <= 180:
                recent.append(video)
            elif age_days <= 365:
                established.append(video)
            else:
                evergreen.append(video)

        rows.append({
            "category": category,
            "video_count": total,
            "unique_channels": unique_channels,
            "missing_channel_id_count": sum(
                1 for video in selected
                if not str(video.get("channel_id") or "").strip()
            ),
            "median_views": median([
                video.get("views", 0) for video in selected
            ]),
            "median_views_per_day": median([
                video.get("views_per_day", 0) for video in selected
            ]),
            "recent_video_count": len(recent),
            "established_video_count": len(established),
            "evergreen_video_count": len(evergreen),
            "recent_median_views_per_day": median([
                video.get("views_per_day", 0) for video in recent
            ]),
            "short_candidate_count": sum(
                1 for video in selected
                if video.get("format_category") == "short_candidate"
            ),
            "long_form_count": sum(
                1 for video in selected
                if video.get("format_category") == "long_form"
            ),
            "top_3_channel_share_percent": round(
                top_three_count / total * 100, 2
            ) if total else 0
        })

    return rows


def analyze_competitors(videos):
    groups = defaultdict(list)

    for video in videos:
        channel_id = str(video.get("channel_id") or "").strip()

        if not channel_id:
            continue

        for category in video.get("matched_categories") or []:
            key = (category, channel_id)
            groups[key].append(video)

    rows = []

    for (category, channel_id), channel_videos in groups.items():
        channel_names = Counter(
            video.get("channel_name") or "Unknown"
            for video in channel_videos
        )

        rows.append({
            "category": category,
            "channel_id": channel_id,
            "channel_name": channel_names.most_common(1)[0][0],
            "video_count": len(channel_videos),
            "median_views": median([
                video.get("views", 0) for video in channel_videos
            ]),
            "median_views_per_day": median([
                video.get("views_per_day", 0)
                for video in channel_videos
            ])
        })

    return sorted(
        rows,
        key=lambda row: (
            row["category"],
            -row["video_count"],
            -row["median_views_per_day"]
        )
    )


def analyze_overlap(videos):
    pairs = Counter()

    for video in videos:
        categories = sorted(set(
            video.get("matched_categories") or []
        ))

        for i in range(len(categories)):
            for j in range(i + 1, len(categories)):
                pairs[(categories[i], categories[j])] += 1

    return [
        {
            "category_1": pair[0],
            "category_2": pair[1],
            "shared_video_count": count
        }
        for pair, count in pairs.most_common()
    ]


def analyze_formats(videos):
    rows = []

    for format_name in ["short_candidate", "long_form"]:
        selected = [
            video for video in videos
            if video.get("format_category") == format_name
        ]

        rows.append({
            "format": format_name,
            "video_count": len(selected),
            "median_views": median([
                video.get("views", 0) for video in selected
            ]),
            "median_views_per_day": median([
                video.get("views_per_day", 0) for video in selected
            ]),
            "median_engagement_percent": median([
                video.get("engagement_rate_percent", 0)
                for video in selected
            ])
        })

    return rows


def build_topic_shortlist(category_rows):
    topic_ideas = {
        "Human Psychology": [
            "Why do people make emotional decisions even when they know better?",
            "The hidden psychology behind everyday human behaviour"
        ],
        "Money Psychology": [
            "Rich vs Poor: How everyday money decisions shape the future",
            "Why a higher income does not always create financial freedom"
        ],
        "Power Dynamics": [
            "How emotional control influences power dynamics",
            "Why influence is not always about authority"
        ],
        "Success": [
            "Why delayed gratification is harder than it looks",
            "How instant gratification affects long-term success"
        ],
        "Social Comparison": [
            "Why seeing other people's lifestyle changes our spending",
            "The hidden cost of comparing your progress with friends"
        ]
    }

    category_map = {
        row["category"]: row for row in category_rows
    }

    result = []

    for category, topics in topic_ideas.items():
        evidence = category_map[category]

        for topic in topics:
            result.append({
                "topic": topic,
                "category": category,
                "evidence_video_count": evidence["video_count"],
                "unique_competitor_channels": evidence["unique_channels"],
                "recent_video_count": evidence["recent_video_count"],
                "recent_median_views_per_day": evidence[
                    "recent_median_views_per_day"
                ],
                "research_note": (
                    "Provisional category-level evidence; "
                    "topic-level validation still required."
                )
            })

    result.sort(
        key=lambda row: (
            row["recent_median_views_per_day"],
            row["evidence_video_count"]
        ),
        reverse=True
    )

    for index, row in enumerate(result, 1):
        row["provisional_rank"] = index

    return result[:10]


def main():
    print("\nRESEARCH QUALITY AUDIT V2.4.1")
    print("=" * 50)

    source = load_source()
    videos = source["videos"]
    now = datetime.now(timezone.utc)

    print("Source records:", len(videos))

    audited, issues = audit_video_quality(videos)
    duplicate_report = analyze_duplicates(audited)
    category_rows = analyze_categories(audited, now)
    competitor_rows = analyze_competitors(audited)
    overlap_rows = analyze_overlap(audited)
    format_rows = analyze_formats(audited)
    topic_rows = build_topic_shortlist(category_rows)

    passed = sum(
        1 for video in audited
        if video["quality_status"] == "PASS"
    )
    review = sum(
        1 for video in audited
        if video["quality_status"] == "REVIEW"
    )
    low = sum(
        1 for video in audited
        if video["quality_status"] == "LOW_QUALITY"
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report = {
        "engine": "Research Quality Audit V2.4.1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": str(SOURCE_FILE),
        "total_records": len(audited),
        "quality_summary": {
            "pass": passed,
            "review": review,
            "low_quality": low,
            "issues": len(issues)
        },
        "duplicate_audit": duplicate_report,
        "category_analysis": category_rows,
        "competitor_channels": competitor_rows,
        "category_overlap": overlap_rows,
        "format_analysis": format_rows,
        "top_10_provisional_topics": topic_rows,
        "methodology_notes": [
            "Missing or zero views always trigger REVIEW.",
            "Missing channel IDs trigger REVIEW.",
            "Competitor identity uses channel_id, not display name.",
            "Missing channel IDs are excluded from competitor ranking.",
            "Category counts may overlap.",
            "Top-three share is based only on this sample.",
            "Topic ranking is provisional and requires topic-level evidence.",
            "Short candidates are not confirmed YouTube Shorts."
        ]
    }

    outputs = {
        "json": RESEARCH_DIR / f"research_quality_audit_v241_{timestamp}.json",
        "videos": RESEARCH_DIR / f"video_quality_audit_v241_{timestamp}.csv",
        "issues": RESEARCH_DIR / f"quality_issues_v241_{timestamp}.csv",
        "categories": RESEARCH_DIR / f"category_audit_v241_{timestamp}.csv",
        "competitors": RESEARCH_DIR / f"competitor_channels_v241_{timestamp}.csv",
        "overlap": RESEARCH_DIR / f"category_overlap_v241_{timestamp}.csv",
        "formats": RESEARCH_DIR / f"format_audit_v241_{timestamp}.csv",
        "topics": RESEARCH_DIR / f"provisional_topics_v241_{timestamp}.csv"
    }

    outputs["json"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    write_csv(outputs["videos"], audited)
    write_csv(outputs["issues"], issues)
    write_csv(outputs["categories"], category_rows)
    write_csv(outputs["competitors"], competitor_rows)
    write_csv(outputs["overlap"], overlap_rows)
    write_csv(outputs["formats"], format_rows)
    write_csv(outputs["topics"], topic_rows)

    latest = {
        "json": "latest_research_quality_audit_v241.json",
        "videos": "latest_video_quality_audit_v241.csv",
        "issues": "latest_quality_issues_v241.csv",
        "categories": "latest_category_audit_v241.csv",
        "competitors": "latest_competitor_channels_v241.csv",
        "overlap": "latest_category_overlap_v241.csv",
        "formats": "latest_format_audit_v241.csv",
        "topics": "latest_provisional_topics_v241.csv"
    }

    for key, path in outputs.items():
        (RESEARCH_DIR / latest[key]).write_bytes(path.read_bytes())

    print("\nQUALITY SUMMARY")
    print("PASS:", passed)
    print("REVIEW:", review)
    print("LOW QUALITY:", low)
    print("Issues:", len(issues))

    print("\nDUPLICATE AUDIT")
    print(duplicate_report)

    print("\nCATEGORY SUMMARY")
    for row in category_rows:
        print(
            row["category"],
            "| Videos:", row["video_count"],
            "| Unique channels:", row["unique_channels"],
            "| Missing channel IDs:", row["missing_channel_id_count"],
            "| Recent:", row["recent_video_count"]
        )

    print("\nTOP COMPETITORS")
    for row in sorted(
        competitor_rows,
        key=lambda x: x["video_count"],
        reverse=True
    )[:15]:
        print(
            row["category"], "|",
            row["channel_name"], "|",
            row["channel_id"], "| Videos:",
            row["video_count"]
        )

    print("\nOUTPUT FILES")
    for path in outputs.values():
        print(path)

    print("\nSTATUS: SUCCESS")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("\nAUDIT ERROR:", type(error).__name__, str(error))
        raise
