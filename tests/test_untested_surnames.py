from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from features.untested_surnames import clear_untested_surname_cache, load_untested_surname_groups


class UntestedSurnamesTests(unittest.TestCase):
    def tearDown(self) -> None:
        clear_untested_surname_cache()

    def test_loads_four_named_groups_from_text_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "untested.txt"
            path.write_text(
                "\n".join(
                    [
                        "Для начала ознакомьтесь со списками непротестированных фамилий:",
                        "Список карачаевских фамилий",
                        "Абаев",
                        "Боташев",
                        "Список непротестированных балкарских фамилий",
                        "Глашев",
                        "Фамилии, наличие которых требует подтверждения",
                        "Текуев",
                        "Список непротестированных балкарских фамилий Чегем",
                        "Чегемов",
                        "Список непротестированных балкарских фамилий Холам",
                        "Холамов",
                    ]
                ),
                encoding="utf-8",
            )

            groups = load_untested_surname_groups(path)
            by_key = {group["key"]: group for group in groups}

        self.assertEqual(by_key["karachay"]["names"], ["Абаев", "Боташев"])
        self.assertEqual(by_key["malkar"]["names"], ["Глашев"])
        self.assertEqual(by_key["malkar"]["confirm_names"], ["Текуев"])
        self.assertEqual(by_key["chegem"]["names"], ["Чегемов"])
        self.assertEqual(by_key["holam"]["names"], ["Холамов"])

    def test_missing_file_returns_empty_groups(self) -> None:
        groups = load_untested_surname_groups(Path("missing-untested-surnames.txt"))

        self.assertEqual([group["key"] for group in groups], ["karachay", "malkar", "chegem", "holam"])
        self.assertTrue(all(not group["names"] and not group["confirm_names"] for group in groups))


if __name__ == "__main__":
    unittest.main()
