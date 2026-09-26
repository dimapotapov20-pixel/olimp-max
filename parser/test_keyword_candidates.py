from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

try:  # ``python -m unittest`` from the repository root
    from parser.crawl_admission_rules import find_candidates, html_to_markdown
except ModuleNotFoundError:  # direct execution from ``parser/``
    from crawl_admission_rules import find_candidates, html_to_markdown


class KeywordCandidatesTest(unittest.TestCase):
    def test_keeps_a_relevant_table_row_and_infers_a_confirmation_threshold(self) -> None:
        markdown = """
        ## Особые права для победителей и призеров олимпиад
        | Олимпиада | Профиль | Льгота |
        | --- | --- | --- |
        | Высшая проба | математика | 100 баллов по математике при ЕГЭ 75 баллов |
        """
        candidates = find_candidates(markdown, "a" * 64)
        self.assertEqual(1, len(candidates))
        candidate = candidates[0]
        self.assertEqual("hundred_points", candidate.suggested_benefit_kind)
        self.assertEqual("math", candidate.suggested_confirmation_subject_code)
        self.assertEqual(75, candidate.suggested_confirmation_min_score)
        self.assertEqual("markdown:line:4", candidate.source_locator)

    def test_ambiguous_winner_and_prize_winner_is_left_for_review(self) -> None:
        markdown = """
        Победителям и призерам олимпиад школьников предоставляется БВИ по соответствующему профилю.
        """
        candidate = find_candidates(markdown, "b" * 64)[0]
        self.assertEqual("bvi", candidate.suggested_benefit_kind)
        self.assertIsNone(candidate.suggested_diploma_status)

    def test_uses_a_later_pdf_header_after_a_faculty_row(self) -> None:
        markdown = """
        ## Страница 2
        | МЕХАНИКО-МАТЕМАТИЧЕСКИЙ ФАКУЛЬТЕТ | | | |
        | Направление | Профиль олимпиады | Перечень олимпиад | Предоставляемая льгота |
        | Математика | математика | Олимпиада «Ломоносов» | БВИ |
        """
        candidates = find_candidates(markdown, "c" * 64)
        self.assertEqual(1, len(candidates))
        self.assertIn("Профиль олимпиады", candidates[0].raw_payload["headers"][0])
        self.assertIn("Олимпиада «Ломоносов»", candidates[0].raw_payload["row"])

    def test_splits_a_named_olympiad_list_into_review_candidates(self) -> None:
        markdown = """
        | Направление | Профиль олимпиады | Перечень олимпиад | Предоставляемая льгота |
        | Математика | математика | Московская олимпиада школьников, Олимпиада школьников «Ломоносов» | БВИ |
        """
        candidates = find_candidates(markdown, "d" * 64)
        self.assertEqual(2, len(candidates))
        titles = {item.raw_olympiad_name for item in candidates}
        self.assertEqual({"Московская олимпиада школьников", "Олимпиада школьников «Ломоносов»"}, titles)

    def test_inherits_a_rowspan_olympiad_title_for_the_next_profile(self) -> None:
        markdown = """
        | Полное наименование олимпиады | Профиль олимпиады | Льгота |
        | Всероссийская олимпиада школьников «Высшая проба» | математика | 100 баллов |
        | | физика | БВИ |
        """
        candidates = find_candidates(markdown, "e" * 64)
        identities = {(item.raw_olympiad_name, item.raw_profile_name) for item in candidates}
        self.assertEqual(
            {
                ("Всероссийская олимпиада школьников «Высшая проба»", "математика"),
                ("Всероссийская олимпиада школьников «Высшая проба»", "физика"),
            },
            identities,
        )

    def test_auto_confirms_only_a_table_with_all_explicit_admission_fields(self) -> None:
        markdown = """
        | Программа | Олимпиада | Профиль олимпиады | Победители | Призёры | БВИ | Подтверждающий предмет | Минимальный балл |
        | --- | --- | --- | --- | --- | --- | --- | --- |
        | 09.03.04 | Олимпиада школьников «Высшая проба» | информатика | предоставляется | предоставляется | предоставляется | информатика | 75 |
        """
        candidates = find_candidates(markdown, "f" * 64)
        self.assertEqual(2, len(candidates))
        self.assertTrue(all(candidate.confidence == 100 for candidate in candidates))
        self.assertEqual({"winner", "prize_winner"}, {candidate.suggested_diploma_status for candidate in candidates})
        self.assertTrue(all(candidate.suggested_benefit_kind == "bvi" for candidate in candidates))
        self.assertTrue(all(candidate.raw_programme_name == "09.03.04" for candidate in candidates))
        self.assertTrue(all(candidate.raw_payload["kind"] == "automatic_explicit_table_row" for candidate in candidates))

    def test_does_not_auto_confirm_a_table_without_diploma_status(self) -> None:
        markdown = """
        | Программа | Олимпиада | Профиль олимпиады | Льгота |
        | --- | --- | --- | --- |
        | 09.03.04 | Олимпиада школьников «Высшая проба» | информатика | БВИ |
        """
        candidates = find_candidates(markdown, "g" * 64)
        self.assertEqual(1, len(candidates))
        self.assertEqual(72, candidates[0].confidence)

    def test_html_reader_retains_a_benefit_table(self) -> None:
        html = """
        <h2>Особые права олимпиадников</h2>
        <table><tr><th>Олимпиада</th><th>Льгота</th></tr>
        <tr><td>Турнир</td><td>БВИ для победителей</td></tr></table>
        <script>window.unrelated = true</script>
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "benefits.html"
            path.write_text(html, encoding="utf-8")
            markdown = html_to_markdown(path)
        self.assertIn("## Особые права олимпиадников", markdown)
        self.assertIn("| Турнир | БВИ для победителей |", markdown)
        self.assertNotIn("unrelated", markdown)


if __name__ == "__main__":
    unittest.main()
