#!/usr/bin/env python3
"""Find moved admission documents on allow-listed university sites.

This is intentionally a *discovery* worker, not a benefit parser. It follows a
small number of official pages, honours ``robots.txt``, scores links to rules
and olympiad appendices, and attaches only high-signal documents to the
generic review-candidate parser. A discovered URL can never publish a benefit
without a later exact programme-level match.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import deque
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

try:
    import requests
except ImportError:  # pragma: no cover - environment dependent
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - environment dependent
    BeautifulSoup = None

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
except ImportError:  # pragma: no cover - environment dependent
    psycopg = None
    dict_row = None
    Jsonb = None

try:
    from parser.crawl_admission_rules import USER_AGENT, allowed_host, compact, normalized
except ModuleNotFoundError:  # Allows `python parser/discover_official_sources.py`.
    from crawl_admission_rules import USER_AGENT, allowed_host, compact, normalized  # type: ignore


ADAPTER_CODE = "official-source-discovery-v1"
ADAPTER_VERSION = "2026.1"
MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_SITEMAP_URLS = 160
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid"}

# Weighting is intentionally explainable and conservative. A URL must contain
# both an olympiad/benefit signal and an admissions signal before it is attached
# to a parser target.
SIGNALS: tuple[tuple[str, tuple[str, ...], int], ...] = (
    ("admission_rules", ("правила приема", "правила приёма"), 24),
    ("olympiads", ("олимпиад", "рсош", "российского совета олимпиад"), 22),
    ("bvi", ("бви", "без вступительных испытаний"), 22),
    ("hundred_points", ("100 баллов", "100 балл"), 15),
    ("special_right", ("особые права", "особое право"), 14),
    ("admission", ("прием", "приём", "поступлен"), 8),
    ("appendix", ("приложение", "перечень соответствий"), 6),
)
HARD_SIGNALS = {"olympiads", "bvi", "hundred_points", "special_right"}
ADMISSION_SIGNALS = {"admission_rules", "admission", "appendix"}
SUPPORTED_KINDS = {"html", "pdf", "xlsx"}


@dataclass(frozen=True)
class DiscoveryTarget:
    id: int
    campaign_id: int
    university_location_id: int | None
    source_id: int
    seed_url: str
    source_base_url: str
    adapter_config: dict[str, Any]


@dataclass(frozen=True)
class DiscoveredCandidate:
    url: str
    document_kind: str
    title: str | None
    source_excerpt: str | None
    score: int
    signals: dict[str, int]


def canonical_url(value: str, base_url: str) -> str | None:
    """Resolve a link while rejecting non-web, credentialed and tracking URLs."""
    try:
        parsed = urlparse(urljoin(base_url, value))
        _ = parsed.port  # Raises on malformed ports.
    except ValueError:
        return None
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return None
    query = urlencode(
        [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in TRACKING_QUERY_KEYS and not key.lower().startswith("utm_")
        ],
        doseq=True,
    )
    path = parsed.path or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", query, ""))


def document_kind(url: str, content_type: str | None = None) -> str:
    media_type = (content_type or "").split(";", 1)[0].strip().lower()
    if media_type in {"text/html", "application/xhtml+xml"}:
        return "html"
    if media_type == "application/pdf" or urlparse(url).path.lower().endswith(".pdf"):
        return "pdf"
    if media_type in {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-excel",
    } or urlparse(url).path.lower().endswith((".xlsx", ".xls")):
        return "xlsx"
    return "other"


def linked_document_kind(url: str) -> str:
    """Treat an extensionless link as a page until its response says otherwise.

    Admission sites commonly use paths such as ``/rules`` or ``/documents``.
    Classifying those as ``other`` before fetching would make the bounded walk
    stop at its seed page. PDFs and spreadsheets remain terminal immediately.
    """
    kind = document_kind(url)
    return "html" if kind == "other" else kind


def score_candidate(url: str, *, title: str = "", excerpt: str = "", campaign_year: int = 2026) -> tuple[int, dict[str, int]]:
    """Return an explainable score from URL, anchor text and page metadata."""
    haystack = normalized(" ".join([url.replace("/", " ").replace("-", " "), title, excerpt]))
    signals: dict[str, int] = {}
    for name, phrases, weight in SIGNALS:
        matches = sum(phrase in haystack for phrase in phrases)
        if matches:
            signals[name] = matches
    score = sum(next(weight for key, _, weight in SIGNALS if key == name) for name in signals)
    if str(campaign_year) in haystack:
        signals["campaign_year"] = 1
        score += 12
    kind = document_kind(url)
    if kind in {"pdf", "xlsx"}:
        signals["document"] = 1
        score += 8
    return min(score, 100), signals


def attachable(candidate: DiscoveredCandidate, minimum_score: int) -> bool:
    signal_names = set(candidate.signals)
    return (
        candidate.document_kind in SUPPORTED_KINDS
        and candidate.score >= minimum_score
        and bool(signal_names & HARD_SIGNALS)
        and bool(signal_names & ADMISSION_SIGNALS)
    )


def extract_links(html: bytes, page_url: str, target: DiscoveryTarget) -> tuple[str, list[DiscoveredCandidate]]:
    if BeautifulSoup is None:
        raise RuntimeError("BeautifulSoup is not installed. Run: python3 -m pip install -r requirements-crawler.txt")
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "svg", "template"]):
        node.decompose()
    title = compact(soup.title.get_text(" ", strip=True)) if soup.title else ""
    heading = soup.find("h1")
    page_label = compact(" ".join(item for item in [title, heading.get_text(" ", strip=True) if heading else ""] if item))[:800]
    allowed_hosts = list(target.adapter_config.get("allow_hosts", []))
    links: list[DiscoveredCandidate] = []
    for anchor in soup.select("a[href]"):
        url = canonical_url(str(anchor.get("href", "")), page_url)
        if not url or not allowed_host(url, target.source_base_url, allowed_hosts):
            continue
        anchor_text = compact(anchor.get_text(" ", strip=True))[:800]
        score, signals = score_candidate(url, title=title, excerpt=anchor_text, campaign_year=target.adapter_config.get("campaign_year", 2026))
        links.append(
            DiscoveredCandidate(
                url=url,
                document_kind=linked_document_kind(url),
                title=title or None,
                source_excerpt=anchor_text or None,
                score=score,
                signals=signals,
            )
        )
    # Navigation menus repeat words such as “олимпиада” on every page.  The
    # page label is page-specific, unlike the full body, so it is safe to use
    # for a candidate score without turning every navigation link into a hit.
    return page_label, links


def sitemap_urls(xml: bytes, base_url: str, target: DiscoveryTarget) -> list[str]:
    """Read URL entries from a same-host sitemap; never follow external locs."""
    allowed_hosts = list(target.adapter_config.get("allow_hosts", []))
    urls: list[str] = []
    for raw_url in re.findall(rb"<loc>\s*(.*?)\s*</loc>", xml, flags=re.IGNORECASE | re.DOTALL):
        try:
            value = raw_url.decode("utf-8", errors="ignore")
        except UnicodeDecodeError:  # pragma: no cover - errors="ignore" handles it
            continue
        url = canonical_url(value, base_url)
        if url and allowed_host(url, target.source_base_url, allowed_hosts):
            urls.append(url)
        if len(urls) >= MAX_SITEMAP_URLS:
            break
    return urls


def robots_allowed(session: "requests.Session", url: str, cache: dict[str, RobotFileParser | None]) -> bool:
    parsed = urlparse(url)
    cache_key = f"{parsed.scheme}://{parsed.netloc}"
    if cache_key not in cache:
        parser = RobotFileParser()
        robots_url = f"{cache_key}/robots.txt"
        try:
            response = session.get(robots_url, timeout=(5, 15), headers={"User-Agent": USER_AGENT})
            if response.status_code == 200 and len(response.content) <= 512 * 1024:
                parser.parse(response.text.splitlines())
                cache[cache_key] = parser
            else:
                cache[cache_key] = None
        except requests.RequestException:
            cache[cache_key] = None
    parser = cache[cache_key]
    return True if parser is None else parser.can_fetch(USER_AGENT, url)


def fetch_public(session: "requests.Session", url: str, target: DiscoveryTarget) -> tuple[bytes, str, str]:
    allowed_hosts = list(target.adapter_config.get("allow_hosts", []))
    response = session.get(
        url,
        allow_redirects=True,
        timeout=(5, 30),
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;q=0.8,*/*;q=0.1"},
    )
    response.raise_for_status()
    response_url = str(response.url)
    final_url = canonical_url(response_url, url) or ""
    if not final_url or not allowed_host(final_url, target.source_base_url, allowed_hosts):
        raise ValueError(f"Official discovery page redirected to an unapproved host: {response_url}")
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError(f"Discovery response exceeds {MAX_RESPONSE_BYTES // 1024 // 1024} MB")
    return response.content, final_url, response.headers.get("content-type", "application/octet-stream")


def merge_candidate(candidates: dict[str, DiscoveredCandidate], candidate: DiscoveredCandidate) -> None:
    prior = candidates.get(candidate.url)
    if prior is None or candidate.score > prior.score:
        candidates[candidate.url] = candidate


def discover(target: DiscoveryTarget) -> tuple[int, list[DiscoveredCandidate]]:
    """Breadth-first discovery bounded by an explicit host, depth and page cap."""
    if requests is None:
        raise RuntimeError("requests is not installed. Run: python3 -m pip install -r requirements-crawler.txt")
    config = target.adapter_config
    max_pages = min(max(int(config.get("max_pages", 24)), 1), 60)
    max_depth = min(max(int(config.get("max_depth", 2)), 0), 3)
    allowed_hosts = list(config.get("allow_hosts", []))
    if not allowed_hosts or not allowed_host(target.seed_url, target.source_base_url, allowed_hosts):
        raise ValueError("Discovery seed must be HTTPS on an approved official host")

    queue: deque[tuple[str, int]] = deque([(target.seed_url, 0)])
    queued = {target.seed_url}
    visited: set[str] = set()
    candidates: dict[str, DiscoveredCandidate] = {}
    robots_cache: dict[str, RobotFileParser | None] = {}
    with requests.Session() as session:
        seed_parts = urlparse(target.seed_url)
        sitemap = f"{seed_parts.scheme}://{seed_parts.netloc}/sitemap.xml"
        if robots_allowed(session, sitemap, robots_cache):
            try:
                sitemap_body, _, sitemap_type = fetch_public(session, sitemap, target)
                if "xml" in sitemap_type or sitemap_body.lstrip().startswith(b"<"):
                    for url in sitemap_urls(sitemap_body, sitemap, target):
                        score, _ = score_candidate(url, campaign_year=config.get("campaign_year", 2026))
                        kind = linked_document_kind(url)
                        if kind in {"pdf", "xlsx"}:
                            sitemap_score, sitemap_signals = score_candidate(url, campaign_year=config.get("campaign_year", 2026))
                            merge_candidate(candidates, DiscoveredCandidate(url, kind, None, None, sitemap_score, sitemap_signals))
                        elif kind == "html" and score >= 8 and url not in queued:
                            queue.append((url, 1))
                            queued.add(url)
            except (requests.RequestException, ValueError):
                pass  # A missing sitemap must not make an official seed unusable.

        while queue and len(visited) < max_pages:
            url, depth = queue.popleft()
            if url in visited or not robots_allowed(session, url, robots_cache):
                continue
            visited.add(url)
            try:
                body, final_url, content_type = fetch_public(session, url, target)
            except (requests.RequestException, ValueError):
                # A website may link to a login gateway, an expired campaign
                # page or a rate-limited endpoint.  It must not prevent the
                # rest of the allow-listed official site from being checked.
                if url == target.seed_url:
                    raise
                continue
            kind = document_kind(final_url, content_type)
            if kind != "html":
                score, signals = score_candidate(final_url, campaign_year=config.get("campaign_year", 2026))
                merge_candidate(candidates, DiscoveredCandidate(final_url, kind, None, None, score, signals))
                continue
            page_label, links = extract_links(body, final_url, target)
            score, signals = score_candidate(final_url, title=page_label, campaign_year=config.get("campaign_year", 2026))
            merge_candidate(candidates, DiscoveredCandidate(final_url, kind, page_label or None, None, score, signals))
            for candidate in links:
                merge_candidate(candidates, candidate)
                if depth < max_depth and candidate.document_kind == "html" and candidate.score >= 8 and candidate.url not in queued:
                    queue.append((candidate.url, depth + 1))
                    queued.add(candidate.url)

    return len(visited), sorted(candidates.values(), key=lambda item: (-item.score, item.url))[:120]


def due_targets(connection: "psycopg.Connection", limit: int, *, force: bool, excluded_ids: tuple[int, ...]) -> list[DiscoveryTarget]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT target.id, target.admission_campaign_id AS campaign_id, target.university_location_id,
                   target.source_id, target.seed_url, source.base_url AS source_base_url, target.adapter_config
            FROM official_source_discovery_targets target
            JOIN sources source ON source.id = target.source_id
            WHERE target.is_active
              AND (%s OR target.next_check_at IS NULL OR target.next_check_at <= now())
              AND NOT target.id = ANY(%s)
              AND NOT EXISTS (
                SELECT 1 FROM official_source_discovery_runs running
                WHERE running.official_source_discovery_target_id = target.id
                  AND running.status = 'running'
                  AND running.started_at > now() - interval '1 hour'
              )
            ORDER BY target.next_check_at NULLS FIRST, target.id
            LIMIT %s
            FOR UPDATE OF target SKIP LOCKED
            """,
            (force, list(excluded_ids), limit),
        )
        return [DiscoveryTarget(**row) for row in cursor.fetchall()]


def start_run(connection: "psycopg.Connection", target: DiscoveryTarget) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO official_source_discovery_runs (official_source_discovery_target_id, status)
            VALUES (%s, 'running') RETURNING id
            """,
            (target.id,),
        )
        run_id = cursor.fetchone()["id"]
    connection.commit()
    return run_id


def persist_run(
    connection: "psycopg.Connection", target: DiscoveryTarget, run_id: int, pages_seen: int, candidates: list[DiscoveredCandidate]
) -> int:
    """Save the audit trail and attach only high-confidence official documents."""
    minimum_score = min(max(int(target.adapter_config.get("minimum_score", 38)), 1), 100)
    attached = 0
    max_attachments = min(max(int(target.adapter_config.get("max_attachments", 8)), 1), 20)
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*) AS active_count
            FROM admission_source_targets
            WHERE admission_campaign_id = %s
              AND is_active
              AND adapter_config->>'discovered_by' = %s
            """,
            (target.campaign_id, ADAPTER_CODE),
        )
        active_discovery_targets = cursor.fetchone()["active_count"]
        for candidate in candidates:
            cursor.execute(
                """
                INSERT INTO official_source_discovery_candidates (
                  official_source_discovery_run_id, url, document_kind, title, source_excerpt, score, signals
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    run_id,
                    candidate.url,
                    candidate.document_kind,
                    candidate.title,
                    candidate.source_excerpt,
                    candidate.score,
                    Jsonb(candidate.signals),
                ),
            )
            candidate_id = cursor.fetchone()["id"]
            if not attachable(candidate, minimum_score):
                cursor.execute("UPDATE official_source_discovery_candidates SET status = 'ignored' WHERE id = %s", (candidate_id,))
                continue
            cursor.execute(
                """
                SELECT id, is_active FROM admission_source_targets
                WHERE admission_campaign_id = %s AND url = %s
                """,
                (target.campaign_id, candidate.url),
            )
            existing = cursor.fetchone()
            if existing:
                if not existing["is_active"]:
                    if active_discovery_targets >= max_attachments:
                        continue
                    cursor.execute(
                        """
                        UPDATE admission_source_targets
                        SET university_location_id = %s, source_id = %s, source_role = 'benefits_table',
                            document_kind = %s, adapter_code = 'requests-bs4-keyword-v1', adapter_config = %s,
                            next_check_at = now(), is_active = TRUE, updated_at = now()
                        WHERE id = %s
                        """,
                        (
                            target.university_location_id,
                            target.source_id,
                            candidate.document_kind,
                            Jsonb(
                                {
                                    "allow_hosts": target.adapter_config.get("allow_hosts", []),
                                    "discovered_by": ADAPTER_CODE,
                                    "discovery_candidate_id": candidate_id,
                                }
                            ),
                            existing["id"],
                        ),
                    )
                    cursor.execute(
                        """
                        UPDATE official_source_discovery_candidates
                        SET status = 'attached', admission_source_target_id = %s
                        WHERE id = %s
                        """,
                        (existing["id"], candidate_id),
                    )
                    attached += 1
                    active_discovery_targets += 1
                    continue
                cursor.execute(
                    """
                    UPDATE official_source_discovery_candidates
                    SET status = 'already_tracked', admission_source_target_id = %s
                    WHERE id = %s
                    """,
                    (existing["id"], candidate_id),
                )
                continue
            if active_discovery_targets >= max_attachments:
                continue
            cursor.execute(
                """
                INSERT INTO admission_source_targets (
                  admission_campaign_id, university_location_id, source_id, url,
                  source_role, document_kind, adapter_code, adapter_config, next_check_at, is_active
                ) VALUES (%s, %s, %s, %s, 'benefits_table', %s, 'requests-bs4-keyword-v1', %s, now(), TRUE)
                RETURNING id
                """,
                (
                    target.campaign_id,
                    target.university_location_id,
                    target.source_id,
                    candidate.url,
                    candidate.document_kind,
                    Jsonb(
                        {
                            "allow_hosts": target.adapter_config.get("allow_hosts", []),
                            "discovered_by": ADAPTER_CODE,
                            "discovery_candidate_id": candidate_id,
                        }
                    ),
                ),
            )
            attached_target_id = cursor.fetchone()["id"]
            cursor.execute(
                """
                UPDATE official_source_discovery_candidates
                SET status = 'attached', admission_source_target_id = %s
                WHERE id = %s
                """,
                (attached_target_id, candidate_id),
            )
            attached += 1
            active_discovery_targets += 1
        cursor.execute(
            """
            UPDATE official_source_discovery_runs
            SET status = 'succeeded', pages_seen = %s, candidates_found = %s,
                targets_attached = %s, finished_at = now()
            WHERE id = %s
            """,
            (pages_seen, len(candidates), attached, run_id),
        )
        cursor.execute(
            """
            UPDATE official_source_discovery_targets
            SET last_checked_at = now(), next_check_at = now() + make_interval(hours => poll_interval_hours), updated_at = now()
            WHERE id = %s
            """,
            (target.id,),
        )
    connection.commit()
    return attached


def fail_run(connection: "psycopg.Connection", target: DiscoveryTarget, run_id: int, message: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE official_source_discovery_runs SET status = 'failed', error_message = %s, finished_at = now() WHERE id = %s",
            (message[:4_000], run_id),
        )
        cursor.execute(
            """
            UPDATE official_source_discovery_targets
            SET last_checked_at = now(), next_check_at = now() + make_interval(hours => poll_interval_hours), updated_at = now()
            WHERE id = %s
            """,
            (target.id,),
        )
    connection.commit()


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10, help="maximum due university sites to inspect")
    parser.add_argument("--force", action="store_true", help="ignore next_check_at for active targets")
    parser.add_argument("--dry-run", action="store_true", help="print candidates without writing runs or parser targets")
    return parser.parse_args()


def main() -> int:
    args = arguments()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL is required", file=sys.stderr)
        return 2
    if psycopg is None or requests is None or BeautifulSoup is None:
        print("Install dependencies first: python3 -m pip install -r requirements-crawler.txt", file=sys.stderr)
        return 2
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        processed_ids: set[int] = set()
        processed = 0
        errors = 0
        while processed < args.limit:
            targets = due_targets(connection, 1, force=args.force, excluded_ids=tuple(processed_ids) if args.force else ())
            if not targets:
                if processed == 0:
                    print("No due official discovery targets.")
                break
            target = targets[0]
            processed += 1
            processed_ids.add(target.id)
            try:
                pages_seen, candidates = discover(target)
                if args.dry_run:
                    print(f"target {target.id}: {pages_seen} pages; {len(candidates)} candidates")
                    for candidate in candidates[:8]:
                        print(f"  {candidate.score:>3} {candidate.document_kind:<4} {candidate.url}")
                    continue
                run_id = start_run(connection, target)
                attached = persist_run(connection, target, run_id, pages_seen, candidates)
                print(f"target {target.id}: {pages_seen} pages; {len(candidates)} candidates; {attached} parser targets attached")
            except (requests.RequestException, OSError, RuntimeError, ValueError) as error:
                errors += 1
                if not args.dry_run:
                    run_id = start_run(connection, target)
                    fail_run(connection, target, run_id, str(error))
                print(f"target {target.id}: discovery failed — {error}", file=sys.stderr)
    # A blocked page on one university site is recorded on its target and does
    # not make the whole daily refresh look failed after other sites completed.
    return 1 if processed and processed == errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
