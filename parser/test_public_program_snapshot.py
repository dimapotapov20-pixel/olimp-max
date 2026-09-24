from __future__ import annotations

import unittest

try:
    from parser.export_public_programs import build_payload
except ModuleNotFoundError:  # pragma: no cover - direct invocation from parser/
    from export_public_programs import build_payload


def programme(**changes):
    value = {
        "university_code": "msu",
        "university_location_code": "msu-moscow",
        "external_code": None,
        "programme_name": "Прикладная математика и информатика",
        "catalogue_status": "named_verified",
        "degree_level": "bachelor",
        "verified_benefits_count": 3,
        "source_url": "https://example.test/rules.pdf",
        "checked_at": "2026-09-24",
    }
    value.update(changes)
    return value


class PublicProgrammeSnapshotTest(unittest.TestCase):
    def test_exports_only_public_programme_fields(self) -> None:
        payload = build_payload([programme()], 2026, "2026-09-24")
        exported = payload["programmes"][0]
        self.assertEqual("msu-moscow", exported["university_location_code"])
        self.assertEqual("Прикладная математика и информатика", exported["programme_name"])
        self.assertNotIn("raw_payload", exported)

    def test_code_only_requires_full_direction_code(self) -> None:
        payload = build_payload(
            [programme(external_code="09.03.04", programme_name="Направление 09.03.04", catalogue_status="code_only")],
            2026,
            "2026-09-24",
        )
        self.assertEqual("09.03.04", payload["programmes"][0]["external_code"])
        with self.assertRaisesRegex(ValueError, "full direction code"):
            build_payload(
                [programme(external_code="09.03", programme_name="Направление 09.03", catalogue_status="code_only")],
                2026,
                "2026-09-24",
            )


if __name__ == "__main__":
    unittest.main()
