from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from app.features.modeling.qpadm_classic import (
    QPADM_ENGINE_ADMIXTOOLS2,
    QPADM_ENGINE_CLASSIC,
    _format_messages,
    _format_preflight,
    _qpadm_args,
    _qpadm_backend_config_for_engine,
    _qpadm_env,
    _snapshot_flow,
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


if __name__ == "__main__":
    unittest.main()
