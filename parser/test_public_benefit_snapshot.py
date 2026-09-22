from __future__ import annotations

import unittest

try:
    from parser.export_public_benefits import build_payload
except ModuleNotFoundError:
    from export_public_benefits import build_payload


def reviewed_rule(**overrides: object) -> dict[str, object]:
    rule: dict[str, object] = {
        "university_code": "hse",
        "university_location_code": "hse-moscow",
        "programme_name": "Прикладная математика",
        "olympiad_title": "Олимпиада школьников «Высшая проба»",
        "profile_title": "математика",
        "olympiad_level": 1,
        "diploma_status": "prize_winner",
        "benefit_kind": "bvi",
        "point_value": None,
        "confirmation_subject_name": "Математика",
        "confirmation_min_score": 75,
        "source_url": "https://example.edu/rules",
        "source_locator": "table:4,row:8",
        "checked_at": "2026-09-22",
        "internal_candidate_text": "must not be exported",
    }
    rule.update(overrides)
    return rule


class PublicBenefitSnapshotTest(unittest.TestCase):
    def test_exports_only_public_contract_fields(self) -> None:
        payload = build_payload([reviewed_rule()], 2026, "2026-09-22")
        self.assertEqual(2026, payload["campaign"])
        exported = payload["rules"][0]
        self.assertEqual("hse-moscow", exported["university_location_code"])
        self.assertNotIn("internal_candidate_text", exported)

    def test_requires_a_specific_location(self) -> None:
        with self.assertRaisesRegex(ValueError, "university_location_code"):
            build_payload([reviewed_rule(university_location_code="")], 2026, "2026-09-22")

    def test_rejects_points_on_bvi(self) -> None:
        with self.assertRaisesRegex(ValueError, "Only individual achievement"):
            build_payload([reviewed_rule(point_value=5)], 2026, "2026-09-22")

    def test_accepts_valid_individual_points(self) -> None:
        payload = build_payload(
            [reviewed_rule(benefit_kind="individual_points", point_value=6)],
            2026,
            "2026-09-22",
        )
        self.assertEqual(6, payload["rules"][0]["point_value"])


if __name__ == "__main__":
    unittest.main()
