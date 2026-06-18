from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.features.modeling.visuals import (
    render_admixtools2_fstats_result,
    render_admixtools2_qpadm_batch_result,
    render_admixtools2_qpgraph_result,
    render_qpwave_result,
    render_qpadm_result,
)
class ModelingRenderingTests(unittest.TestCase):
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

    def test_admixtools2_fstats_renderer_returns_png(self) -> None:
        payload = {
            "status": "completed",
            "result": {
                "statistic": "f4",
                "rows": [
                    {
                        "pop1": "Mbuti.DG",
                        "pop2": "Han.DG",
                        "pop3": "Papuan.DG",
                        "pop4": "Balkar.HO",
                        "est": [0.00123],
                        "se": [0.00045],
                        "z": [2.73],
                        "p": [0.006],
                    }
                ],
                "data_source": {"type": "precomputed_f2_cache", "cache_status": "hit", "path": "/tmp/f2_cache"},
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = render_admixtools2_fstats_result(
                payload,
                flow={"dataset": "human_origins", "statistic": "f4", "populations": ["Mbuti.DG", "Han.DG", "Papuan.DG", "Balkar.HO"]},
                elapsed_seconds=3.1,
                output_dir=Path(temp_dir),
            )

            self.assertTrue(path.name.startswith("fstats_admixtools2_result_"))
            with Image.open(path) as image:
                self.assertEqual(image.width, 1180)
                self.assertGreaterEqual(image.height, 820)

    def test_admixtools2_qpwave_renderer_uses_distinct_visual_profile(self) -> None:
        ranks = [
            {"rank": 0, "dof": 3, "chisq": 2.4, "tail": 0.493},
            {"rank": 1, "dof": 2, "chisq": 0.8, "tail": 0.672},
        ]
        flow = {
            "engine": "admixtools2_qpwave",
            "dataset": "v66p1_1240k_public",
            "left": ["Russia_Caucasus_Maikop_Novosvobodnaya.AG", "Russia_MLBA_Sintashta.SG"],
            "right": ["Mbuti", "Han", "Papuan", "Russia_UstIshim_IUP"],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            path = render_qpwave_result(
                ranks=ranks,
                flow=flow,
                elapsed_seconds=4.2,
                output_dir=Path(temp_dir),
                data_source={"type": "precomputed_f2_cache", "cache_status": "hit", "path": "/tmp/f2_cache"},
                f4_rows=[{"pop1": "A"} for _ in range(5)],
            )

            self.assertTrue(path.name.startswith("qpwave_admixtools2_result_"))
            with Image.open(path) as image:
                self.assertEqual(image.width, 1200)
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
