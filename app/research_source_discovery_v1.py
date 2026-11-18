from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "research" / "youtube_universe_v33"
WORKSPACES = BASE / "research_workspace_v33"

FIELDS = [
    "source_id",
    "title",
    "author",
    "organization",
    "published_date",
    "source_type",
    "url_or_doi",
    "accessed_date",
    "source_review_status",
    "notes",
    "provider",
    "provider_id",
    "abstract",
    "discovery_query",
    "discovered_at",
]

USER_AGENT = "TheSuccessParadoxResearchWorkbench/1.0 (academic source discovery)"
TIMEOUT_SECONDS = 20
MAX_RETRIES = 2


def clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(clean(x) for x in value if clean(x))
    return str(value).strip()


def stable_id(value: str) -> str:
    digest = hashlib.sha256(value.lower().strip().encode("utf-8")).hexdigest()
    return "DISC-" + digest[:16].upper()


def reconstruct_abstract(index: Any) -> str:
    if not isinstance(index, dict):
        return ""

    words = {}
    for word, positions in index.items():
        if not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                words[position] = word

    return " ".join(words[key] for key in sorted(words))


def request_json(url: str) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
    )

    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            with urllib.request.urlopen(
                request,
                timeout=TIMEOUT_SECONDS,
            ) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload)

        except Exception as exc:
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"Request failed: {last_error}")


def normalize_doi(value: Any) -> str:
    doi = clean(value)
    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")
    return doi.strip().lower()


def openalex_search(query: str, limit: int) -> list[dict]:
    params = {
        "search": query,
        "per-page": str(limit),
        "select": (
            "id,doi,title,publication_year,authorships,"
            "primary_location,type,open_access,abstract_inverted_index"
        ),
    }

    url = (
        "https://api.openalex.org/works?"
        + urllib.parse.urlencode(params)
    )

    payload = request_json(url)
    results = payload.get("results", [])

    rows = []

    for item in results:
        authorships = item.get("authorships") or []
        authors = []

        for author_item in authorships:
            author = author_item.get("author") or {}
            name = clean(author.get("display_name"))
            if name:
                authors.append(name)

        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        doi = normalize_doi(item.get("doi"))

        rows.append({
            "title": clean(item.get("title")),
            "author": "; ".join(authors),
            "organization": clean(source.get("display_name")),
            "published_date": clean(item.get("publication_year")),
            "source_type": clean(item.get("type")) or "Academic work",
            "url_or_doi": (
                "https://doi.org/" + doi
                if doi
                else clean(item.get("id"))
            ),
            "abstract": reconstruct_abstract(
                item.get("abstract_inverted_index")
            ),
            "provider": "OpenAlex",
            "provider_id": clean(item.get("id")),
            "doi_key": doi,
        })

    return rows


def crossref_search(query: str, limit: int) -> list[dict]:
    params = {
        "query": query,
        "rows": str(limit),
        "select": (
            "DOI,title,author,published,container-title,"
            "type,URL,abstract,publisher"
        ),
    }

    url = (
        "https://api.crossref.org/works?"
        + urllib.parse.urlencode(params)
    )

    payload = request_json(url)
    message = payload.get("message") or {}
    results = message.get("items") or []

    rows = []

    for item in results:
        title_list = item.get("title") or []
        title = clean(title_list[0]) if title_list else ""

        author_names = []
        for author in item.get("author") or []:
            given = clean(author.get("given"))
            family = clean(author.get("family"))
            name = " ".join(x for x in [given, family] if x)
            if name:
                author_names.append(name)

        date_parts = (
            (item.get("published") or {}).get("date-parts") or [[]]
        )
        date = "-".join(str(x) for x in date_parts[0]) if date_parts[0] else ""

        doi = normalize_doi(item.get("DOI"))

        rows.append({
            "title": title,
            "author": "; ".join(author_names),
            "organization": clean(item.get("publisher")),
            "published_date": date,
            "source_type": clean(item.get("type")) or "Academic work",
            "url_or_doi": (
                "https://doi.org/" + doi
                if doi
                else clean(item.get("URL"))
            ),
            "abstract": clean(item.get("abstract")),
            "provider": "Crossref",
            "provider_id": doi or clean(item.get("URL")),
            "doi_key": doi,
        })

    return rows


def discover(query: str, limit: int, provider: str) -> tuple[list[dict], list[str]]:
    rows = []
    errors = []

    if provider in ("openalex", "both"):
        try:
            rows.extend(openalex_search(query, limit))
        except Exception as exc:
            errors.append(f"OpenAlex: {exc}")

    if provider in ("crossref", "both"):
        if rows:
            time.sleep(1.0)

        try:
            rows.extend(crossref_search(query, limit))
        except Exception as exc:
            errors.append(f"Crossref: {exc}")

    # Prefer DOI as the deduplication key. Fall back to provider ID.
    unique = {}

    for row in rows:
        title = clean(row.get("title"))
        locator = clean(row.get("url_or_doi"))

        if not title or not locator:
            continue

        key = (
            "doi:" + row["doi_key"]
            if row.get("doi_key")
            else "url:" + locator.lower()
        )

        if key not in unique:
            unique[key] = row
        else:
            existing = unique[key]
            for field in ("abstract", "author", "organization"):
                if not clean(existing.get(field)) and clean(row.get(field)):
                    existing[field] = row[field]

            existing["provider"] = "; ".join(
                sorted(set(
                    existing["provider"].split("; ")
                    + row["provider"].split("; ")
                ))
            )

    return list(unique.values()), errors


def save_results(video_id: str, query: str, rows: list[dict]) -> Path:
    workspace = WORKSPACES / video_id
    workspace.mkdir(parents=True, exist_ok=True)

    output = workspace / "discovered_sources.csv"
    existing = []

    if output.exists():
        with output.open("r", encoding="utf-8-sig", newline="") as handle:
            existing = list(csv.DictReader(handle))

    existing_keys = {
        normalize_doi(row.get("url_or_doi"))
        or clean(row.get("provider_id")).lower()
        for row in existing
    }

    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    added = []

    for row in rows:
        key = (
            normalize_doi(row.get("url_or_doi"))
            or clean(row.get("provider_id")).lower()
        )

        if not key or key in existing_keys:
            continue

        added.append({
            "source_id": stable_id(key),
            "title": clean(row.get("title")),
            "author": clean(row.get("author")),
            "organization": clean(row.get("organization")),
            "published_date": clean(row.get("published_date")),
            "source_type": clean(row.get("source_type")),
            "url_or_doi": clean(row.get("url_or_doi")),
            "accessed_date": today,
            "source_review_status": "DISCOVERED",
            "notes": "Automatically discovered; not independently reviewed.",
            "provider": clean(row.get("provider")),
            "provider_id": clean(row.get("provider_id")),
            "abstract": clean(row.get("abstract")),
            "discovery_query": query,
            "discovered_at": now,
        })

        existing_keys.add(key)

    write_mode = "a" if output.exists() else "w"

    with output.open(
        write_mode,
        encoding="utf-8-sig",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if write_mode == "w":
            writer.writeheader()
        writer.writerows(added)

    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover academic sources without approving or verifying them."
    )
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument(
        "--provider",
        choices=("openalex", "crossref", "both"),
        default="both",
    )
    args = parser.parse_args()

    video_id = clean(args.video_id)
    query = clean(args.query)

    if not video_id or not query:
        parser.error("video-id and query must not be empty")

    if len(video_id) > 128 or len(query) > 500:
        parser.error("video-id or query exceeds the allowed length")

    if not 1 <= args.limit <= 25:
        parser.error("--limit must be between 1 and 25")

    rows, errors = discover(query, args.limit, args.provider)
    output = save_results(video_id, query, rows)

    print("=" * 60)
    print("ACADEMIC SOURCE DISCOVERY")
    print("=" * 60)
    print("Video ID:", video_id)
    print("Query:", query)
    print("Providers:", args.provider)
    print("Results discovered:", len(rows))
    print("Output:", output)
    print("Review status: DISCOVERED — NOT VERIFIED")
    print("Research approval: NOT GRANTED")
    print("Production approval: NOT GRANTED")
    print("Upload authorization: NOT GRANTED")

    if errors:
        print("\nPROVIDER ERRORS:")
        for error in errors:
            print("-", error)

    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
