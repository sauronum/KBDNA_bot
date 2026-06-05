from __future__ import annotations

import gzip
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.features.my_data.storage import MyDataStore, RawArchiveError


RAW_CONTENT = "rsid,chromosome,position,genotype\nrs1,1,100,AA\n"


class MyDataStorageTests(unittest.TestCase):
    def test_save_raw_file_extracts_csv_from_zip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "upload.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("notes/readme.md", "metadata")
                archive.writestr("sample/raw.csv", RAW_CONTENT)

            store = MyDataStore(root / "my_data")
            asset = store.save_raw_file(
                1,
                archive_path,
                original_file_name="upload.zip",
                display_name="Sample raw",
            )

            stored_path = store.resolve_raw_file_path(asset)
            self.assertEqual(asset.original_file_name, "raw.csv")
            self.assertEqual(stored_path.suffix, ".csv")
            self.assertEqual(stored_path.read_text(encoding="utf-8"), RAW_CONTENT)

    def test_save_raw_file_extracts_gz_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "raw.csv.gz"
            with gzip.open(archive_path, "wt", encoding="utf-8") as archive:
                archive.write(RAW_CONTENT)

            store = MyDataStore(root / "my_data")
            asset = store.save_raw_file(
                1,
                archive_path,
                original_file_name="raw.csv.gz",
                display_name="",
            )

            stored_path = store.resolve_raw_file_path(asset)
            self.assertEqual(asset.original_file_name, "raw.csv")
            self.assertEqual(asset.display_name, "raw")
            self.assertEqual(stored_path.read_text(encoding="utf-8"), RAW_CONTENT)

    def test_save_raw_file_rejects_rar_instead_of_storing_broken_sample_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive_path = root / "raw.rar"
            archive_path.write_bytes(b"not parsed as raw")
            store = MyDataStore(root / "my_data")

            with self.assertRaises(RawArchiveError) as caught:
                store.save_raw_file(
                    1,
                    archive_path,
                    original_file_name="raw.rar",
                    display_name="Raw",
                )

            self.assertEqual(caught.exception.reason, "rar_not_supported")
            self.assertEqual(store.list_raw_files(1), [])


if __name__ == "__main__":
    unittest.main()
