from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.features.modeling import source_sets as modeling_source_sets
class ModelingSourceSetsDatasetTests(unittest.TestCase):
    def test_source_sets_are_filtered_by_exact_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = modeling_source_sets.SOURCE_SETS_PATH
            modeling_source_sets.SOURCE_SETS_PATH = Path(temp_dir) / "source_sets.json"
            try:
                modeling_source_sets._write_records(
                    [
                        {
                            "id": "v66",
                            "owner_user_id": 42,
                            "dataset": "v66p1_1240k_public",
                            "name": "v66 set",
                            "sources": ["Turkey_N"],
                            "references": ["Mbuti.DG"],
                            "created_at": "2026-01-02T00:00:00Z",
                        },
                        {
                            "id": "v62",
                            "owner_user_id": 42,
                            "dataset": "v62_1240k_public",
                            "name": "v62 set",
                            "sources": ["Turkey_Marmara_Barcin_N.AG"],
                            "references": ["Mbuti.DG"],
                            "created_at": "2026-01-03T00:00:00Z",
                        },
                        {
                            "id": "legacy",
                            "owner_user_id": 42,
                            "name": "legacy set",
                            "sources": ["Turkey_N"],
                            "references": ["Mbuti.DG"],
                            "created_at": "2026-01-04T00:00:00Z",
                        },
                    ]
                )

                rows = modeling_source_sets._user_records(42, dataset="v66p1_1240k_public")

                self.assertEqual([row["id"] for row in rows], ["v66"])
            finally:
                modeling_source_sets.SOURCE_SETS_PATH = original_path

    def test_save_record_rejects_unknown_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = modeling_source_sets.SOURCE_SETS_PATH
            modeling_source_sets.SOURCE_SETS_PATH = Path(temp_dir) / "source_sets.json"
            try:
                with self.assertRaises(ValueError):
                    modeling_source_sets._save_record(
                        42,
                        dataset="v66_made_up",
                        name="bad",
                        sources=["Turkey_N"],
                        references=["Mbuti.DG"],
                    )
            finally:
                modeling_source_sets.SOURCE_SETS_PATH = original_path

    def test_apply_target_context_requires_same_known_dataset(self) -> None:
        context = SimpleNamespace(
            user_data={
                modeling_source_sets.QPADM_FLOW_KEY: {
                    "dataset": "v66p1_1240k_public",
                    "target": "Target",
                }
            }
        )
        compatible = {
            "dataset": "v66p1_1240k_public",
            "sources": ["Turkey_N"],
            "references": ["Mbuti.DG"],
        }
        wrong_dataset = {
            "dataset": "v62_1240k_public",
            "sources": ["Turkey_Marmara_Barcin_N.AG"],
            "references": ["Mbuti.DG"],
        }
        legacy = {
            "sources": ["Turkey_N"],
            "references": ["Mbuti.DG"],
        }

        self.assertIsNotNone(modeling_source_sets._apply_target_context(context, compatible))
        self.assertIsNone(modeling_source_sets._apply_target_context(context, wrong_dataset))
        self.assertIsNone(modeling_source_sets._apply_target_context(context, legacy))


if __name__ == "__main__":
    unittest.main()
