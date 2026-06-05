from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.features.my_data.storage import MyDataStore
from app.features.settings import menu as settings_menu
from app.features.settings.storage import UserSettingsStore
from app.storage_io import write_json_atomic, write_text_atomic


class StorageIoTests(unittest.TestCase):
    def test_write_json_atomic_replaces_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.json"
            path.write_text('{"old": true}', encoding="utf-8")

            write_json_atomic(path, {"items": ["один", "two"]})

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"items": ["один", "two"]})
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_write_text_atomic_keeps_existing_file_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.txt"
            path.write_text("original", encoding="utf-8")

            with patch("app.storage_io.os.fsync", side_effect=OSError("disk error")):
                with self.assertRaises(OSError):
                    write_text_atomic(path, "new")

            self.assertEqual(path.read_text(encoding="utf-8"), "original")
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    def test_user_settings_store_uses_atomic_json_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = UserSettingsStore(Path(tmp))

            settings = store.set_language(42, "en")

            self.assertEqual(settings.language, "en")
            self.assertEqual(settings.card_format, "wide")
            self.assertEqual(settings.result_mode, "simple")
            self.assertEqual(settings.search_base, "kbdna")
            self.assertTrue(settings.notifications_enabled)
            self.assertEqual(
                json.loads((Path(tmp) / "42.json").read_text(encoding="utf-8")),
                {
                    "language": "en",
                    "card_format": "wide",
                    "result_mode": "simple",
                    "search_base": "kbdna",
                    "notifications_enabled": True,
                },
            )

    def test_user_settings_store_preserves_all_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = UserSettingsStore(Path(tmp))

            settings = store.set_language(42, "en")
            settings = store.set_card_format(42, "mobile")
            settings = store.set_result_mode(42, "advanced")
            settings = store.set_search_base(42, "abkhaz")
            settings = store.set_notifications_enabled(42, False)
            self.assertEqual(settings.language, "en")
            self.assertEqual(settings.card_format, "mobile")
            self.assertEqual(settings.result_mode, "advanced")
            self.assertEqual(settings.search_base, "abkhaz")
            self.assertFalse(settings.notifications_enabled)

            settings = store.set_language(42, "ru")
            self.assertEqual(settings.language, "ru")
            self.assertEqual(settings.card_format, "mobile")
            self.assertEqual(settings.result_mode, "advanced")
            self.assertEqual(settings.search_base, "abkhaz")
            self.assertFalse(settings.notifications_enabled)

            settings = store.set_card_format(42, "wide")
            self.assertEqual(settings.language, "ru")
            self.assertEqual(settings.card_format, "wide")
            self.assertEqual(settings.result_mode, "advanced")
            self.assertEqual(settings.search_base, "abkhaz")
            self.assertFalse(settings.notifications_enabled)

            settings = store.set_result_mode(42, "simple")
            self.assertEqual(settings.language, "ru")
            self.assertEqual(settings.card_format, "wide")
            self.assertEqual(settings.result_mode, "simple")
            self.assertEqual(settings.search_base, "abkhaz")
            self.assertFalse(settings.notifications_enabled)
            self.assertEqual(store.get_card_format(42), "wide")
            self.assertEqual(store.get_result_mode(42), "simple")
            self.assertEqual(store.get_search_base(42), "abkhaz")
            self.assertFalse(store.get_notifications_enabled(42))

    def test_privacy_export_and_delete_user_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user_id = 42
            my_data_store = MyDataStore(root / "my_data")
            settings_store = UserSettingsStore(root / "user_settings")
            raw_source = root / "raw.txt"
            raw_source.write_text("rs1\tAA\n", encoding="utf-8")

            raw = my_data_store.save_raw_file(
                user_id,
                raw_source,
                original_file_name="raw.txt",
                display_name="Raw",
            )
            sample = my_data_store.save_sample(user_id, display_name="Sample", raw_file_id=raw.asset_id)
            self.assertIsNotNone(sample)
            my_data_store.save_coordinate(
                user_id,
                display_name="G25",
                target_name="Target",
                coordinate_type="g25",
                g25_line="Target,0.1,0.2",
                input_mode="manual",
            )
            settings_store.set_language(user_id, "en")
            context = SimpleNamespace(
                application=SimpleNamespace(
                    bot_data={
                        "my_data_store": my_data_store,
                        "user_settings_store": settings_store,
                    }
                ),
                user_data={"reports_back_callback": "main:privacy"},
            )

            archive_path = settings_menu.export_user_data_archive(context, user_id)
            try:
                with zipfile.ZipFile(archive_path) as archive:
                    names = set(archive.namelist())
                    self.assertIn("manifest.json", names)
                    self.assertIn("my_data/raw_files.json", names)
                    self.assertIn("my_data/samples.json", names)
                    self.assertIn("my_data/coordinates.json", names)
                    self.assertIn("settings/42.json", names)
            finally:
                archive_path.unlink(missing_ok=True)

            deleted = settings_menu.delete_user_data(context, user_id)

            self.assertEqual(deleted.samples, 1)
            self.assertEqual(deleted.raw_files, 1)
            self.assertEqual(deleted.g25_profiles, 1)
            self.assertFalse((root / "my_data" / "users" / str(user_id)).exists())
            self.assertFalse((root / "user_settings" / "42.json").exists())
            self.assertNotIn("reports_back_callback", context.user_data)
