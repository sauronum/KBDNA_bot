from __future__ import annotations

import unittest

from app.features.modeling.admixtools2 import _format_fstats_result, _parse_populations
from app.features.modeling.qpwave import (
    QPWAVE_ENGINE_ADMIXTOOLS2,
    _extract_admixtools2_ranks,
    _snapshot_flow,
    _start_flow,
)


class ModelingAdmixtools2Tests(unittest.TestCase):
    def test_fstats_population_parser_accepts_keyed_and_plain_lists(self) -> None:
        self.assertEqual(
            _parse_populations("pop1=Mbuti.DG\npop2=Han.DG\npop3=Papuan.DG\npop4=Russia_MA1_UP.SG", 4),
            ["Mbuti.DG", "Han.DG", "Papuan.DG", "Russia_MA1_UP.SG"],
        )
        self.assertEqual(_parse_populations("Mbuti.DG, Han.DG; Papuan.DG", 3), ["Mbuti.DG", "Han.DG", "Papuan.DG"])

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


if __name__ == "__main__":
    unittest.main()
