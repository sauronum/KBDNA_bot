from __future__ import annotations

import unittest

from app.features.vahaduo.ready_models_runtime import format_fit_quality, run_source_fitting
from app.features.vahaduo.ready_model_sets import ReadyModelSource, ReadyModelSet, get_source_set


TARGET_G25 = (
    "TestTarget,0.105855,0.119832,-0.05242,-0.028101,-0.043085,0.000837,"
    "0.00893,-0.008538,-0.05154,-0.031527,0.003573,0.004496,-0.012636,"
    "0.001239,0.002036,0.002917,0.019427,-0.003547,0.001508,0.018384,"
    "0.007861,-0.002226,-0.006655,0,0.001676"
)


class VahaduoReadyModelsRuntimeTests(unittest.TestCase):
    def test_run_source_fitting_returns_ok_result(self) -> None:
        source_set = get_source_set("steppe_russia")
        self.assertIsNotNone(source_set)

        result = run_source_fitting("Заур", TARGET_G25, source_set)  # type: ignore[arg-type]

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.target_name, "Заур")
        self.assertEqual(result.source_set_id, "steppe_russia")
        self.assertIsNotNone(result.distance)
        self.assertGreater(len(result.components), 0)
        self.assertAlmostEqual(sum(component.percent for component in result.components), 100.0, delta=0.2)

    def test_run_source_fitting_reports_missing_sources(self) -> None:
        source_set = ReadyModelSet(
            id="missing_model",
            title="Missing model",
            short_title="Missing model",
            status="ready",
            type="g25_source_fit",
            description="Missing source test.",
            interpretation_note="Это G25-fit модель, не qpAdm. Компоненты являются proxy-источниками.",
            sources=(ReadyModelSource("Missing", "🧪", "Definitely_Missing_Source"),),
        )

        result = run_source_fitting("Заур", TARGET_G25, source_set)

        self.assertEqual(result.status, "source_missing")
        self.assertIn("Definitely_Missing_Source", result.missing_sources)

    def test_format_fit_quality(self) -> None:
        self.assertEqual(format_fit_quality(0.019), "хороший")
        self.assertEqual(format_fit_quality(0.025), "средний")
        self.assertEqual(format_fit_quality(0.035), "слабый")


if __name__ == "__main__":
    unittest.main()
