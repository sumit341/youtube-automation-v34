
import csv
import json
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(r"G:\youtube automation")
RESEARCH_DIR = ROOT / "data" / "research"

SOURCE_FILE = RESEARCH_DIR / "latest_youtube_research_v23.json"

CATEGORY_NAMES = [
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
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        return None


def csv_write(path, rows):
    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fields = list(rows[0].keys())

    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()

        for row in rows:
            clean_row = {}

            for key, value in row.items():
                if isinstance(value, (list, dict)):
                    clean_row[key] = json.dumps(
                        value, ensure_ascii=False
                    )
                else:
                    clean_row[key] = value

            writer.writerow(clean_row)


def load_source():
    if not SOURCE_FILE.exists():
        raise FileNotFoundError(
            f"V2.3 source report not found: {SOURCE_FILE}"
        )

    with SOURCE_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if "videos" not in data:
        raise ValueError("Source JSON does not contain videos.")

    return data


def audit_video_quality(videos):
    audited = []
    issues = []

    for video in videos:
        title = str(video.get("title") or "").strip()
        channel = str(video.get("channel_name") or "").strip()
        video_id = str(video.get("video_id") or "").strip()
        categories = video.get("matched_categories") or []

        quality_score = 100
        flags = []

        if not video_id:
            quality_score -= 30
            flags.append("missing_video_id")

        if not title:
            quality_score -= 25
            flags.append("missing_title")

        if not channel:
            quality_score -= 15
            flags.append("missing_channel_name")

        if not video.get("published_at"):
            quality_score -= 10
            flags.append("missing_publish_date")

        if int(video.get("views") or 0) <= 0:
            quality_score -= 10
            flags.append("zero_or_missing_views")

        if not categories:
            quality_score -= 10
            flags.append("missing_category")

        if len(title) < 12:
            quality_score -= 10
            flags.append("very_short_title")

        quality_score = max(0, quality_score)

        row = dict(video)
        row["quality_score"] = quality_score
        row["quality_flags"] = flags
        row["quality_status"] = (
            "PASS" if quality_score >= 80
            else "REVIEW" if quality_score >= 60
            else "LOW_QUALITY"
        )

        audited.append(row)

        if flags:
            issues.append({
                "video_id": video_id,
                "title": title,
                "channel_name": channel,
                "quality_score": quality_score,
                "quality_status": row["quality_status"],
                "quality_flags": flags
            })

    return audited, issues


def analyze_duplicates(videos):
    counts = Counter(
        str(video.get("video_id") or "")
        for video in videos
        if video.get("video_id")
    )

    duplicate_ids = {
        video_id: count
        for video_id, count in counts.items()
        if count > 1
    }

    return {
        "total_video_records": len(videos),
        "unique_video_ids": len(counts),
        "duplicate_video_ids": len(duplicate_ids),
        "duplicate_records_extra": sum(
            count - 1 for count in duplicate_ids.values()
        ),
        "duplicate_details": duplicate_ids
    }


def analyze_categories(videos, now):
    category_rows = []
    competitor_rows = []
    category_video_map = {}

    for category in CATEGORY_NAMES:
        selected = [
            video for video in videos
            if category in (video.get("matched_categories") or [])
        ]

        category_video_map[category] = selected

        channel_counts = Counter(
            video.get("channel_name") or "Unknown channel"
            for video in selected
        )

        total = len(selected)
        unique_channels = len(channel_counts)

        top_three_count = sum(
            count for _, count in channel_counts.most_common(3)
        )

        top_three_share = (
            round(top_three_count / total * 100, 2)
            if total else 0
        )

        views_per_day = [
            float(video.get("views_per_day") or 0)
            for video in selected
        ]

        recent = []
        established = []
        evergreen = []

        for video in selected:
            published = safe_date(video.get("published_at"))

            if published is None:
                continue

            age_days = max(
                (now - published).total_seconds() / 86400,
                0
            )

            if age_days <= 180:
                recent.append(video)
            elif age_days <= 365:
                established.append(video)
            else:
                evergreen.append(video)

        row = {
            "category": category,
            "video_count": total,
            "unique_channels": unique_channels,
            "median_views": median([
                video.get("views", 0) for video in selected
            ]),
            "median_views_per_day": median(views_per_day),
            "recent_video_count": len(recent),
            "established_video_count": len(established),
            "evergreen_video_count": len(evergreen),
            "recent_median_views_per_day": median([
                video.get("views_per_day", 0) for video in recent
            ]),
            "long_form_count": sum(
                1 for video in selected
                if video.get("format_category") == "long_form"
            ),
            "short_candidate_count": sum(
                1 for video in selected
                if video.get("format_category") == "short_candidate"
            ),
            "videos_per_channel": round(
                total / unique_channels, 2
            ) if unique_channels else 0,
            "top_3_channel_share_percent": top_three_share,
            "channel_diversity_percent": round(
                unique_channels / total * 100, 2
            ) if total else 0
        }

        category_rows.append(row)

        for channel_name, count in channel_counts.most_common():
            channel_videos = [
                video for video in selected
                if (video.get("channel_name") or "Unknown channel")
                == channel_name
            ]

            competitor_rows.append({
                "category": category,
                "channel_name": channel_name,
                "video_count": count,
                "median_views": median([
                    video.get("views", 0)
                    for video in channel_videos
                ]),
                "median_views_per_day": median([
                    video.get("views_per_day", 0)
                    for video in channel_videos
                ]),
                "recent_video_count": sum(
                    1 for video in channel_videos
                    if video in recent
                )
            })

    return category_rows, competitor_rows, category_video_map


def analyze_category_overlap(videos):
    pair_counts = Counter()
    category_counts = Counter()

    for video in videos:
        categories = sorted(set(
            video.get("matched_categories") or []
        ))

        for category in categories:
            category_counts[category] += 1

        for first_index in range(len(categories)):
            for second_index in range(first_index + 1, len(categories)):
                pair = (
                    categories[first_index],
                    categories[second_index]
                )
                pair_counts[pair] += 1

    overlap_rows = []

    for (first, second), count in pair_counts.items():
        overlap_rows.append({
            "category_1": first,
            "category_2": second,
            "shared_video_count": count
        })

    overlap_rows.sort(
        key=lambda row: row["shared_video_count"],
        reverse=True
    )

    return overlap_rows


def analyze_formats(videos):
    result = []

    for format_name in ["short_candidate", "long_form"]:
        selected = [
            video for video in videos
            if video.get("format_category") == format_name
        ]

        result.append({
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

    return result


def build_topic_shortlist(category_rows):
    category_map = {
        row["category"]: row for row in category_rows
    }

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

    shortlist = []

    for category, topics in topic_ideas.items():
        evidence = category_map[category]

        for topic in topics:
            shortlist.append({
                "topic": topic,
                "category": category,
                "evidence_video_count": evidence["video_count"],
                "unique_competitor_channels": evidence["unique_channels"],
                "median_views_per_day": evidence["median_views_per_day"],
                "recent_video_count": evidence["recent_video_count"],
                "recent_median_views_per_day": evidence[
                    "recent_median_views_per_day"
                ],
                "top_3_channel_share_percent": evidence[
                    "top_3_channel_share_percent"
                ],
                "research_note": (
                    "Needs manual topic-level validation; "
                    "category evidence is not topic-specific proof."
                )
            })

    shortlist.sort(
        key=lambda row: (
            row["recent_median_views_per_day"],
            row["median_views_per_day"],
            row["evidence_video_count"]
        ),
        reverse=True
    )

    for rank, row in enumerate(shortlist, start=1):
        row["provisional_rank"] = rank

    return shortlist[:10]


def main():
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

    print("\nRESEARCH QUALITY & COMPETITION AUDIT V2.4")
    print("=" * 52)

    source = load_source()
    videos = source["videos"]

    print("Source:", SOURCE_FILE)
    print("Input video records:", len(videos))

    now = datetime.now(timezone.utc)

    audited_videos, quality_issues = audit_video_quality(videos)

    duplicate_report = analyze_duplicates(videos)

    category_rows, competitor_rows, category_video_map = (
        analyze_categories(audited_videos, now)
    )

    overlap_rows = analyze_category_overlap(audited_videos)
    format_rows = analyze_formats(audited_videos)
    topic_shortlist = build_topic_shortlist(category_rows)

    passed = sum(
        1 for video in audited_videos
        if video["quality_status"] == "PASS"
    )

    review = sum(
        1 for video in audited_videos
        if video["quality_status"] == "REVIEW"
    )

    low_quality = sum(
        1 for video in audited_videos
        if video["quality_status"] == "LOW_QUALITY"
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    report = {
        "engine": "Research Quality & Competition Audit V2.4",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_file": str(SOURCE_FILE),
        "input_video_records": len(videos),
        "quality_summary": {
            "pass": passed,
            "review": review,
            "low_quality": low_quality,
            "issues_found": len(quality_issues)
        },
        "duplicate_audit": duplicate_report,
        "category_analysis": category_rows,
        "category_overlap": overlap_rows,
        "competitor_channels": competitor_rows,
        "format_analysis": format_rows,
        "top_10_provisional_topics": topic_shortlist,
        "methodology_notes": [
            "This module audits the V2.3 dataset; it does not collect new YouTube data.",
            "Category counts can overlap because one video may match multiple categories.",
            "Channel counts are based on the collected sample, not the entire YouTube market.",
            "Top-three channel share is sample concentration, not total market share.",
            "A high channel count does not automatically mean high competition.",
            "No subscriber-normalized competition score is calculated.",
            "Topic shortlist is provisional because evidence is category-level, not topic-level.",
            "Short candidate means duration of 180 seconds or less; it does not confirm Shorts eligibility.",
            "Public views per day are historical averages, not real-time velocity."
        ]
    }

    output_files = {
        "json": RESEARCH_DIR / f"research_quality_audit_v24_{timestamp}.json",
        "videos": RESEARCH_DIR / f"video_quality_audit_v24_{timestamp}.csv",
        "categories": RESEARCH_DIR / f"category_audit_v24_{timestamp}.csv",
        "competitors": RESEARCH_DIR / f"competitor_channels_v24_{timestamp}.csv",
        "overlap": RESEARCH_DIR / f"category_overlap_v24_{timestamp}.csv",
        "formats": RESEARCH_DIR / f"format_audit_v24_{timestamp}.csv",
        "topics": RESEARCH_DIR / f"provisional_topics_v24_{timestamp}.csv",
        "issues": RESEARCH_DIR / f"quality_issues_v24_{timestamp}.csv"
    }

    output_files["json"].write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    csv_write(output_files["videos"], audited_videos)
    csv_write(output_files["categories"], category_rows)
    csv_write(output_files["competitors"], competitor_rows)
    csv_write(output_files["overlap"], overlap_rows)
    csv_write(output_files["formats"], format_rows)
    csv_write(output_files["topics"], topic_shortlist)
    csv_write(output_files["issues"], quality_issues)

    latest_names = {
        "json": "latest_research_quality_audit_v24.json",
        "videos": "latest_video_quality_audit_v24.csv",
        "categories": "latest_category_audit_v24.csv",
        "competitors": "latest_competitor_channels_v24.csv",
        "overlap": "latest_category_overlap_v24.csv",
        "formats": "latest_format_audit_v24.csv",
        "topics": "latest_provisional_topics_v24.csv",
        "issues": "latest_quality_issues_v24.csv"
    }

    for key, source_path in output_files.items():
        destination = RESEARCH_DIR / latest_names[key]
        destination.write_bytes(source_path.read_bytes())

    print("\nQUALITY SUMMARY")
    print("PASS:", passed)
    print("REVIEW:", review)
    print("LOW QUALITY:", low_quality)
    print("Issues:", len(quality_issues))

    print("\nDUPLICATE AUDIT")
    print("Input records:", duplicate_report["total_video_records"])
    print("Unique IDs:", duplicate_report["unique_video_ids"])
    print("Duplicate IDs:", duplicate_report["duplicate_video_ids"])

    print("\nCATEGORY AUDIT")
    for index, row in enumerate(category_rows, start=1):
        print(
            f"{index}. {row['category']} | "
            f"Videos: {row['video_count']} | "
            f"Channels: {row['unique_channels']} | "
            f"Recent: {row['recent_video_count']} | "
            f"Top 3 share: {row['top_3_channel_share_percent']}%"
        )

    print("\nFORMAT AUDIT")
    for row in format_rows:
        print(
            f"{row['format']} | "
            f"Videos: {row['video_count']} | "
            f"Median views/day: {row['median_views_per_day']}"
        )

    print("\nTOP 10 PROVISIONAL TOPICS")
    for row in topic_shortlist:
        print(
            f"{row['provisional_rank']}. {row['topic']} "
            f"[{row['category']}]"
        )

    print("\nREPORT FILES")
    for path in output_files.values():
        print(path)

    print("\nSTATUS: SUCCESS")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(
            "\nAUDIT ERROR:",
            type(error).__name__,
            str(error),
            flush=True
        )
        raise
