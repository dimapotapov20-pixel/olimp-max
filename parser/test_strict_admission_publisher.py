from __future__ import annotations

import unittest

try:
    from parser.publish_strict_admission_rules import Programme, complete, degree_level_for_direction, direction_code, official_named_scope, programme_match
except ModuleNotFoundError:
    from publish_strict_admission_rules import Programme, complete, degree_level_for_direction, direction_code, official_named_scope, programme_match


class StrictAdmissionPublisherTest(unittest.TestCase):
    def test_matches_only_one_exact_programme_code(self) -> None:
        programmes = [
            Programme(1, "01.03.02", "Прикладная математика"),
            Programme(2, "09.03.04", "Программная инженерия"),
        ]
        self.assertEqual(2, programme_match("09.03.04", programmes).id)
        self.assertIsNone(programme_match("09.03", programmes))

    def test_does_not_choose_between_duplicate_programme_names(self) -> None:
        programmes = [
            Programme(1, "01.03.02", "Прикладная математика"),
            Programme(2, "01.03.03", "Прикладная математика"),
        ]
        self.assertIsNone(programme_match("Прикладная математика", programmes))

    def test_requires_every_identity_field_for_auto_publication(self) -> None:
        candidate = {
            "confidence": 100,
            "university_location_id": 4,
            "raw_programme_name": "01.03.02",
            "raw_olympiad_name": "Высшая проба",
            "raw_profile_name": "математика",
            "suggested_diploma_status": "winner",
            "suggested_benefit_kind": "bvi",
        }
        self.assertIsNone(complete(candidate))
        candidate["raw_profile_name"] = None
        self.assertEqual("missing_explicit_identity", complete(candidate))

    def test_accepts_only_a_full_official_direction_code_for_code_scope(self) -> None:
        self.assertEqual("38.03.01", direction_code("38.03.01"))
        self.assertIsNone(direction_code("38.03"))
        self.assertIsNone(direction_code("все направления"))

    def test_direction_code_marks_specialist_level(self) -> None:
        self.assertEqual("bachelor", degree_level_for_direction("09.03.04"))
        self.assertEqual("specialist", degree_level_for_direction("10.05.03"))

    def test_accepts_named_scope_only_from_msu_programme_first_row(self) -> None:
        candidate = {
            "adapter_code": "strict-msu-2026-v2",
            "raw_programme_name": "Фундаментальные математика и механика",
            "raw_payload": {"kind": "msu_programme_table_row"},
        }
        self.assertEqual("Фундаментальные математика и механика", official_named_scope(candidate))
        candidate["raw_programme_name"] = "Группа программ «Физико-химическая биология»"
        self.assertIsNone(official_named_scope(candidate))
        candidate["raw_programme_name"] = "Прикладная математика"
        candidate["adapter_code"] = "strict-mipt-2026-v2"
        self.assertIsNone(official_named_scope(candidate))


if __name__ == "__main__":
    unittest.main()
