from __future__ import annotations

import unittest

try:
    from parser.university_catalogue_adapters import catalogue_programmes
except ModuleNotFoundError:  # pragma: no cover - direct invocation from parser/
    from university_catalogue_adapters import catalogue_programmes


class UniversityCatalogueAdaptersTest(unittest.TestCase):
    def test_hse_keeps_named_programme_without_guessed_code(self) -> None:
        markdown = """
        # НИУ ВШЭ (г. Москва)
        | Образовательная программа | Бюджетные места |
        | --- | --- |
        | Совместный бакалавриат НИУ ВШЭ и ЦПМ | 25 |
        """
        programmes = catalogue_programmes("catalogue-hse-2026-v1", markdown)
        self.assertEqual(1, len(programmes))
        self.assertIsNone(programmes[0].external_code)
        self.assertEqual("Совместный бакалавриат НИУ ВШЭ и ЦПМ", programmes[0].name)

    def test_mipt_preserves_programme_title_from_its_own_column(self) -> None:
        markdown = """
        | Подразделение | Образовательные программы | Конкурсная группа |
        | --- | --- | --- |
        | 01.03.02 Прикладная математика и информатика | 180 |  | 
        | ФПМИ | Прикладная математика и информатика | Компьютерные технологии |
        """
        programmes = catalogue_programmes("catalogue-mipt-2026-v1", markdown)
        self.assertEqual(["Прикладная математика и информатика"], [item.name for item in programmes])

    def test_mephi_uses_code_and_educational_programme(self) -> None:
        markdown = """
        # Приемная комиссия НИЯУ МИФИ
        | Код | Название направления / специальности | Образовательная программа |
        | --- | --- | --- |
        | 09.03.04 | Программная инженерия | Разработка программных систем |
        """
        programmes = catalogue_programmes("catalogue-mephi-2026-v1", markdown)
        self.assertEqual(1, len(programmes))
        self.assertEqual("09.03.04", programmes[0].external_code)
        self.assertEqual("Разработка программных систем", programmes[0].name)

    def test_msu_drops_faculty_prefix_before_direction_code(self) -> None:
        markdown = """
        # МГУ имени М. В. Ломоносова
        | Факультет, направление подготовки (специальность), образовательная программа | Места |
        | --- | --- |
        | Механико-математический факультет, 01.03.02 Прикладная математика и информатика | 50 |
        """
        programmes = catalogue_programmes("catalogue-msu-2026-v1", markdown)
        self.assertEqual(1, len(programmes))
        self.assertEqual("01.03.02", programmes[0].external_code)
        self.assertEqual("Прикладная математика и информатика", programmes[0].name)

    def test_bmstu_mai_and_mirea_use_their_own_formats(self) -> None:
        bmstu = """
        # МГТУ им. Н. Э. Баумана
        | Код, наименование направления подготовки | Квалификация |
        | --- | --- |
        | 09.03.01 Информатика и вычислительная техника | Высшее образование |
        """
        mai = """
        # Приёмная комиссия МАИ
        ## Прикладная математика и информатика
        01.03.02
        """
        mirea = """
        # Филиал РТУ МИРЭА в г. Ставрополе
        | Код | Наименование направления подготовки |
        | --- | --- |
        | 09.03.01 | Информатика и вычислительная техника |
        """
        self.assertEqual("Информатика и вычислительная техника", catalogue_programmes("catalogue-bmstu-2026-v1", bmstu)[0].name)
        self.assertEqual("Прикладная математика и информатика", catalogue_programmes("catalogue-mai-2026-v1", mai)[0].name)
        self.assertEqual("09.03.01", catalogue_programmes("catalogue-mirea-2026-v1", mirea)[0].external_code)

    def test_mai_card_catalogue_keeps_name_when_the_page_omits_a_code(self) -> None:
        markdown = """
        # Приёмная комиссия МАИ
        ## Программы
        ### Программная инженерия
        ### Информационная безопасность
        """
        programmes = catalogue_programmes("catalogue-mai-2026-v1", markdown)
        self.assertEqual(["Программная инженерия", "Информационная безопасность"], [item.name for item in programmes])
        self.assertEqual([None, None], [item.external_code for item in programmes])

    def test_adapter_rejects_a_document_from_another_university(self) -> None:
        markdown = """
        # НИУ ВШЭ
        | Код | Образовательная программа |
        | --- | --- |
        | 09.03.04 | Программная инженерия |
        """
        self.assertEqual([], catalogue_programmes("catalogue-mai-2026-v1", markdown))

    def test_rejects_course_identifiers_that_are_not_admission_directions(self) -> None:
        markdown = """
        # РТУ МИРЭА
        | Код | Наименование направления подготовки |
        | --- | --- |
        | 00.00.12 | Мастерство публичных выступлений |
        | 09.03.01 | Информатика и вычислительная техника |
        """
        programmes = catalogue_programmes("catalogue-mirea-2026-v1", markdown)
        self.assertEqual(["09.03.01"], [item.external_code for item in programmes])


if __name__ == "__main__":
    unittest.main()
