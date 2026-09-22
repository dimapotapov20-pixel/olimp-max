from __future__ import annotations

import unittest

try:
    from parser.match_rsosh_candidates import RsoshProfile, candidate_identity_text, match_candidate_text
    from parser.collect_olympiads import parse_rsosh
except ModuleNotFoundError:
    from match_rsosh_candidates import RsoshProfile, candidate_identity_text, match_candidate_text
    from collect_olympiads import parse_rsosh


class RsoshMatcherTest(unittest.TestCase):
    def setUp(self) -> None:
        self.profiles = [
            RsoshProfile(11, "Всероссийская олимпиада школьников «Высшая проба»", "математика", 1),
            RsoshProfile(12, "Всероссийская олимпиада школьников «Высшая проба»", "информатика", 1),
            RsoshProfile(13, "Олимпиада школьников «Шаг в будущее»", "физика", 2),
        ]

    def test_resolves_title_and_profile(self) -> None:
        match = match_candidate_text("«Высшая проба» | I | математика | БВИ", self.profiles)
        self.assertEqual("resolved", match.status)
        self.assertEqual(11, match.profile.id)
        self.assertEqual("title_and_profile", match.reason)

    def test_keeps_title_with_several_profiles_ambiguous(self) -> None:
        match = match_candidate_text("Олимпиада «Высшая проба» даёт особое право", self.profiles)
        self.assertEqual("ambiguous", match.status)
        self.assertEqual({11, 12}, set(match.alternatives))

    def test_does_not_auto_resolve_a_single_profile_title(self) -> None:
        match = match_candidate_text("Шаг в будущее: право на прием без вступительных испытаний", self.profiles)
        self.assertEqual("unresolved", match.status)
        self.assertEqual("title_without_profile", match.reason)

    def test_does_not_match_a_generic_subject_without_title(self) -> None:
        match = match_candidate_text("Победителям по математике предоставляется БВИ", self.profiles)
        self.assertEqual("unresolved", match.status)

    def test_uses_a_pre_extracted_identity_from_a_multi_olympiad_row(self) -> None:
        candidate = {
            "raw_payload": {
                "kind": "table_row",
                "identity": {"olympiad_title": "Высшая проба", "profile_title": "математика"},
            }
        }
        self.assertEqual("Высшая проба | математика", candidate_identity_text(candidate))

    def test_reads_continuation_profiles_from_an_official_rowspan_table(self) -> None:
        markup = """
        <table class="mainTableInfo">
          <tr><td>5</td><td>Национальная технологическая олимпиада</td><td>геномное редактирование</td><td>биология</td><td>3</td></tr>
          <tr><td>инфохимия</td><td>информатика и химия</td><td>3</td></tr>
        </table>
        """
        records = parse_rsosh(markup)
        self.assertEqual(2, len(records))
        self.assertEqual("Национальная технологическая олимпиада", records[1]["title"])
        self.assertEqual("инфохимия", records[1]["profile"])

    def test_rejects_a_generic_title_nested_in_another_title(self) -> None:
        generic = [RsoshProfile(14, "Открытая олимпиада школьников", "информатика", 2)]
        match = match_candidate_text("Всесибирская открытая олимпиада школьников | информатика", generic)
        self.assertEqual("unresolved", match.status)

    def test_extracts_identity_only_from_named_table_columns(self) -> None:
        candidate = {
            "raw_payload": {
                "kind": "table_row",
                "headers": ["| Олимпиада | Профиль олимпиады | Льгота |"],
                "row": "| Высшая проба | биология | 100 баллов по математике |",
            }
        }
        self.assertEqual("Высшая проба | биология", candidate_identity_text(candidate))

    def test_keeps_identity_when_benefit_columns_have_extra_merged_cells(self) -> None:
        candidate = {
            "raw_payload": {
                "kind": "table_row",
                "headers": ["| № | Полное наименование олимпиады | Профиль олимпиады | Льгота |"],
                "row": "| 8 | Высшая проба | биология | 100 баллов | | |",
            }
        }
        self.assertEqual("Высшая проба | биология", candidate_identity_text(candidate))


if __name__ == "__main__":
    unittest.main()
