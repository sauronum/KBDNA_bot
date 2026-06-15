from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.features.modeling.qpadm_classic import (
    QPADM_ENGINE_ADMIXTOOLS2,
    QPADM_ENGINE_CLASSIC,
    _format_messages,
    _format_preflight,
    _format_preflight_process_result,
    _format_qpadm_summary,
    _format_queue_text,
    _flow_for_target,
    _add_dataset_target,
    _add_raw_target,
    _looks_like_direct_qpadm_label,
    _merge_role_items,
    _qpadm_args,
    _qpadm_backend_config_for_engine,
    _qpadm_env,
    _qpadm_title,
    _run_qpadm_batch_job,
    _run_qpadm_job,
    _has_supported_target_for_engine,
    _snapshot_flow,
    _target_menu_markup,
    _targets_list,
)


class QpadmClassicFormattingTests(unittest.TestCase):
    def test_format_messages_limits_long_backend_lists(self) -> None:
        messages = [{"message": f"warning {index}"} for index in range(6)]

        lines = _format_messages(messages, limit=3, lang="en")

        self.assertEqual(len(lines), 4)
        self.assertIn("warning 0", lines[0])
        self.assertIn("warning 2", lines[2])
        self.assertIn("and 3 more", lines[3])
        self.assertNotIn("warning 3", "\n".join(lines))

    def test_preflight_limits_warnings_and_errors(self) -> None:
        payload = {
            "status": "ok",
            "engine_status": "ready",
            "can_run": True,
            "warnings": [{"message": f"warning {index}"} for index in range(6)],
            "errors": [{"message": f"error {index}"} for index in range(5)],
        }

        text, can_run = _format_preflight(payload, elapsed_seconds=1.25, lang="en")

        self.assertTrue(can_run)
        self.assertIn("warning 0", text)
        self.assertIn("warning 3", text)
        self.assertIn("and 2 more", text)
        self.assertIn("error 0", text)
        self.assertIn("error 3", text)
        self.assertIn("and 1 more", text)
        self.assertNotIn("warning 4", text)
        self.assertNotIn("error 4", text)

    def test_preflight_formats_json_stdout_even_when_process_exits_nonzero(self) -> None:
        stdout = json.dumps(
            {
                "status": "failed",
                "engine_status": {"available": True},
                "can_run": False,
                "warnings": [],
                "errors": [{"message": "raw target could not be prepared"}],
                "raw_preparation": None,
            }
        )

        text, can_run = _format_preflight_process_result(
            returncode=1,
            stdout=stdout,
            stderr="",
            elapsed_seconds=0.5,
            lang="en",
            product_title="ADMIXTOOLS2 qpAdm",
        )

        self.assertFalse(can_run)
        self.assertIn("ADMIXTOOLS2 qpAdm", text)
        self.assertIn("raw target could not be prepared", text)
        self.assertNotIn('"raw_preparation"', text)

    def test_preflight_expands_missing_population_details(self) -> None:
        payload = {
            "status": "population_not_found",
            "engine_status": "backend_not_ready",
            "can_run": False,
            "warnings": [],
            "errors": [
                {
                    "code": "population_not_found",
                    "message": "One or more qpAdm sources/references are not available in the selected dataset.",
                    "details": {
                        "dataset": "v62_1240k_public",
                        "missing": [
                            {
                                "role": "source",
                                "label": "Missing_Source.AG",
                                "suggestions": ["Missing_Source_Possible.AG"],
                            },
                            {"role": "reference", "label": "Missing_Reference.DG", "suggestions": []},
                        ],
                    },
                }
            ],
        }

        text, can_run = _format_preflight(payload, elapsed_seconds=2.5, lang="en", product_title="ADMIXTOOLS2 qpAdm")

        self.assertFalse(can_run)
        self.assertIn("Missing in dataset:", text)
        self.assertIn("source: Missing_Source.AG", text)
        self.assertIn("try: Missing_Source_Possible.AG", text)
        self.assertIn("reference: Missing_Reference.DG", text)

    def test_preflight_expands_missing_target_population_detail(self) -> None:
        payload = {
            "status": "population_not_found",
            "engine_status": "skipped",
            "can_run": False,
            "warnings": [],
            "errors": [
                {
                    "code": "population_not_found",
                    "message": "Population 'Balkar' is not available in dataset 'v62_1240k_public'.",
                    "details": {"dataset": "v62_1240k_public", "population_id": "Balkar"},
                }
            ],
        }

        text, can_run = _format_preflight(payload, elapsed_seconds=0.5, lang="en", product_title="ADMIXTOOLS2 qpAdm")

        self.assertFalse(can_run)
        self.assertIn("Missing in dataset:", text)
        self.assertIn("target: Balkar", text)

    def test_admixtools2_titles_are_not_labeled_classic(self) -> None:
        flow = {
            "engine": QPADM_ENGINE_ADMIXTOOLS2,
            "dataset": "v62_1240k_public",
            "target": "Balkar",
            "sources": ["Sintashta"],
            "references": ["Mbuti"],
        }
        summary = {
            "status": "completed",
            "engine": QPADM_ENGINE_ADMIXTOOLS2,
            "fit": {"p_value": 0.25},
            "feasibility": {"status": "PASS"},
            "weights": [],
        }

        self.assertIn("ADMIXTOOLS2 qpAdm", _qpadm_title(QPADM_ENGINE_ADMIXTOOLS2))
        self.assertIn("ADMIXTOOLS2 qpAdm", _format_queue_text(flow, job_id=1, position=1, active_count=1))
        self.assertIn("ADMIXTOOLS2 qpAdm", _format_qpadm_summary(summary, elapsed_seconds=1.0, flow=flow, lang="en"))
        self.assertNotIn("qpAdm classic", _format_queue_text(flow, job_id=1, position=1, active_count=1))

    def test_qpadm_summary_expands_structured_errors(self) -> None:
        flow = {
            "engine": QPADM_ENGINE_ADMIXTOOLS2,
            "dataset": "v66p1_1240k_public",
            "target": "Ramazan",
            "sources": ["Missing_Source.AG"],
            "references": ["Mbuti.DG"],
        }
        summary = {
            "status": "population_not_found",
            "engine": QPADM_ENGINE_ADMIXTOOLS2,
            "engine_status": "backend_not_ready",
            "fit": {"p_value": None},
            "feasibility": {"status": "FAIL"},
            "weights": [],
            "errors": [
                {
                    "code": "population_not_found",
                    "message": "One or more qpAdm sources/references are not available in the selected dataset.",
                    "details": {
                        "missing": [
                            {"role": "source", "label": "Missing_Source.AG"},
                        ]
                    },
                }
            ],
        }

        text = _format_qpadm_summary(summary, elapsed_seconds=2.0, flow=flow, lang="en")

        self.assertIn("Errors", text)
        self.assertIn("Missing_Source.AG", text)
        self.assertIn("Missing in dataset", text)

    def test_exact_qpadm_label_can_be_added_without_population_search(self) -> None:
        flow = {
            "target": "Balkar",
            "sources": [],
            "references": [],
        }

        self.assertTrue(_looks_like_direct_qpadm_label("Mongolia_LBA_Ulaanzukh_2.AG"))
        self.assertFalse(_looks_like_direct_qpadm_label("Sintashta"))

        result = _merge_role_items(flow, "source", ["Mongolia_LBA_Ulaanzukh_2.AG"])

        self.assertEqual(result["added"], ["Mongolia_LBA_Ulaanzukh_2.AG"])
        self.assertEqual(flow["sources"], ["Mongolia_LBA_Ulaanzukh_2.AG"])

    def test_admixtools2_target_menu_supports_population_and_raw_samples(self) -> None:
        classic_callbacks = [
            button.callback_data
            for row in _target_menu_markup({"engine": QPADM_ENGINE_CLASSIC}, "en").inline_keyboard
            for button in row
        ]
        at2_callbacks = [
            button.callback_data
            for row in _target_menu_markup({"engine": QPADM_ENGINE_ADMIXTOOLS2}, "en").inline_keyboard
            for button in row
        ]

        self.assertIn("modeling:qpadm_target_kind:sample", classic_callbacks)
        self.assertIn("modeling:qpadm_target_kind:population", classic_callbacks)
        self.assertIn("modeling:qpadm_import", classic_callbacks)
        self.assertIn("modeling:qpadm_target_kind:sample", at2_callbacks)
        self.assertIn("modeling:qpadm_target_kind:population", at2_callbacks)
        self.assertNotIn("modeling:qpadm_target_kind:multi_population", at2_callbacks)
        self.assertIn("modeling:qpadm_import", at2_callbacks)


class QpadmClassicEngineTests(unittest.TestCase):
    def test_qpadm_args_include_selected_engine(self) -> None:
        flow = {
            "engine": QPADM_ENGINE_ADMIXTOOLS2,
            "dataset": "v62_1240k_public",
            "target_type": "dataset_population",
            "target": "Balkar",
            "sources": ["Sintashta"],
            "references": ["Mbuti"],
        }

        args = _qpadm_args(flow, "admixlab-qpadm-preflight")

        self.assertIn("--engine", args)
        self.assertEqual(args[args.index("--engine") + 1], QPADM_ENGINE_ADMIXTOOLS2)

    def test_qpadm_args_default_to_classic_engine(self) -> None:
        flow = {
            "dataset": "v62_1240k_public",
            "target_type": "dataset_population",
            "target": "Balkar",
            "sources": ["Sintashta"],
            "references": ["Mbuti"],
        }

        args = _qpadm_args(flow, "admixlab-run-qpadm")

        self.assertEqual(args[args.index("--engine") + 1], QPADM_ENGINE_CLASSIC)

    def test_admixtools2_uses_separate_backend_config_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "ADMIXLAB_QPADM_BACKEND_CONFIG": "/etc/admixlab/legacy.json",
                "ADMIXLAB_QPADM_CLASSIC_BACKEND_CONFIG": "/etc/admixlab/classic.json",
                "ADMIXLAB_QPADM_ADMIXTOOLS2_BACKEND_CONFIG": "/etc/admixlab/admixtools2.json",
            },
        ):
            self.assertEqual(_qpadm_backend_config_for_engine(QPADM_ENGINE_CLASSIC), "/etc/admixlab/classic.json")
            self.assertEqual(_qpadm_backend_config_for_engine(QPADM_ENGINE_ADMIXTOOLS2), "/etc/admixlab/admixtools2.json")
            self.assertEqual(
                _qpadm_env(QPADM_ENGINE_ADMIXTOOLS2)["ADMIXLAB_QPADM_BACKEND_CONFIG"],
                "/etc/admixlab/admixtools2.json",
            )

    def test_snapshot_flow_preserves_normalized_engine(self) -> None:
        snapshot = _snapshot_flow(
            {
                "engine": "admixtools2",
                "dataset": "v62_1240k_public",
                "target_type": "dataset_population",
                "target": "Balkar",
                "target_label": "Balkar",
                "sources": ["Sintashta"],
                "references": ["Mbuti"],
            }
        )

        self.assertEqual(snapshot["engine"], QPADM_ENGINE_ADMIXTOOLS2)

    def test_admixtools2_flow_can_collect_multiple_population_targets(self) -> None:
        flow = {
            "engine": QPADM_ENGINE_ADMIXTOOLS2,
            "dataset": "human_origins",
            "target_type": None,
            "target": None,
            "target_label": None,
            "targets": [],
            "sources": ["Barcin_N"],
            "references": ["Mbuti.DG"],
        }

        _add_dataset_target(flow, "Balkar.HO")
        _add_dataset_target(flow, "Karachay.HO")
        _add_dataset_target(flow, "Balkar.HO")

        self.assertEqual(_targets_list(flow), ["Balkar.HO", "Karachay.HO"])
        self.assertEqual(flow["target"], "Balkar.HO")
        self.assertIn("2 targets", _format_queue_text(flow, job_id=1, position=1, active_count=1))
        self.assertEqual(_snapshot_flow(flow)["targets"], ["Balkar.HO", "Karachay.HO"])

    def test_batch_flow_for_target_keeps_sources_and_references(self) -> None:
        flow = {
            "engine": QPADM_ENGINE_ADMIXTOOLS2,
            "dataset": "human_origins",
            "target_type": "dataset_population",
            "target": "Balkar.HO",
            "target_label": "Balkar.HO",
            "targets": ["Balkar.HO", "Karachay.HO"],
            "sources": ["Barcin_N"],
            "references": ["Mbuti.DG"],
        }

        single = _flow_for_target(flow, "Karachay.HO")
        args = _qpadm_args(single, "admixlab-run-qpadm")

        self.assertEqual(single["targets"], ["Karachay.HO"])
        self.assertEqual(args[args.index("--target") + 1], "Karachay.HO")
        self.assertIn("--source", args)
        self.assertIn("--reference", args)

    def test_admixtools2_flow_can_collect_multiple_raw_targets(self) -> None:
        flow = {
            "engine": QPADM_ENGINE_ADMIXTOOLS2,
            "dataset": "human_origins",
            "target_type": None,
            "target": None,
            "target_label": None,
            "targets": [],
            "target_labels": [],
            "sources": ["Barcin_N"],
            "references": ["Mbuti.DG"],
        }

        _add_raw_target(flow, "/tmp/sample_a.txt", "Sample A")
        _add_raw_target(flow, "/tmp/sample_b.txt", "Sample B")
        _add_raw_target(flow, "/tmp/sample_a.txt", "Sample A")

        self.assertEqual(_targets_list(flow), ["/tmp/sample_a.txt", "/tmp/sample_b.txt"])
        self.assertEqual(flow["target"], "/tmp/sample_a.txt")
        self.assertEqual(flow["target_label"], "Sample A")
        self.assertIn("2 targets", _format_queue_text(flow, job_id=1, position=1, active_count=1))
        self.assertEqual(_snapshot_flow(flow)["target_labels"], ["Sample A", "Sample B"])

        single = _flow_for_target(
            flow,
            {"target_type": "raw_file", "target": "/tmp/sample_b.txt", "target_label": "Sample B"},
        )
        args = _qpadm_args(single, "admixlab-run-qpadm")

        self.assertEqual(single["target_type"], "raw_file")
        self.assertEqual(single["target_label"], "Sample B")
        self.assertEqual(args[args.index("--target-type") + 1], "raw_file")
        self.assertEqual(args[args.index("--target") + 1], "/tmp/sample_b.txt")

    def test_admixtools2_supports_dataset_population_and_raw_targets(self) -> None:
        self.assertTrue(
            _has_supported_target_for_engine(
                {"engine": QPADM_ENGINE_ADMIXTOOLS2, "target_type": "dataset_population", "target": "Balkar.HO"}
            )
        )
        self.assertFalse(_has_supported_target_for_engine({"engine": QPADM_ENGINE_ADMIXTOOLS2, "target_type": "dataset_population"}))
        self.assertTrue(_has_supported_target_for_engine({"engine": QPADM_ENGINE_ADMIXTOOLS2, "target_type": "raw_file", "target": "/tmp/raw.txt"}))
        self.assertFalse(_has_supported_target_for_engine({"engine": QPADM_ENGINE_ADMIXTOOLS2, "target_type": "raw_file"}))
        self.assertTrue(_has_supported_target_for_engine({"engine": QPADM_ENGINE_CLASSIC, "target_type": "raw_file"}))


class QpadmClassicJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_qpadm_job_uses_structured_summary_when_command_exits_nonzero(self) -> None:
        flow = {
            "engine": QPADM_ENGINE_ADMIXTOOLS2,
            "dataset": "v66p1_1240k_public",
            "target_type": "dataset_population",
            "target": "Ramazan",
            "target_label": "Ramazan",
            "sources": ["Missing_Source.AG"],
            "references": ["Mbuti.DG"],
        }
        summary = {
            "status": "population_not_found",
            "engine": QPADM_ENGINE_ADMIXTOOLS2,
            "engine_status": "backend_not_ready",
            "target": {"label": "Ramazan", "kind": "dataset_population"},
            "fit": {"p_value": None},
            "feasibility": {"status": "FAIL"},
            "weights": [],
            "errors": [
                {
                    "code": "population_not_found",
                    "message": "One or more qpAdm sources/references are not available in the selected dataset.",
                    "details": {"missing": [{"role": "source", "label": "Missing_Source.AG"}]},
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            async def fake_run_process_result(*args, **kwargs):
                output_path = output_dir / "admixtools2_100_1_7.json"
                output_path.write_text(json.dumps({"status": "population_not_found"}), encoding="utf-8")
                return 1, json.dumps({"status": "population_not_found"}), ""

            with patch("app.features.modeling.qpadm_classic.BOT_QPADM_OUTPUT_DIR", output_dir), patch(
                "app.features.modeling.qpadm_classic.time.time",
                return_value=1,
            ), patch(
                "app.features.modeling.qpadm_classic._run_process_result",
                new=AsyncMock(side_effect=fake_run_process_result),
            ), patch(
                "app.features.modeling.qpadm_classic._load_qpadm_summary",
                new=AsyncMock(return_value=summary),
            ), patch(
                "app.features.modeling.qpadm_classic.render_qpadm_result",
                side_effect=RuntimeError("visual skipped"),
            ):
                text, save_payload = await _run_qpadm_job(flow, 100, job_id=7, lang="en")

        self.assertIn("population_not_found", text)
        self.assertIn("Missing_Source.AG", text)
        self.assertEqual(save_payload["result_payload"], summary)
        self.assertEqual(save_payload["visual_error"], "visual skipped")
        self.assertEqual(save_payload["target_type"], "dataset_population")
        self.assertEqual(save_payload["target_label"], "Ramazan")
        self.assertEqual(save_payload["targets"], ["Ramazan"])
        self.assertEqual(save_payload["target_labels"], ["Ramazan"])

    async def test_run_qpadm_batch_job_preserves_raw_target_metadata_for_saved_models(self) -> None:
        flow = {
            "engine": QPADM_ENGINE_ADMIXTOOLS2,
            "dataset": "human_origins",
            "target_type": "raw_file",
            "target": "/tmp/sample_a.txt",
            "target_label": "Sample A",
            "targets": ["/tmp/sample_a.txt", "/tmp/sample_b.txt"],
            "target_labels": ["Sample A", "Sample B"],
            "sources": ["Barcin_N"],
            "references": ["Mbuti.DG"],
        }
        summary = {
            "status": "completed",
            "engine": QPADM_ENGINE_ADMIXTOOLS2,
            "fit": {"p_value": 0.5},
            "feasibility": {"status": "PASS"},
            "weights": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)

            async def fake_run_process_result(*args, **kwargs):
                return 0, json.dumps({"status": "completed"}), ""

            with patch("app.features.modeling.qpadm_classic.BOT_QPADM_OUTPUT_DIR", output_dir), patch(
                "app.features.modeling.qpadm_classic.time.time",
                return_value=1,
            ), patch(
                "app.features.modeling.qpadm_classic._run_process_result",
                new=AsyncMock(side_effect=fake_run_process_result),
            ), patch(
                "app.features.modeling.qpadm_classic._load_qpadm_summary",
                new=AsyncMock(return_value=summary),
            ), patch(
                "app.features.modeling.qpadm_classic.render_admixtools2_qpadm_batch_result",
                side_effect=RuntimeError("visual skipped"),
            ):
                _text, save_payload = await _run_qpadm_batch_job(flow, 100, job_id=7, lang="en")

        self.assertEqual(save_payload["target_type"], "raw_file")
        self.assertEqual(save_payload["targets"], ["/tmp/sample_a.txt", "/tmp/sample_b.txt"])
        self.assertEqual(save_payload["target_labels"], ["Sample A", "Sample B"])
        self.assertEqual(
            save_payload["target_entries"],
            [
                {"target_type": "raw_file", "target": "/tmp/sample_a.txt", "target_label": "Sample A"},
                {"target_type": "raw_file", "target": "/tmp/sample_b.txt", "target_label": "Sample B"},
            ],
        )
        self.assertEqual(save_payload["visual_error"], "visual skipped")


if __name__ == "__main__":
    unittest.main()
