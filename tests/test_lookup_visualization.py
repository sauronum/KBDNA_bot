from __future__ import annotations

import unittest

from ui.lookup_visualization import render_lookup_record_png


def _png_size(png_bytes: bytes) -> tuple[int, int]:
    return (
        int.from_bytes(png_bytes[16:20], "big"),
        int.from_bytes(png_bytes[20:24], "big"),
    )


class LookupVisualizationTests(unittest.TestCase):
    def test_render_lookup_record_png_returns_detailed_card(self) -> None:
        png = render_lookup_record_png({
            "visual_name": "Эркенов",
            "visual_haplogroup": "G2a - Z31455",
            "visual_general": "G2a",
            "visual_subclade": "Z31455",
            "visual_origins": ["Карачай", "Балкария"],
            "visual_related": ["Абаев", "Боташев", "Узденов"],
            "visual_test_count": "3",
            "visual_yfull_link": "https://www.yfull.com/tree/G-Z31455/",
        })

        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual(_png_size(png), (1280, 900))
        self.assertGreater(len(png), 1000)


if __name__ == "__main__":
    unittest.main()
