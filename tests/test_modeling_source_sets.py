from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.features.modeling import source_sets as modeling_source_sets
from app.features.vahaduo.ready_model_sets import (
    get_source_set,
    list_source_sets,
    load_source_sets,
    source_set_is_runnable,
)


class VahaduoReadyModelSetsTests(unittest.TestCase):
    def test_source_sets_catalog_loads_expected_models(self) -> None:
        source_sets = list_source_sets()
        ids = [source_set.id for source_set in source_sets]

        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn("steppe_russia", ids)
        self.assertIn("karachay_balkar_hypothesis", ids)
        self.assertIn("broad_west_eurasian", ids)
        self.assertTrue(source_set_is_runnable(get_source_set("steppe_russia")))
        self.assertFalse(source_set_is_runnable(get_source_set("alan_sarmatian_hypothesis")))
        for source_set in source_sets:
            self.assertIn(source_set.status, {"ready", "draft"})
            self.assertEqual(source_set.type, "g25_source_fit")
            self.assertGreater(len(source_set.sources), 0)
            self.assertIn("Это G25-fit модель, не qpAdm.", source_set.interpretation_note)
            self.assertIn("Компоненты являются proxy-источниками.", source_set.interpretation_note)

    def test_invalid_source_sets_file_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "source_sets.json"
            path.write_text(json.dumps({"version": 1, "sets": [{"id": "broken"}]}), encoding="utf-8")

            self.assertEqual(load_source_sets(path), [])


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
