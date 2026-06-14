from __future__ import annotations

import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.features.modeling.visuals import render_admixtools2_qpadm_batch_result, render_admixtools2_qpgraph_result, render_qpadm_result
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

    def test_qpadm_renderer_uses_distinct_admixtools2_visual_profile(self) -> None:
        summary = {
            "status": "completed",
            "fit": {"p_value": 0.123},
            "feasibility": {"status": "PASS"},
            "weights": [
                {"source": "Sintashta", "weight_percent": 61.5, "stderr_percent": 4.2},
                {"source": "Caucasus_Maikop", "weight_percent": 38.5, "stderr_percent": 4.2},
            ],
        }
        base_flow = {
            "dataset": "v62_1240k_public",
            "target": "Balkar",
            "sources": ["Sintashta", "Caucasus_Maikop"],
            "references": ["Mbuti", "Han", "Onge"],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            classic_path = render_qpadm_result(summary, flow=base_flow, elapsed_seconds=1.2, output_dir=Path(temp_dir))
            at2_path = render_qpadm_result(
                summary,
                flow={**base_flow, "engine": "admixtools2_qpadm"},
                elapsed_seconds=1.2,
                output_dir=Path(temp_dir),
            )

            self.assertTrue(classic_path.name.startswith("qpadm_result_"))
            self.assertTrue(at2_path.name.startswith("qpadm_admixtools2_result_"))
            with Image.open(classic_path) as classic_image, Image.open(at2_path) as at2_image:
                self.assertNotEqual(classic_image.size, at2_image.size)
                self.assertGreater(at2_image.width, classic_image.width)
                self.assertNotEqual(classic_image.getpixel((50, 50)), at2_image.getpixel((50, 50)))

    def test_admixtools2_batch_renderer_returns_png(self) -> None:
        flow = {
            "engine": "admixtools2_qpadm",
            "dataset": "human_origins",
            "target_type": "dataset_population",
            "target": "Balkar.HO",
            "targets": ["Balkar.HO", "Karachay.HO"],
            "sources": ["Barcin_N", "YuzhniyOleniyOstrov", "Satsurblia"],
            "references": ["Mbuti.DG", "Russia_UstIshim_IUP.DG"],
        }
        batch_payload = {
            "status": "completed",
            "results": [
                {
                    "target": "Balkar.HO",
                    "target_label": "Balkar.HO",
                    "status": "completed",
                    "summary": {
                        "fit": {"p_value": 0.849},
                        "feasibility": {"status": "PASS"},
                        "weights": [
                            {"source": "Barcin_N", "weight_percent": 33.7},
                            {"source": "YuzhniyOleniyOstrov", "weight_percent": 21.3},
                            {"source": "Satsurblia", "weight_percent": 8.1},
                        ],
                    },
                },
                {
                    "target": "Karachay.HO",
                    "target_label": "Karachay.HO",
                    "status": "completed",
                    "summary": {
                        "fit": {"p_value": 0.096},
                        "feasibility": {"status": "WARNING"},
                        "weights": [
                            {"source": "Barcin_N", "weight_percent": 34.9},
                            {"source": "YuzhniyOleniyOstrov", "weight_percent": 18.9},
                            {"source": "Satsurblia", "weight_percent": 7.6},
                        ],
                    },
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = render_admixtools2_qpadm_batch_result(batch_payload, flow=flow, elapsed_seconds=9.4, output_dir=Path(temp_dir))

            self.assertTrue(path.name.startswith("qpadm_admixtools2_batch_"))
            with Image.open(path) as image:
                self.assertEqual(image.width, 1440)
                self.assertGreaterEqual(image.height, 820)

    def test_admixtools2_qpgraph_renderer_returns_png(self) -> None:
        payload = {
            "status": "completed",
            "result": {
                "score": [0.000143],
                "worst_residual": [0.0115],
                "leaf_populations": ["Mbuti.DG", "Han.DG", "Papuan.DG"],
                "edges": [
                    {"from": "R", "to": "Mbuti.DG", "weight": [0.035]},
                    {"from": "R", "to": "N1", "weight": [0.035]},
                    {"from": "N1", "to": "Han.DG", "weight": [0.018]},
                    {"from": "N1", "to": "Papuan.DG", "weight": [0.039]},
                ],
                "f3": [{"pop1": "Mbuti.DG", "pop2": "Han.DG", "pop3": "Papuan.DG", "z": [0.99]}],
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = render_admixtools2_qpgraph_result(
                payload,
                flow={"dataset": "v62_1240k_public", "graph_text": "edge R Mbuti.DG"},
                elapsed_seconds=2.4,
                output_dir=Path(temp_dir),
            )

            self.assertTrue(path.name.startswith("qpgraph_admixtools2_result_"))
            with Image.open(path) as image:
                self.assertGreaterEqual(image.width, 1180)
                self.assertGreaterEqual(image.height, 820)

    def test_admixtools2_qpgraph_renderer_expands_for_deep_graphs(self) -> None:
        edges = [{"from": "R", "to": "N0", "weight": [0.01]}]
        for index in range(8):
            edges.append({"from": f"N{index}", "to": f"N{index + 1}", "weight": [0.01]})
        edges.extend(
            [
                {"from": "N8", "to": "Mbuti.DG", "weight": [0.01]},
                {"from": "N8", "to": "Han.DG", "weight": [0.01]},
                {"from": "N8", "to": "Papuan.DG", "weight": [0.01]},
            ]
        )
        payload = {
            "status": "completed",
            "result": {
                "score": [0.1],
                "worst_residual": [0.2],
                "leaf_populations": ["Mbuti.DG", "Han.DG", "Papuan.DG"],
                "edges": edges,
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = render_admixtools2_qpgraph_result(
                payload,
                flow={"dataset": "human_origins", "graph_text": "edge R N0"},
                elapsed_seconds=1.0,
                output_dir=Path(temp_dir),
            )

            with Image.open(path) as image:
                self.assertGreater(image.width, 1180)

    def test_admixtools2_qpgraph_renderer_reserves_edge_weight_section(self) -> None:
        edges = [{"from": "R", "to": "Mbuti.DG", "weight": [0.031]}]
        for index in range(12):
            edges.append({"from": f"N{index}", "to": f"N{index + 1}", "weight": [0.01 * (index + 1)]})
        payload = {
            "status": "completed",
            "result": {
                "score": [0.1],
                "worst_residual": [0.2],
                "leaf_populations": ["Mbuti.DG", "N12"],
                "edges": edges,
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = render_admixtools2_qpgraph_result(
                payload,
                flow={"dataset": "human_origins", "graph_text": "edge R Mbuti.DG"},
                elapsed_seconds=1.0,
                output_dir=Path(temp_dir),
            )

            with Image.open(path) as image:
                self.assertGreaterEqual(image.height, 980)


if __name__ == "__main__":
    unittest.main()
