from __future__ import annotations

import unittest

from render import analytics as analytics_render


class AnalyticsRenderTests(unittest.TestCase):
    def test_captions_match_analytics_wording(self) -> None:
        self.assertEqual(analytics_render.haplo_distribution_caption("families", 42), "Распределение гаплогрупп · по родам · 42")
        self.assertEqual(analytics_render.haplo_subclade_caption("G2a1", "tests", 11), "Субклады G2a1 у карачаево-балкарцев · по тестам · 11")
        self.assertEqual(
            analytics_render.haplo_distribution_caption("families", 42, scope_label="Адыгская база"),
            "Распределение гаплогрупп · Адыгская база · по родам · 42",
        )
        self.assertEqual(
            analytics_render.haplo_subclade_caption("G2a1", "tests", 11, scope_label="Абхазская база"),
            "Субклады G2a1 · Абхазская база · по тестам · 11",
        )
        self.assertEqual(analytics_render.mtdna_distribution_caption("subclades", 5), "МтДНК · субклады · по образцам · 5")

    def test_render_haplo_distribution_png_returns_png_bytes(self) -> None:
        png = analytics_render.render_haplo_distribution_png(
            [
                {"label": "G2a1", "count": 3},
                {"label": "R1a", "count": 2},
            ],
            5,
            "tests",
        )

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(png), 1000)

    def test_render_haplo_distribution_png_handles_other_label_and_zero_total(self) -> None:
        png = analytics_render.render_haplo_distribution_png(
            [{"label": "Прочее", "count": 0}],
            0,
            "families",
            title="TEST",
        )

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
