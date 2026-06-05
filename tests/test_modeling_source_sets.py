from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
