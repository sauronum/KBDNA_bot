from __future__ import annotations

import unittest

from app.features.vahaduo.ready_models_runtime import format_fit_quality, run_source_fitting
from app.features.vahaduo.ready_model_sets import ReadyModelSource, ReadyModelSet, get_source_set


TARGET_G25 = (
    "MixedTarget,0.10204215,0.05361980,-0.00959775,0.00521645,-0.00834005,0.01250845,"
    "0.00991735,-0.00725725,-0.02947195,-0.02523055,-0.01119655,0.00053965,-0.00709110,"
    "-0.00624105,0.01034865,0.00704065,0.01158445,-0.00107655,0.00327420,0.01131805,"
    "0.00958305,0.00527965,-0.00698785,0.00172315,0.00096380"
)


class VahaduoReadyModelsRuntimeTests(unittest.TestCase):
    def test_run_source_fitting_returns_ok_result(self) -> None:
        source_set = get_source_set("karachay_balkar_hypothesis")
        self.assertIsNotNone(source_set)

        result = run_source_fitting("Заур", TARGET_G25, source_set)  # type: ignore[arg-type]

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.target_name, "Заур")
        self.assertEqual(result.source_set_id, "karachay_balkar_hypothesis")
        self.assertIsNotNone(result.distance)
        self.assertGreaterEqual(len(result.components), 3)
        self.assertEqual([component.source_name for component in result.components[:3]], ["Maikop", "Steppe", "YR"])
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
