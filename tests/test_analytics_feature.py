from __future__ import annotations

import unittest

from features import analytics as analytics_feature


class YdnaAnalyticsFeatureTests(unittest.TestCase):
    def test_group_label_and_subclade_rollup(self) -> None:
        entry = {"name": "Эркенов", "haplo": "G-M201", "general": "G2A1A", "subclade": "G2a1 > FGC1053"}

        self.assertEqual(analytics_feature.distribution_group_label(entry), "G2a1")
        self.assertEqual(analytics_feature.subclade_distribution_label(entry), "FGC1053")

    def test_distribution_counts_families_and_tests_differently(self) -> None:
        entries = [
            {"name": "Эркенов", "haplo": "G-M201", "general": "G2A1A", "subclade": "G2a1 > FGC1053"},
            {"name": "эркенов", "haplo": "G-M201", "general": "G2A1A", "subclade": "G2a1 > FGC1053"},
            {"name": "Биджиев", "haplo": "G-M201", "general": "G2A1A", "subclade": "G2a1 > Z31459"},
            {"name": "Салпагаров", "haplo": "R-M198", "general": "R1A", "subclade": "R1a > YP451"},
        ]

        families = analytics_feature.haplogroup_distribution(entries, "families")
        tests = analytics_feature.haplogroup_distribution(entries, "tests")
        subclades = analytics_feature.subclade_distribution(entries, "G2a1", "tests")

        self.assertEqual(families["items"][0]["label"], "G2a1")
        self.assertEqual(families["items"][0]["count"], 2)
        self.assertEqual(tests["items"][0]["count"], 3)
        self.assertEqual({item["label"]: item["count"] for item in subclades["items"]}, {"FGC1053": 2, "Z31459": 1})

    def test_navigation_surnames_are_unique_by_normalized_name(self) -> None:
        entries = [
            {"name": "Эркенов", "haplo": "G-M201", "general": "G2A1A", "subclade": "G2a1 > FGC1053"},
            {"name": "эркенов", "haplo": "G-M201", "general": "G2A1A", "subclade": "G2a1 > FGC1053"},
            {"name": "Биджиев", "haplo": "G-M201", "general": "G2A1A", "subclade": "G2a1 > FGC1053"},
        ]

        names = analytics_feature.surnames_in_subclade(entries, "G2a1", "FGC1053")

        self.assertEqual(names, ["Биджиев", "Эркенов"])


class MtdnaAnalyticsFeatureTests(unittest.TestCase):
    def test_mtdna_haplogroup_normalization_and_major_group(self) -> None:
        self.assertEqual(analytics_feature.normalize_mtdna_haplogroup("mtDNA U1b2d+"), "U1B2D")
        self.assertEqual(analytics_feature.mtdna_major_haplogroup("HV12A2A"), "HV")
        self.assertEqual(analytics_feature.mtdna_major_haplogroup("R0A"), "R0")

    def test_mtdna_navigation_uses_names_when_present_and_samples_when_not(self) -> None:
        entries = [
            {"name": "YF02397", "haplo": "B4B1A3A", "links": []},
            {"name": "YF95220", "haplo": "B4B1A3A", "links": []},
            {"name": "", "haplo": "U1B2D", "links": []},
            {"name": "", "haplo": "U1B2D", "links": []},
        ]

        groups = analytics_feature.mtdna_navigation_groups(entries)
        subclades = analytics_feature.mtdna_navigation_subclades(entries, "B")

        self.assertEqual({item["label"]: item["count"] for item in groups}, {"B": 2, "U": 2})
        self.assertEqual(subclades, [{"label": "B4B1A3A", "count": 2, "description": ""}])

    def test_mtdna_entries_in_subclade_deduplicates_links(self) -> None:
        link = {"label": "YFull", "url": "https://www.yfull.com/mtree/B4b1a3a/"}
        entries = [
            {"name": "YF02397", "haplo": "B4B1A3A", "links": [link]},
            {"name": "YF02397", "haplo": "B4B1A3A", "links": [link]},
            {"name": "YF95220", "haplo": "B4B1A3A", "links": []},
        ]

        result = analytics_feature.mtdna_entries_in_subclade(entries, "B", "B4b1a3a")

        self.assertEqual([item["name"] for item in result], ["YF02397", "YF95220"])


if __name__ == "__main__":
    unittest.main()
