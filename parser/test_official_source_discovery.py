from __future__ import annotations

import unittest

try:
    import bs4  # noqa: F401
except ModuleNotFoundError:
    BS4_AVAILABLE = False
else:
    BS4_AVAILABLE = True

try:
    from parser.discover_official_sources import (
        DiscoveredCandidate,
        DiscoveryTarget,
        HARD_SIGNALS,
        attachable,
        canonical_url,
        extract_links,
        score_candidate,
        sitemap_urls,
    )
except ModuleNotFoundError:  # Allows `python parser/test_official_source_discovery.py`.
    from discover_official_sources import (  # type: ignore
        DiscoveredCandidate,
        DiscoveryTarget,
        HARD_SIGNALS,
        attachable,
        canonical_url,
        extract_links,
        score_candidate,
        sitemap_urls,
    )


TARGET = DiscoveryTarget(
    id=1,
    campaign_id=1,
    university_location_id=1,
    source_id=1,
    seed_url="https://admission.example.edu/2026/",
    source_base_url="https://admission.example.edu/2026/",
    adapter_config={"allow_hosts": ["example.edu"], "campaign_year": 2026},
)


class OfficialSourceDiscoveryTests(unittest.TestCase):
    def test_canonical_url_keeps_official_path_and_removes_tracking(self) -> None:
        self.assertEqual(
            canonical_url("/docs/rules.pdf?utm_source=menu&id=7#appendix", TARGET.seed_url),
            "https://admission.example.edu/docs/rules.pdf?id=7",
        )
        self.assertIsNone(canonical_url("https://user:secret@example.edu/rules.pdf", TARGET.seed_url))
        self.assertIsNone(canonical_url("javascript:alert(1)", TARGET.seed_url))

    def test_score_requires_benefit_and_admission_signals(self) -> None:
        score, signals = score_candidate(
            "https://admission.example.edu/files/rules-2026.pdf",
            title="Правила приёма 2026",
            excerpt="Приложение: перечень олимпиад РСОШ для БВИ",
        )
        candidate = DiscoveredCandidate(
            url="https://admission.example.edu/files/rules-2026.pdf",
            document_kind="pdf",
            title="Правила приёма 2026",
            source_excerpt="Приложение: перечень олимпиад РСОШ для БВИ",
            score=score,
            signals=signals,
        )
        self.assertGreaterEqual(score, 38)
        self.assertTrue(attachable(candidate, 38))

    @unittest.skipUnless(BS4_AVAILABLE, "beautifulsoup4 is installed in the crawler image")
    def test_links_are_scoped_to_the_official_allow_list(self) -> None:
        _, links = extract_links(
            """
            <html><title>Admission</title><body>
              <a href="/files/rules-2026.pdf">Правила приема: РСОШ и БВИ</a>
              <a href="https://not-example.org/rules.pdf">external</a>
            </body></html>
            """.encode("utf-8"),
            TARGET.seed_url,
            TARGET,
        )
        self.assertEqual([item.url for item in links], ["https://admission.example.edu/files/rules-2026.pdf"])
        self.assertEqual(links[0].document_kind, "pdf")
        self.assertTrue(attachable(links[0], 38))

    @unittest.skipUnless(BS4_AVAILABLE, "beautifulsoup4 is installed in the crawler image")
    def test_extensionless_official_links_are_walked_as_pages(self) -> None:
        _, links = extract_links(
            '<a href="/admission/rules">Правила приема и олимпиады</a>'.encode("utf-8"),
            TARGET.seed_url,
            TARGET,
        )
        self.assertEqual(links[0].document_kind, "html")

    @unittest.skipUnless(BS4_AVAILABLE, "beautifulsoup4 is installed in the crawler image")
    def test_navigation_text_does_not_promote_every_page_to_a_benefit_source(self) -> None:
        page_label, links = extract_links(
            """
            <html><title>Приемная комиссия</title><body>
              <nav>Олимпиады РСОШ БВИ Правила приема</nav>
              <h1>Контакты</h1><a href="/contacts">Контакты</a>
            </body></html>
            """.encode("utf-8"),
            TARGET.seed_url,
            TARGET,
        )
        score, signals = score_candidate("https://admission.example.edu/contacts", title=page_label)
        self.assertEqual(page_label, "Приемная комиссия Контакты")
        self.assertFalse(bool(set(signals) & HARD_SIGNALS))
        self.assertFalse(attachable(DiscoveredCandidate(links[0].url, "html", page_label, None, score, signals), 38))

    def test_sitemap_rejects_foreign_hosts(self) -> None:
        entries = sitemap_urls(
            """
            <urlset>
              <url><loc>https://admission.example.edu/files/rules-2026.pdf</loc></url>
              <url><loc>https://not-example.org/files/rules-2026.pdf</loc></url>
            </urlset>
            """.encode("utf-8"),
            "https://admission.example.edu/sitemap.xml",
            TARGET,
        )
        self.assertEqual(entries, ["https://admission.example.edu/files/rules-2026.pdf"])


if __name__ == "__main__":
    unittest.main()
