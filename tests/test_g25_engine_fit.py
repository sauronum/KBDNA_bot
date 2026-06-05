from __future__ import annotations

import unittest
from pathlib import Path

from g25_core import g25_engine


ROOT_DIR = Path(__file__).resolve().parents[1]
TARGET_ZAUR = g25_engine.G25Entry(
    "Заур",
    (
        0.11329207,
        0.08222063,
        -0.01682855,
        -0.00089987,
        -0.02810336,
        0.00768269,
        0.01047033,
        -0.00092467,
        -0.05459405,
        -0.03202557,
        -0.00598673,
        0.00700874,
        -0.01590565,
        0.00236356,
        0.00996475,
        -0.01343122,
        0.00264223,
        -0.00349443,
        -0.00661213,
        0.01304836,
        0.00265609,
        0.00156566,
        0.00474135,
        0.00136679,
        -0.00376188,
    ),
)


class G25PanelFitTests(unittest.TestCase):
    def test_panel_fit_matches_vahaduo_single_reference(self) -> None:
        source_files = [
            ("Maikop", "Maikop.txt"),
            ("Steppe", "Steppe_Sintashta.txt"),
            ("YR", "YellowRiver.txt"),
        ]
        references = []
        manifest = {}
        for group, file_name in source_files:
            path = ROOT_DIR / "g25_core" / "panels" / "custom_sources" / file_name
            for reference in g25_engine.load_g25_entries(path):
                references.append(reference)
                manifest[reference.name] = {"group": group, "panel_name": "Custom panel"}

        fit = g25_engine.summarize_panel_fit(TARGET_ZAUR, references, manifest, "group", 250, 12)

        self.assertEqual(fit["distance"], 0.015672)
        self.assertLess(fit["iterations"], 250)
        self.assertAlmostEqual(fit["groups"]["Maikop"], 0.609372, places=6)
        self.assertAlmostEqual(fit["groups"]["Steppe"], 0.324876, places=6)
        self.assertAlmostEqual(fit["groups"]["YR"], 0.065752, places=6)


if __name__ == "__main__":
    unittest.main()
