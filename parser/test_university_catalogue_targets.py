from __future__ import annotations

import unittest

try:
    from parser.configure_university_catalogue_targets import SOURCES, TARGETS
    from parser.university_catalogue_adapters import supported_codes
except ModuleNotFoundError:  # pragma: no cover - direct invocation from parser/
    from configure_university_catalogue_targets import SOURCES, TARGETS
    from university_catalogue_adapters import supported_codes


class UniversityCatalogueTargetTest(unittest.TestCase):
    def test_every_target_uses_one_registered_adapter_and_official_host(self) -> None:
        source_codes = {source[0] for source in SOURCES}
        adapter_codes = set(supported_codes())
        for source_code, _university, _location, url, kind, adapter_code, hosts in TARGETS:
            self.assertIn(source_code, source_codes)
            self.assertIn(adapter_code, adapter_codes)
            self.assertEqual("https", url.split(":", 1)[0])
            self.assertIn(kind, {"html", "pdf", "xlsx"})
            self.assertTrue(hosts)

    def test_one_catalogue_target_is_scoped_to_one_location(self) -> None:
        locations = [(university, location, url) for _source, university, location, url, *_ in TARGETS]
        self.assertEqual(len(locations), len(set(locations)))

    def test_branch_sources_are_not_relabelled_as_head_campus_sources(self) -> None:
        configured_locations = {location for _source, _university, location, *_ in TARGETS}
        self.assertIn("bmstu-kaluga", configured_locations)
        self.assertIn("mirea-stavropol", configured_locations)
        self.assertNotIn("bmstu-moscow", configured_locations)
        self.assertNotIn("mirea-moscow", configured_locations)


if __name__ == "__main__":
    unittest.main()
