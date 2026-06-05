from __future__ import annotations

import unittest

from clients.sheets import MtdnaSheetsClient, SheetsClient


class SheetsClientUtilityTests(unittest.TestCase):
    def test_normalize_handles_case_spacing_and_dashes(self) -> None:
        self.assertEqual(SheetsClient._normalize("  Ёл — А  "), "ел-а")

    def test_normalize_yfull_link_applies_override(self) -> None:
        self.assertEqual(
            SheetsClient._normalize_yfull_link("https://www.yfull.com/tree/G-Z6670/"),
            "",
        )
        self.assertEqual(
            SheetsClient._normalize_yfull_link("https://www.yfull.com/tree/R-BY30628/"),
            "https://www.yfull.com/tree/R-YP457/",
        )

    def test_mtdna_extracts_and_labels_links(self) -> None:
        links = MtdnaSheetsClient._extract_links_from_cell("YFull: https://www.yfull.com/mtree/U1b2d/.")
        self.assertEqual(links, ["https://www.yfull.com/mtree/U1b2d/"])
        self.assertEqual(MtdnaSheetsClient._link_label("tree", links[0]), "YFull")

    def test_mtdna_display_name_rejects_links_and_haplogroups(self) -> None:
        self.assertFalse(MtdnaSheetsClient._looks_like_display_name("https://example.com", "U1B2D"))
        self.assertFalse(MtdnaSheetsClient._looks_like_display_name("U1b2d", "U1B2D"))
        self.assertTrue(MtdnaSheetsClient._looks_like_display_name("Карачай", "U1B2D"))

    def test_filtered_client_prefers_configured_surname_column(self) -> None:
        class FakeWorksheet:
            def get_all_values(self):
                return [
                    ["Kit Number", "Name", "Фамилия", "Paternal Ancestor Name", "Country", "Haplogroup"],
                    ["C2", "C > M217 > F1067", "", "", "", ""],
                    ["kit1", "Khashkhozhev", "Хьащэхъуэжь", "Плановское", "Circassia", "C-F1067"],
                    ["kit2", "Lakoba", "Лакоба", "Лыхны", "Abkhazia", "G-M201"],
                ]

        client = object.__new__(SheetsClient)
        client.worksheet = FakeWorksheet()
        client.name_aliases = ("фамилия", "name", "имя")
        client.row_filter = lambda headers, row: len(row) > 4 and row[4] == "Circassia"
        client.emoji_map = {}
        client.yfull_links = {"by_subclade": {}, "by_terminal": {}}

        records = client.get_group_records("Хьащэхъуэжь")

        self.assertEqual(len(records), 1)
        self.assertIn("ХЬАЩЭХЪУЭЖЬ", records[0]["text"])
        self.assertNotIn("Лакоба", records[0]["text"])

        latin_records = client.get_group_records("Khashkhozhev")

        self.assertEqual(len(latin_records), 1)
        self.assertIn("ХЬАЩЭХЪУЭЖЬ", latin_records[0]["text"])
        self.assertEqual(client.find_similar_names("Khashkhozhe"), ["Хьащэхъуэжь"])

    def test_external_base_uses_location_and_exact_haplogroup_related_names(self) -> None:
        class FakeWorksheet:
            def get_all_values(self):
                return [
                    ["Kit Number", "Name", "Фамилия", "Paternal Ancestor Name", "Lacation", "Country", "Haplogroup"],
                    ["G2a2 L1266", "G2a2 L1266", "", "", "", "", ""],
                    ["kit1", "Shogenov", "Шогенов", "63790", "Заюково > Исламей", "Circassia", "G-Y293937"],
                    ["kit2", "Other", "Другой", "", "Инаркой", "Circassia", "G-L1264"],
                    ["kit3", "Exact", "Точный", "", "Чегем", "Circassia", "G-Y293937"],
                ]

        client = object.__new__(SheetsClient)
        client.worksheet = FakeWorksheet()
        client.name_aliases = ("фамилия", "name", "имя")
        client.origin_aliases = ("lacation", "location", "локация")
        client.related_match_mode = SheetsClient.RELATED_MATCH_HAPLOGROUP
        client.lookup_label_mode = SheetsClient.LOOKUP_LABEL_TERMINAL_HAPLOGROUP
        client.row_filter = None
        client.values_range = ""
        client.emoji_map = {}
        client.yfull_links = {"by_subclade": {}, "by_terminal": {}}

        records = client.get_group_records("Шогенов")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["button_label"], "G2a2 - Y293937 · 1")
        self.assertIn("Заюково &gt; Исламей", records[0]["text"])
        self.assertNotIn("63790", records[0]["text"])
        self.assertIn("Точный", records[0]["text"])
        self.assertNotIn("Другой", records[0]["text"])

    def test_related_names_are_limited_in_text_card(self) -> None:
        class FakeWorksheet:
            def get_all_values(self):
                rows = [
                    ["Kit Number", "Name", "Фамилия", "Lacation", "Country", "Haplogroup"],
                    ["G2a2 L1266", "G2a2 L1266", "", "", "", ""],
                    ["kit1", "Shogenov", "Шогенов", "Заюково", "Circassia", "G-L1264"],
                ]
                for index in range(45):
                    rows.append([
                        f"kit{index + 2}",
                        f"Related {index + 1}",
                        f"Родственный {index + 1}",
                        "",
                        "Circassia",
                        "G-L1264",
                    ])
                return rows

        client = object.__new__(SheetsClient)
        client.worksheet = FakeWorksheet()
        client.name_aliases = ("фамилия", "name", "имя")
        client.origin_aliases = ("lacation", "location", "локация")
        client.related_match_mode = SheetsClient.RELATED_MATCH_HAPLOGROUP
        client.lookup_label_mode = SheetsClient.LOOKUP_LABEL_TERMINAL_HAPLOGROUP
        client.row_filter = None
        client.values_range = ""
        client.emoji_map = {}
        client.yfull_links = {"by_subclade": {}, "by_terminal": {}}

        records = client.get_group_records("Шогенов")

        self.assertIn("Родственный 40", records[0]["text"])
        self.assertNotIn("Родственный 41,", records[0]["text"])
        self.assertIn("и ещё 5", records[0]["text"])


if __name__ == "__main__":
    unittest.main()
