from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from stores.vahaduo import (
    CustomPanelStore,
    G25AccessStore,
    VahaduoFullStore,
    VahaduoSavedSourceStore,
    VahaduoSavedTargetStore,
)


def _fake_update(user_id: int = 42, username: str = "tester") -> SimpleNamespace:
    return SimpleNamespace(effective_user=SimpleNamespace(id=user_id, username=username))


class G25AccessStoreTests(unittest.TestCase):
    def test_normalizes_usernames_and_checks_admins(self) -> None:
        store = G25AccessStore(Path("unused.json"), admin_ids={1}, admin_usernames={"Admin"})

        self.assertEqual(store._normalize_username("@Admin "), "admin")
        self.assertTrue(store.is_admin(_fake_update(1, "someone")))
        self.assertTrue(store.is_admin(_fake_update(2, "admin")))
        self.assertFalse(store.is_admin(_fake_update(2, "other")))


class VahaduoSavedStoreTests(unittest.TestCase):
    def test_saved_source_store_crud_and_kind_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_path = root / "source.txt"
            source_path.write_text("Sample,1,2,3\n", encoding="utf-8")
            store = VahaduoSavedSourceStore(root / "sources.sqlite3", root / "sources")

            saved = store.save_for_user(
                _fake_update(),
                title=" My Source ",
                source_path=source_path,
                source_count=1,
                source_label="My Source",
                source_input_mode="file",
                source_kind="multi",
            )

            self.assertEqual(saved["title"], "My Source")
            self.assertEqual(saved["source_kind"], "single")
            self.assertEqual(len(store.list_for_user(42, "single")), 1)
            self.assertEqual(len(store.list_for_user(42, "distance")), 0)
            self.assertTrue(store.delete_for_user(42, int(saved["id"])))
            self.assertEqual(store.list_for_user(42), [])

    def test_saved_target_store_crud(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target_path = root / "target.g25"
            target_path.write_text("Target,1,2,3\n", encoding="utf-8")
            store = VahaduoSavedTargetStore(root / "targets.sqlite3", root / "targets")

            saved = store.save_for_user(
                _fake_update(),
                title=" Target ",
                target_name="Target",
                target_path=target_path,
                target_input_mode="text",
            )

            self.assertEqual(saved["title"], "Target")
            self.assertEqual(len(store.list_for_user(42)), 1)
            self.assertTrue(store.delete_for_user(42, int(saved["id"])))
            self.assertEqual(store.list_for_user(42), [])


class InMemoryPanelStoreTests(unittest.TestCase):
    def test_custom_panel_store_tracks_selection_and_pending(self) -> None:
        store = CustomPanelStore()

        self.assertEqual(store.toggle(1, 2, "maikop"), ["maikop"])
        self.assertEqual(store.finish(1, 2), ["maikop"])
        self.assertTrue(store.has_pending(1, 2))
        store.clear_pending(1, 2)
        self.assertFalse(store.has_pending(1, 2))
        store.cancel(1, 2)
        self.assertIsNone(store.get(1, 2))

    def test_vahaduo_full_store_tracks_source_target_and_mode(self) -> None:
        store = VahaduoFullStore()

        state = store.set_source(
            1,
            2,
            source_key="custom",
            source_label="Custom",
            source_path=Path("source.txt"),
            source_count=3,
            source_input_mode="file",
        )
        self.assertEqual(state["source_label"], "Custom")

        state = store.set_target(
            1,
            2,
            target_label="Target",
            target_path=Path("target.g25"),
            target_input_mode="text",
        )
        self.assertEqual(state["target_label"], "Target")

        store.set_mode(1, 2, "single", awaiting="target")
        self.assertTrue(store.has_pending(1, 2, "target"))
        store.cancel(1, 2)
        self.assertIsNone(store.get(1, 2))


if __name__ == "__main__":
    unittest.main()
