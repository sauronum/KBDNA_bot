from __future__ import annotations

import unittest
from io import BytesIO

from PIL import Image

from app.features.vahaduo.ready_models_rendering import CANVAS_WIDTH, MIN_CANVAS_HEIGHT, build_rendered_source_fit_card, render_source_fit_card, source_fit_caption
from app.features.vahaduo.ready_models_runtime import SourceFitComponent, SourceFitResult


def _fit_result() -> SourceFitResult:
    return SourceFitResult(
        status="ok",
        target_name="Заур",
        source_set_id="karachay_balkar_hypothesis",
        source_set_title="Karachay-Balkar hypothesis",
        distance=0.0195,
        components=(
            SourceFitComponent("Maikop / Caucasus", "🏔", "Maikop", 62.4),
            SourceFitComponent("Sintashta / Steppe", "🐎", "Steppe", 24.8),
            SourceFitComponent("East Eurasian proxy", "🌏", "YR", 7.1),
            SourceFitComponent("Kura-Araxes / Bronze Age Caucasus", "🏺", "KuraAraxes", 5.7),
        ),
    )


class ModelingRenderingTests(unittest.TestCase):
    def test_render_source_fit_card_returns_png_bytes(self) -> None:
        image_bytes = render_source_fit_card(_fit_result())

        self.assertGreater(len(image_bytes), 1000)
        self.assertEqual(image_bytes[:8], b"\x89PNG\r\n\x1a\n")
        with Image.open(BytesIO(image_bytes)) as image:
            self.assertEqual(image.width, CANVAS_WIDTH)
            self.assertGreaterEqual(image.height, MIN_CANVAS_HEIGHT)
            self.assertLess(image.height, 850)

    def test_rendered_source_fit_card_includes_caption_and_result(self) -> None:
        result = _fit_result()
        rendered = build_rendered_source_fit_card(result)

        self.assertEqual(rendered.image_bytes[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIs(rendered.result, result)
        self.assertIn("📚 Ready models", rendered.caption)
        self.assertIn("G25-профиль: Заур", rendered.caption)
        self.assertIn("Модель: Karachay-Balkar hypothesis", rendered.caption)
        self.assertIn("Distance: 0.0195", rendered.caption)
        self.assertIn("Это G25-fit модель, не qpAdm.", rendered.caption)

    def test_source_fit_caption_has_clean_text(self) -> None:
        caption = source_fit_caption(_fit_result())

        self.assertIn("📚 Ready models", caption)
        self.assertNotIn("Vahaduo", caption)
        self.assertNotIn("Single", caption)
        self.assertNotIn("Multi", caption)

    def test_render_source_fit_card_handles_long_title_and_many_components(self) -> None:
        result = SourceFitResult(
            status="ok",
            target_name="Очень длинный G25 профиль с подписью",
            source_set_id="long",
            source_set_title="Very Long Karachay-Balkar Hypothesis With Proxy Source Set",
            distance=0.0287,
            components=tuple(
                SourceFitComponent(f"Long proxy component name {index} / regional layer", "", f"source_{index}", 12.5)
                for index in range(8)
            ),
        )

        image_bytes = render_source_fit_card(result)

        self.assertEqual(image_bytes[:8], b"\x89PNG\r\n\x1a\n")
        with Image.open(BytesIO(image_bytes)) as image:
            self.assertEqual(image.width, CANVAS_WIDTH)
            self.assertGreaterEqual(image.height, MIN_CANVAS_HEIGHT)


if __name__ == "__main__":
    unittest.main()
