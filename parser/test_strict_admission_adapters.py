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
        rules = strict_rules("strict-hse-2026-v1", markdown)
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

    def test_msu_splits_only_named_olympiads_and_inherits_programme(self) -> None:
        markdown = """
        Особые права поступающим в МГУ в 2026 году.
        | Направление подготовки (специальность) | Профиль олимпиады | Общеобразовательные предметы или специальность(и) | Перечень олимпиад, на которые распространяется особое право | Уровень олимпиад | Класс | Победитель/ призер олимпиады | Общеобразовательный предмет, по которому необходимо наличие результатов ЕГЭ не менее 75 баллов | Предоставляемая льгота |
        | --- | --- | --- | --- | --- | --- | --- | --- | --- |
        | Прикладная математика | Математика | Математика | Московская олимпиада школьников, Олимпиада школьников «Ломоносов» | I | 11 | Победитель, призер | Математика | Зачисление без вступительных испытаний |
        |  | Информатика | Информатика | Всероссийская олимпиада школьников «Высшая проба» | I | 11 | Победитель | Информатика | Максимальное количество баллов по ЕГЭ по информатике |
        |  | Физика | Физика | * | I | 11 | Победитель | Физика | Зачисление без вступительных испытаний |
        """
        rules = strict_rules("strict-msu-2026-v2", markdown)
        self.assertEqual(5, len(rules))
        self.assertEqual({"Московская олимпиада школьников", "Олимпиада школьников «Ломоносов»", "Всероссийская олимпиада школьников «Высшая проба»"}, {rule.olympiad_title for rule in rules})
        self.assertNotIn("*", {rule.olympiad_title for rule in rules})
        self.assertTrue(all(rule.programme_selector == "Прикладная математика" for rule in rules))
        self.assertEqual(75, rules[0].confirmation_min_score)

    def test_bmstu_bvi_uses_explicit_direction_scope_only(self) -> None:
        markdown = """
        Приложение 5.1. Право поступления без вступительных испытаний в 2026 году.
        | № | Полное наименование олимпиады | Профиль олимпиады | Направление | Уровень | Предмет | Для победителей | Для призеров |
        | --- | --- | --- | --- | --- | --- | --- |
        | Для направлений: 01.03.02, 09.03.04 |  |  |  |  |  |  |  |
        | 8 | Всероссийская олимпиада школьников «Высшая проба» | информатика | информатика | I | информатика | Предоставляется | Не предоставляется |
        """
        rules = strict_rules("strict-bmstu-bvi-2026-v1", markdown)
        self.assertEqual(2, len(rules))
        self.assertEqual({"01.03.02", "09.03.04"}, {rule.programme_selector for rule in rules})
        self.assertEqual({"winner"}, {rule.diploma_status for rule in rules})
        self.assertEqual({"bvi"}, {rule.benefit_kind for rule in rules})
        self.assertTrue(all(rule.confirmation_min_score == 75 for rule in rules))

    def test_mipt_and_bmstu_hundred_wait_for_official_programme_mapping(self) -> None:
        self.assertEqual(
            [],
            strict_rules(
                "strict-mipt-2026-v2",
                "Перечень по физтех-школам и конкурсным группам МФТИ в 2026 году",
            ),
        )
        self.assertEqual(
            [],
            strict_rules(
                "strict-bmstu-100-2026-v1",
                "Приложение 5.3: особое право на 100 баллов в 2026 году",
            ),
        )


if __name__ == "__main__":
    unittest.main()
