from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.features.reports.g25_platform import G25PlatformReport
from app.features.reports.visualization import build_g25_report_visuals


class ReportsVisualizationTests(unittest.TestCase):
    def test_build_g25_report_visuals_writes_png_cards(self) -> None:
        with TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            analysis_path = output_dir / "analysis.json"
            modern_path = output_dir / "distance_modern.json"
            ancient_path = output_dir / "distance_ancient.json"

            analysis = {
                "sample_name": "Target",
                "artifacts": {
                    "distance_modern": modern_path.name,
                    "distance_ancient": ancient_path.name,
                },
                "routing": {
                    "global": {
                        "modern_macro": {
                            "predicted_group": "West Eurasia",
                            "nearest": [{"reference": "Kabardin", "distance": 0.03123}],
                        },
                        "ancient_macro": {"predicted_group": "WestEurasia"},
                    },
                    "decision": {"selected_regions": [{"label": "West Eurasia"}]},
                    "selected_backbone_branch": "west_eurasia",
                    "regional_backbone": {
                        "west_eurasia": {
                            "modern_cluster": {
                                "predicted_group": "Caucasus_North",
                                "nearest": [{"reference": "Caucasus_North_Kabardin", "distance": 0.04123}],
                            },
                            "ancient_family": {
                                "predicted_group": "Caucasus",
                                "nearest": [{"reference": "WestEurasia_Caucasus_Maikop_Core", "distance": 0.11123}],
                            },
                            "ancient_core": {
                                "predicted_group": "Caucasus_Maikop",
                                "nearest": [{"reference": "WestEurasia_Caucasus_Maikop_Core", "distance": 0.12123}],
                            },
                        }
                    },
                    "regional_reduced_models": {
                        "west_eurasia": {
                            "modern": {
                                "reduced_fit": {
                                    "distance": 0.042,
                                    "sources": 3,
                                    "groups": {
                                        "Caucasus_North": 0.62,
                                        "Europe_Southeast": 0.24,
                                        "Anatolia_West": 0.14,
                                    },
                                }
                            },
                            "ancient": {
                                "reduced_fit": {
                                    "distance": 0.052,
                                    "sources": 3,
                                    "groups": {
                                        "Caucasus_Maikop": 0.55,
                                        "Steppe_EBA": 0.25,
                                        "Anatolia_N": 0.20,
                                    },
                                }
                            },
                        }
                    },
                },
            }
            distance_payload = {
                "sample_name": "Target",
                "results": [
                    {"reference": "Kabardin", "distance": 0.03123},
                    {"reference": "Chechen", "distance": 0.04123},
                ],
            }
            analysis_path.write_text(json.dumps(analysis), encoding="utf-8")
            modern_path.write_text(json.dumps(distance_payload), encoding="utf-8")
            ancient_path.write_text(json.dumps(distance_payload), encoding="utf-8")

            report = G25PlatformReport(
                sample_name="Target",
                coordinate_name="Target G25",
                output_dir=output_dir,
                analysis_path=analysis_path,
                artifact_paths=(),
                summary_lines=("Modern macro: West Eurasia",),
            )

            visuals = build_g25_report_visuals(report)

            self.assertEqual(len(visuals.paths), 3)
            for path in visuals.paths:
                self.assertTrue(path.exists(), path)
                self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
