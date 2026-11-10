from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import socket
import time
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

BASE = Path('data/research/youtube_universe_v33')
WORKSPACE = BASE / 'research_workspace_v33'
MAX_BYTES = 5 * 1024 * 1024
TIMEOUT = 15
USER_AGENT = 'YouTubeResearchVerifier/1.0 (+source-verification; contact: local-user)'
REPORT_NAME = 'source_verification_v1.json'


def norm(text: str) -> str:
    return re.sub(r'\s+', ' ', html.unescape(str(text or ''))).strip().casefold()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_locator(locator: str) -> str:
    locator = str(locator or '').strip()
    if locator.lower().startswith('doi:'):
        doi = locator[4:].strip()
        if not doi or any(ch.isspace() for ch in doi):
            raise ValueError('INVALID_DOI')
        return 'https://doi.org/' + doi
    parsed = urlparse(locator)
    if parsed.scheme != 'https' or not parsed.hostname:
        raise ValueError('HTTPS_REQUIRED')
    return locator


def validate_public_host(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ''
    if parsed.scheme != 'https' or not host:
        raise ValueError('HTTPS_REQUIRED')
    if host.lower() in {'localhost', 'localhost.localdomain'} or host.endswith('.local'):
        raise ValueError('NON_PUBLIC_HOST_BLOCKED')
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError('DNS_LOOKUP_FAILED: ' + str(exc)) from exc
    for info in infos:
        ip = info[4][0]
        # Reject private, loopback, link-local, reserved and non-global destinations.
        import ipaddress
        address = ipaddress.ip_address(ip)
        if not address.is_global:
            raise ValueError('NON_PUBLIC_IP_BLOCKED')


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        validate_public_host(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


class TextExtractor(HTMLParser):
    SKIP = {'script', 'style', 'noscript', 'svg', 'nav', 'footer', 'header'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.SKIP:
            self.skip_depth += 1
        elif tag.lower() in {'p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'br'}:
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag.lower() in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag.lower() in {'p', 'div', 'li', 'h1', 'h2', 'h3', 'h4'}:
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.skip_depth:
            self.parts.append(data)


def fetch_source(locator: str) -> dict:
    requested = resolve_locator(locator)
    validate_public_host(requested)
    opener = build_opener(SafeRedirect())
    request = Request(requested, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xhtml+xml,application/pdf;q=0.8'})
    with opener.open(request, timeout=TIMEOUT) as response:
        final_url = response.geturl()
        validate_public_host(final_url)
        status = getattr(response, 'status', 200)
        content_type = response.headers.get_content_type().lower()
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError('SOURCE_EXCEEDS_5MB_LIMIT')
    if status < 200 or status >= 300:
        raise ValueError('HTTP_STATUS_' + str(status))
    raw_hash = sha256(body)
    if content_type in {'text/html', 'application/xhtml+xml'}:
        charset = 'utf-8'
        text = body.decode(charset, errors='replace')
        parser = TextExtractor()
        parser.feed(text)
        extracted = re.sub(r'\s+', ' ', ' '.join(parser.parts)).strip()
        method = 'stdlib_html_text_extraction'
    elif content_type == 'text/plain':
        extracted = body.decode('utf-8', errors='replace')
        method = 'plain_text'
    elif content_type == 'application/pdf' or final_url.lower().endswith('.pdf'):
        return {
            'status': 'HOLD_PDF_EXTRACTION_UNAVAILABLE', 'requested_url': requested,
            'final_url': final_url, 'http_status': status, 'content_type': content_type,
            'raw_sha256': raw_hash, 'extracted_text_sha256': '', 'extracted_characters': 0,
            'extraction_method': 'not_extracted', 'error': 'PDF extraction is not enabled in this standard-library verifier.'
        }
    else:
        raise ValueError('UNSUPPORTED_CONTENT_TYPE_' + content_type)
    if len(extracted) < 200:
        raise ValueError('INSUFFICIENT_EXTRACTED_TEXT')
    return {
        'status': 'FETCHED', 'requested_url': requested, 'final_url': final_url,
        'http_status': status, 'content_type': content_type, 'raw_sha256': raw_hash,
        'extracted_text_sha256': sha256(extracted.encode('utf-8')),
        'extracted_characters': len(extracted), 'extraction_method': method,
        '_text': extracted,
    }


def read_rows(path: Path) -> list[dict]:
    with path.open('r', encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))


def verify_video(video_id: str, workspace: Path = WORKSPACE) -> dict:
    folder = workspace / video_id
    source_path, evidence_path = folder / 'sources.csv', folder / 'evidence.csv'
    if not source_path.is_file() or not evidence_path.is_file():
        return {'schema_version': 1, 'video_id': video_id, 'status': 'HOLD', 'reason_codes': ['RESEARCH_FILES_MISSING'], 'sources': [], 'evidence': []}
    sources, evidence = read_rows(source_path), read_rows(evidence_path)
    source_results = {}
    for source in sources:
        sid = str(source.get('source_id', '')).strip()
        try:
            result = fetch_source(source.get('url_or_doi', ''))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, Exception) as exc:
            result = {'status': 'HOLD_FETCH_FAILED', 'error': f'{type(exc).__name__}: {exc}'}
        source_results[sid] = result
    evidence_results = []
    for item in evidence:
        eid = str(item.get('evidence_id', '')).strip()
        sid = str(item.get('source_id', '')).strip()
        passage = str(item.get('source_passage', '') or '').strip()
        source_result = source_results.get(sid, {})
        passage_ok = bool(passage) and source_result.get('status') == 'FETCHED' and norm(passage) in norm(source_result.get('_text', ''))
        evidence_results.append({
            'evidence_id': eid, 'claim_id': str(item.get('claim_id', '')).strip(),
            'source_id': sid, 'passage_supplied': bool(passage),
            'exact_passage_found': passage_ok,
            'status': 'PASS_EXACT_PASSAGE' if passage_ok else 'HOLD_PASSAGE_NOT_VERIFIED',
        })
    all_sources_fetched = bool(sources) and all(v.get('status') == 'FETCHED' for v in source_results.values())
    all_passages_verified = bool(evidence_results) and all(v['exact_passage_found'] for v in evidence_results)
    reason_codes = []
    if not all_sources_fetched:
        reason_codes.append('ONE_OR_MORE_SOURCES_NOT_FETCHED')
    if not all_passages_verified:
        reason_codes.append('EXACT_SOURCE_PASSAGE_NOT_VERIFIED')
    # Authenticating a quotation does not establish that it semantically entails a claim.
    reason_codes.append('SEMANTIC_ENTAILMENT_REQUIRES_REVIEW')
    public_sources = []
    for sid, result in source_results.items():
        public_sources.append({k: v for k, v in result.items() if k != '_text'} | {'source_id': sid})
    return {
        'schema_version': 1, 'video_id': video_id,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'status': 'HOLD', 'reason_codes': reason_codes,
        'all_sources_fetched': all_sources_fetched,
        'all_exact_passages_verified': all_passages_verified,
        'semantic_claim_verification': 'NOT_PERFORMED',
        'sources': public_sources, 'evidence': evidence_results,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Fetch sources and verify exact quoted passages; never grants research approval.')
    parser.add_argument('--video-id', required=True)
    args = parser.parse_args()
    report = verify_video(args.video_id)
    target = WORKSPACE / args.video_id / REPORT_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix('.json.tmp')
    temp.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temp.replace(target)
    print('Video:', args.video_id)
    print('Verification status:', report['status'])
    print('Reasons:', ', '.join(report['reason_codes']))
    print('Report:', target)


if __name__ == '__main__':
    main()
