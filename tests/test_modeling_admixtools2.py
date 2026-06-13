from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.features.modeling import admixtools2
from app.features.modeling.admixtools2 import (
    AT2_FSTATS_FLOW_KEY,
    AT2_QPGRAPH_FLOW_KEY,
    _cache_entry_ready,
    _cache_rows,
    _format_cache_status,
    _format_fstats_error,
    _format_fstats_result,
    _format_qpgraph_result,
    _new_fstats_flow,
    _new_qpgraph_flow,
    _parse_populations,
    _parse_qpgraph_graph_text,
    _qpgraph_leaf_populations,
    _qpgraph_preflight,
    _qpgraph_result_markup,
    _qpgraph_save_payload,
    _format_qpgraph_preflight,
    _show_fstats_builder,
    _show_qpgraph_builder,
    admixtools2_callback_handler,
)
from app.features.modeling.navigation import NAV_CURRENT_KEY, NAV_STACK_KEY, nav_enter, nav_pop
from app.features.modeling.saved_models import _kind_label
from app.features.modeling.qpwave import (
    QPWAVE_ENGINE_ADMIXTOOLS2,
    _extract_admixtools2_ranks,
    _format_qpwave_error,
    _snapshot_flow,
    _start_flow,
)


class ModelingAdmixtools2Tests(unittest.TestCase):
    def test_f2_cache_ready_accepts_admixtools2_rds_markers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir)

            self.assertFalse(_cache_entry_ready(path))
            (path / "block_lengths_ap.rds").touch()

            self.assertTrue(_cache_entry_ready(path))

    def test_f2_cache_status_counts_rds_marker_entries_as_ready(self) -> None:
        old_config = admixtools2.AT2_QPADM_CONFIG
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            cache_dir = root / "cache"
            ready_entry = cache_dir / "f2_ready"
            stale_entry = cache_dir / "f2_stale"
            building_entry = cache_dir / "f2_ready.lock"
            ready_entry.mkdir(parents=True)
            stale_entry.mkdir(parents=True)
            building_entry.mkdir(parents=True)
            (ready_entry / "block_lengths_fst.rds").touch()

            config_path = root / "config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "datasets": {
                            "human_origins": {
                                "required_files": {
                                    "geno_prefix": "/data/admixlab/human_origins/human_origins",
                                    "f2_cache_dir": str(cache_dir),
                                }
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            admixtools2.AT2_QPADM_CONFIG = config_path
            try:
                rows = _cache_rows()
                text = _format_cache_status("ru")
            finally:
                admixtools2.AT2_QPADM_CONFIG = old_config

        self.assertEqual(rows[0]["ready_entries"], 1)
        self.assertEqual(rows[0]["building_entries"], 1)
        self.assertEqual(rows[0]["stale_entries"], 1)
        self.assertEqual(rows[0]["entries"], 2)
        self.assertIn("<code>ready</code>", text)
        self.assertIn("<code>1 ready</code>", text)
        self.assertIn("<code>1 building</code>", text)

    def test_fstats_population_parser_accepts_keyed_and_plain_lists(self) -> None:
        self.assertEqual(
            _parse_populations("pop1=Mbuti.DG\npop2=Han.DG\npop3=Papuan.DG\npop4=Russia_MA1_UP.SG", 4),
            ["Mbuti.DG", "Han.DG", "Papuan.DG", "Russia_MA1_UP.SG"],
        )
        self.assertEqual(_parse_populations("Mbuti.DG, Han.DG; Papuan.DG", 3), ["Mbuti.DG", "Han.DG", "Papuan.DG"])

    def test_qpgraph_graph_text_parser_drops_blank_and_comment_lines(self) -> None:
        text = _parse_qpgraph_graph_text(
            "\n".join(
                [
                    "# qpGraph",
                    "",
                    "edge R Mbuti.DG",
                    " edge R N1 ",
                    "edge N1 Han.DG",
                ]
            )
        )

        self.assertEqual(text.splitlines(), ["edge R Mbuti.DG", "edge R N1", "edge N1 Han.DG"])

    def test_qpgraph_leaf_parser_uses_sampled_graph_leaves(self) -> None:
        leaves = _qpgraph_leaf_populations(
            "\n".join(
                [
                    "edge R Mbuti.DG",
                    "edge R N1",
                    "edge N1 Han.DG",
                    "edge N1 Papuan.DG",
                ]
            )
        )

        self.assertEqual(leaves, ["Mbuti.DG", "Han.DG", "Papuan.DG"])

    def test_qpgraph_preflight_reports_missing_dataset_populations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prefix = Path(temp_dir) / "dataset"
            prefix.with_suffix(".ind").write_text(
                "\n".join(
                    [
                        "sample1 U Mbuti.DG",
                        "sample2 U Han.DG",
                        "sample3 U Papuan.DG",
                    ]
                ),
                encoding="utf-8",
            )
            flow = {
                "dataset": "human_origins",
                "graph_text": "\n".join(
                    [
                        "edge R Mbuti.DG",
                        "edge R N1",
                        "edge N1 Missing.Pop",
                        "edge N1 Papuan.DG",
                    ]
                ),
            }

            payload = _qpgraph_preflight(flow, {"geno_prefix": str(prefix)})
            text = _format_qpgraph_preflight(payload, flow=flow)

        self.assertFalse(payload["can_run"])
        self.assertEqual(payload["status"], "population_not_found")
        self.assertIn("Missing.Pop", text)
        self.assertIn("Нет в dataset", text)

    def test_qpgraph_preflight_allows_present_dataset_populations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            prefix = Path(temp_dir) / "dataset"
            prefix.with_suffix(".ind").write_text(
                "\n".join(
                    [
                        "sample1 U Mbuti.DG",
                        "sample2 U Han.DG",
                        "sample3 U Papuan.DG",
                    ]
                ),
                encoding="utf-8",
            )
            payload = _qpgraph_preflight(
                {
                    "dataset": "human_origins",
                    "graph_text": "edge R Mbuti.DG\nedge R N1\nedge N1 Han.DG\nedge N1 Papuan.DG",
                },
                {"geno_prefix": str(prefix)},
            )

        self.assertTrue(payload["can_run"])
        self.assertEqual(payload["status"], "ok")

    def test_qpgraph_result_formats_score_edges_and_residuals(self) -> None:
        text = _format_qpgraph_result(
            {
                "status": "completed",
                "result": {
                    "score": [0.000149],
                    "worst_residual": [0.0118],
                    "leaf_populations": ["Mbuti.DG", "Han.DG", "Papuan.DG"],
                    "edges": [
                        {"from": "R", "to": "Mbuti.DG", "type": "edge", "weight": [0.0346]},
                        {"from": "R", "to": "N1", "type": "edge", "weight": [0.0346]},
                    ],
                    "f3": [
                        {"pop1": "Mbuti.DG", "pop2": "Han.DG", "pop3": "Papuan.DG", "z": [0.991]},
                    ],
                    "data_source": {"type": "precomputed_f2_cache", "path": "/cache/f2_x"},
                },
            },
            flow={"dataset": "human_origins", "graph_text": "edge R Mbuti.DG"},
            elapsed_seconds=3.2,
        )

        self.assertIn("qpGraph 2", text)
        self.assertIn("Fit score", text)
        self.assertIn("Mbuti.DG", text)
        self.assertIn("Worst |z|", text)
        self.assertIn("precomputed_f2_cache", text)

    def test_qpgraph_result_markup_includes_save_and_next_actions(self) -> None:
        markup = _qpgraph_result_markup("ru", "pending123")

        callbacks = [button.callback_data for row in markup.inline_keyboard for button in row]
        self.assertIn("modeling:at2_qpgraph", callbacks)
        self.assertIn("modeling:at2_qpgraph_graph", callbacks)
        self.assertIn("modeling:saved_save:pending123", callbacks)

    def test_qpgraph_save_payload_preserves_graph_and_result(self) -> None:
        text = "<b>result</b>"
        payload = _qpgraph_save_payload(
            {
                "status": "completed",
                "result": {
                    "score": [0.1],
                    "worst_residual": [0.2],
                    "leaf_populations": ["Mbuti.DG", "Han.DG"],
                    "edges": [{"from": "R", "to": "Mbuti.DG"}],
                    "f3": [{"z": [0.5]}],
                },
            },
            flow={"dataset": "human_origins", "graph_text": "edge R Mbuti.DG"},
            text=text,
        )

        self.assertEqual(payload["kind"], "qpgraph_admixtools2")
        self.assertEqual(payload["dataset"], "human_origins")
        self.assertEqual(payload["graph_text"], "edge R Mbuti.DG")
        self.assertEqual(payload["result_text"], text)
        self.assertEqual(payload["leaves"], ["Mbuti.DG", "Han.DG"])
        self.assertEqual(_kind_label(payload), "ADMIXTOOLS2 qpGraph 2")

    def test_qpgraph_builder_enables_run_after_graph_text(self) -> None:
        class Message:
            async def edit_text(self, text, reply_markup=None, parse_mode=None):
                self.text = text
                self.reply_markup = reply_markup

        context = SimpleNamespace(user_data={AT2_QPGRAPH_FLOW_KEY: _new_qpgraph_flow("human_origins")})
        context.user_data[AT2_QPGRAPH_FLOW_KEY]["graph_text"] = "edge R Mbuti.DG\nedge R N1\nedge N1 Han.DG"
        message = Message()

        asyncio.run(_show_qpgraph_builder(message, context, edit_existing=True, lang="ru"))

        callbacks = [button.callback_data for row in message.reply_markup.inline_keyboard for button in row]
        self.assertIn("modeling:at2_qpgraph_run", callbacks)

    def test_fstats_result_formats_scalar_lists_from_r(self) -> None:
        text = _format_fstats_result(
            {
                "status": "completed",
                "result": {
                    "rows": [
                        {
                            "est": [0.012345],
                            "se": [0.0012],
                            "z": [10.2875],
                            "p": [0.42],
                        }
                    ]
                },
            },
            flow={"dataset": "human_origins", "statistic": "f4", "populations": ["A", "B", "C", "D"]},
            elapsed_seconds=1.2,
        )

        self.assertIn("value=<code>0.012345</code>", text)
        self.assertIn("se=<code>0.0012</code>", text)
        self.assertIn("z=<code>10.2875</code>", text)

    def test_fstats_error_formats_runner_failures_for_user(self) -> None:
        text = _format_fstats_error(
            RuntimeError("block_lengths file not found"),
            flow={"dataset": "human_origins", "statistic": "f4", "populations": ["A", "B", "C", "D"]},
            elapsed_seconds=2.3,
        )

        self.assertIn("f-statistics", text)
        self.assertIn("не прошел", text)
        self.assertIn("block_lengths file not found", text)
        self.assertIn("Human Origins", text)

    def test_fstats_builder_marks_selected_statistic(self) -> None:
        class Message:
            async def edit_text(self, text, reply_markup=None, parse_mode=None):
                self.text = text
                self.reply_markup = reply_markup

        context = SimpleNamespace(user_data={AT2_FSTATS_FLOW_KEY: _new_fstats_flow("human_origins")})
        context.user_data[AT2_FSTATS_FLOW_KEY]["statistic"] = "f3"
        message = Message()

        asyncio.run(_show_fstats_builder(message, context, edit_existing=True, lang="ru"))

        first_row = [button.text for button in message.reply_markup.inline_keyboard[0]]
        self.assertEqual(first_row, ["f2", "✓ f3", "f4"])

    def test_fstats_dataset_back_target_is_handled(self) -> None:
        class Message:
            async def edit_text(self, text, reply_markup=None, parse_mode=None):
                self.text = text
                self.reply_markup = reply_markup

        message = Message()
        update = SimpleNamespace(callback_query=SimpleNamespace(message=message))
        context = SimpleNamespace(user_data={})
        nav_enter(context, "modeling:at2")
        nav_enter(context, "modeling:at2_fstats_ds")
        nav_enter(context, "modeling:at2_fstats_builder")

        target = nav_pop(context)
        handled = asyncio.run(
            admixtools2_callback_handler(
                update,
                context,
                target.split(":")[1],
                target.split(":"),
                lang="ru",
            )
        )

        self.assertTrue(handled)
        self.assertIn("f-statistics", message.text)
        self.assertEqual(context.user_data[NAV_CURRENT_KEY], "modeling:at2_fstats_ds")
        self.assertEqual(context.user_data[NAV_STACK_KEY], ["modeling:at2"])

    def test_qpwave_admixtools2_flow_snapshot_preserves_engine(self) -> None:
        class Context:
            user_data = {}

        flow = _start_flow(Context, "human_origins", engine=QPWAVE_ENGINE_ADMIXTOOLS2)
        flow["left"] = ["A", "B"]
        flow["right"] = ["C"]

        self.assertEqual(_snapshot_flow(flow)["engine"], QPWAVE_ENGINE_ADMIXTOOLS2)

    def test_qpwave_admixtools2_rank_parser_accepts_r_scalar_lists(self) -> None:
        ranks = _extract_admixtools2_ranks(
            {
                "result": {
                    "ranks": [
                        {"rank": [0], "dof": [2], "chisq": [4.5], "tail": [0.105]},
                        {"rank": 1, "dof": 1, "chisq": 0.3, "tail": 0.58},
                    ]
                }
            }
        )

        self.assertEqual(ranks[0]["rank"], 0)
        self.assertEqual(ranks[0]["dof"], 2.0)
        self.assertEqual(ranks[1]["tail"], 0.58)

    def test_qpwave_admixtools2_error_mentions_f2_cache_when_relevant(self) -> None:
        text = _format_qpwave_error(
            {
                "engine": QPWAVE_ENGINE_ADMIXTOOLS2,
                "dataset": "human_origins",
                "left": ["A", "B"],
                "right": ["Mbuti.DG"],
            },
            RuntimeError("block_lengths file not found. Please run extract_f2() again."),
        )

        self.assertIn("ADMIXTOOLS2 qpWave", text)
        self.assertIn("Human Origins", text)
        self.assertIn("block_lengths file not found", text)
        self.assertIn("f2 cache", text)


if __name__ == "__main__":
    unittest.main()
