from __future__ import annotations

import unittest

try:
    from parser.strict_admission_adapters import strict_rules
except ModuleNotFoundError:
    from strict_admission_adapters import strict_rules


class StrictAdmissionAdapterTest(unittest.TestCase):
    def test_mephi_expands_explicit_programme_codes_and_both_statuses(self) -> None:
        markdown = """
        Победители и призёры олимпиад школьников обладают особыми правами.
        | № | Полное наименование олимпиады | Уровень | Поступление БВИ | Засчитывание 100 баллов по общеобразовательному предмету | Общеобразовательный предмет | Профиль олимпиады |
        | --- | --- | --- | --- | --- | --- | --- |
        | 8 | Всероссийская олимпиада школьников «Высшая проба» | II | 12.03.04, 18.03.01 | 41.03.05 | химия | химия |
        """
        rules = strict_rules("strict-mephi-2026-v1", markdown)
        self.assertEqual(6, len(rules))
        self.assertEqual({"12.03.04", "18.03.01", "41.03.05"}, {rule.programme_selector for rule in rules})
        self.assertEqual({"winner", "prize_winner"}, {rule.diploma_status for rule in rules})
        self.assertEqual({"bvi", "hundred_points"}, {rule.benefit_kind for rule in rules})
        self.assertEqual("chemistry", next(rule.confirmation_subject_code for rule in rules if rule.benefit_kind == "bvi"))

    def test_requires_an_explicit_profile(self) -> None:
        markdown = """
        | Олимпиада | Поступление БВИ | Диплом |
        | --- | --- | --- |
        | Высшая проба | 01.03.02 | Победитель |
        """
        self.assertEqual([], strict_rules("strict-mephi-2026-v1", markdown))

    def test_does_not_expand_all_programmes_phrase(self) -> None:
        markdown = """
        | Программа | Олимпиада | Профиль олимпиады | Льгота | Диплом |
        | --- | --- | --- | --- |
        | Все направления подготовки | Высшая проба | математика | БВИ | Победитель |
        """
        self.assertEqual([], strict_rules("strict-hse-2026-v1", markdown))

    def test_reads_one_standard_complete_row(self) -> None:
        markdown = """
        | Образовательная программа | Наименование олимпиады | Профиль олимпиады | Предоставляемая льгота | Диплом | Предмет подтверждения |
        | --- | --- | --- | --- | --- |
        | Прикладная математика | Высшая проба | математика | БВИ | Призёр | математика |
        """
        rules = strict_rules("strict-mipt-2026-v1", markdown)
        self.assertEqual(1, len(rules))
        self.assertEqual("Прикладная математика", rules[0].programme_selector)
        self.assertEqual("prize_winner", rules[0].diploma_status)
        self.assertEqual("math", rules[0].confirmation_subject_code)

    def test_hse_inherits_programme_and_olympiad_across_pdf_rows(self) -> None:
        markdown = """
        | Наименование образовательной программы | Полное наименование олимпиады | Профиль олимпиады | Один или несколько предметов, по которым поступающим необходимы результаты ЕГЭ | Количество баллов ЕГЭ | Вид особого права | Кому предоставляется особое право |
        | --- | --- | --- | --- | --- | --- | --- |
        | Направление подготовки 03.03.02 Физика |  |  |  |  |  |  |
        |  | Высшая проба | математика | математика | 80 и более | Право на 100 баллов | Победителям и призерам |
        |  |  | физика | физика | 80 и более | Право на прием БВИ | Победителям |
        """
        rules = strict_rules("strict-hse-2026-v1", markdown)
        self.assertEqual(3, len(rules))
        self.assertEqual({"03.03.02"}, {rule.programme_selector for rule in rules})
        self.assertEqual({"math", "physics"}, {rule.confirmation_subject_code for rule in rules})
        self.assertEqual({"winner", "prize_winner"}, {rule.diploma_status for rule in rules if rule.profile_title == "математика"})


if __name__ == "__main__":
    unittest.main()
