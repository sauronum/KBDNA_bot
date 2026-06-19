from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from telegram.ext import ApplicationHandlerStop

from app.features.haplogroups.domain import (
    DEFAULT_Y_SNP_REFERENCE_PATH,
    compare_y_str_profiles,
    load_y_snp_reference,
    normalize_haplogroup_value,
    parse_haplogroup_result_file,
    parse_y_str_result_file,
    predict_y_haplogroup_from_raw,
    scan_raw_haplogroup_markers,
)
from app.features.haplogroups.menu import (
    HAPLOGROUPS_CALLBACK_PREFIX,
    HAPLOGROUP_RESULT_UPLOAD_LIMIT_BYTES,
    HaplogroupFlowStore,
    _BRANCH_LOOKUP_ACTION,
    _FILE_UPLOAD_ACTION,
    _import_haplogroup_document,
    _paginate_records,
    _send_branch_visual,
    haplogroups_document_input_handler,
    haplogroups_text_input_handler,
    parse_haplogroup_input,
    show_branch_lookup_prompt,
    show_haplogroups_menu,
)
from app.features.haplogroups.storage import HaplogroupRecord, HaplogroupStore
from app.features.haplogroups.ui import raw_scan_result_text, str_distance_text
from app.features.haplogroups.yfull import YFullBranch, YFullChildBranch, YFullGeography, YFullLookupResult
from app.features.my_data.storage import SampleAsset


def _write_raw(path: Path, rows: list[tuple[str, str, int, str]]) -> None:
    body = ["rsid\tchromosome\tposition\tgenotype"]
    body.extend(f"{rsid}\t{chromosome}\t{position}\t{genotype}" for rsid, chromosome, position, genotype in rows)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


def _haplogroup_record(index: int) -> HaplogroupRecord:
    return HaplogroupRecord(
        record_id=f"record-{index}",
        sample_id="sample-1",
        sample_name="Sample One",
        haplogroup_type="Y-DNA",
        haplogroup=f"J{index}",
        terminal_snp="",
        source="",
        confidence="user-entered",
        note="",
        created_at="2026-06-16T00:00:00",
    )


class HaplogroupTests(unittest.TestCase):
    def test_pending_flow_expires(self) -> None:
        flow = HaplogroupFlowStore(ttl_seconds=10)
        with patch("app.features.haplogroups.menu.time.monotonic", side_effect=[100.0, 111.0]):
            flow.expect(10, 123, {"sample_id": "sample-1"})
            self.assertIsNone(flow.get(10, 123))

    def test_parse_haplogroup_input_accepts_optional_fields(self) -> None:
        parsed = parse_haplogroup_input(
            "\n".join(
                [
                    "J2a1a1b2",
                    "terminal: J-Y12345",
                    "source: FTDNA",
                    "confidence: confirmed",
                    "note: Big Y result",
                ]
            )
        )

        self.assertEqual(parsed["haplogroup"], "J2a1a1b2")
        self.assertEqual(parsed["terminal_snp"], "J-Y12345")
        self.assertEqual(parsed["source"], "FTDNA")
        self.assertEqual(parsed["confidence"], "confirmed")
        self.assertEqual(parsed["note"], "Big Y result")

    def test_manual_and_imported_haplogroups_are_validated_and_normalized(self) -> None:
        self.assertEqual(normalize_haplogroup_value("r-m269"), "R-M269")
        self.assertEqual(normalize_haplogroup_value("hv12a2"), "HV12a2")
        self.assertEqual(parse_haplogroup_input("haplogroup: j2a1a")["haplogroup"], "J2a1a")
        self.assertEqual(parse_haplogroup_input("Smith")["haplogroup"], "")

    def test_haplogroup_store_saves_sample_records(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = HaplogroupStore(Path(temp_dir))
            record = store.save_record(
                123,
                sample_id="sample-1",
                sample_name="Sample One",
                haplogroup_type="Y-DNA",
                haplogroup="J2a",
                terminal_snp="M172",
                source="23andMe",
            )

            records = store.list_sample_records(123, "sample-1")
            profile = store.save_y_str_profile(
                123,
                sample_id="sample-1",
                sample_name="Sample One",
                source="FTDNA file",
                marker_values={"DYS393": [14], "DYS390": [22]},
            )
            loaded_profile = store.find_y_str_profile(123, profile.profile_id)

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_id, record.record_id)
        self.assertEqual(records[0].haplogroup, "J2a")
        self.assertEqual(records[0].terminal_snp, "M172")
        self.assertIsNotNone(loaded_profile)
        assert loaded_profile is not None
        self.assertEqual(loaded_profile.marker_values["DYS393"], [14])

    def test_haplogroup_store_replaces_duplicate_sample_record(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = HaplogroupStore(Path(temp_dir))
            first = store.save_record(
                123,
                sample_id="sample-1",
                sample_name="Sample One",
                haplogroup_type="Y-DNA",
                haplogroup="G2a1a1a1",
                terminal_snp="Z6638",
                source="FTDNA",
            )
            second = store.save_record(
                123,
                sample_id="sample-1",
                sample_name="Sample One",
                haplogroup_type="Y-DNA",
                haplogroup="G2a1a1a1",
                terminal_snp="Z6638",
                source="FTDNA SNP Results",
            )

            records = store.list_sample_records(123, "sample-1")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].record_id, second.record_id)
        self.assertNotEqual(records[0].record_id, first.record_id)
        self.assertEqual(records[0].source, "FTDNA SNP Results")

    def test_sample_data_deletion_removes_haplogroups_and_y_str(self) -> None:
        with TemporaryDirectory() as temp_dir:
            store = HaplogroupStore(Path(temp_dir))
            store.save_record(123, sample_id="sample-1", sample_name="One", haplogroup_type="Y-DNA", haplogroup="R-M269")
            store.save_y_str_profile(123, sample_id="sample-1", sample_name="One", source="FTDNA", marker_values={"DYS393": [13]})

            removed = store.delete_sample_data(123, "sample-1")

            self.assertEqual(removed, (1, 1))
            self.assertEqual(store.list_sample_records(123, "sample-1"), [])
            self.assertEqual(store.list_y_str_profiles(123), [])

    def test_combined_file_imports_haplogroup_and_y_str(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "combined.csv"
            path.write_text(
                "Y-DNA Haplogroup,DYS393,DYS390,DYS19,DYS391,DYS385\n"
                "r-m269,13,24,14,10,11-14\n",
                encoding="utf-8",
            )
            store = HaplogroupStore(Path(temp_dir) / "store")
            sample = SampleAsset("sample-1", "One", "raw-1", [], "2026-06-18T00:00:00")

            records, profile = _import_haplogroup_document(store, 123, sample, path, path.name)

            self.assertEqual(records[0].haplogroup, "R-M269")
            self.assertIsNotNone(profile)
            assert profile is not None
            self.assertEqual(profile.marker_count, 5)

    def test_raw_haplogroup_scan_counts_y_and_mt_markers(self) -> None:
        with TemporaryDirectory() as temp_dir:
            raw_path = Path(temp_dir) / "raw.tsv"
            _write_raw(
                raw_path,
                [
                    ("rs_y_1", "ChrY", 100, "A"),
                    ("rs_y_2", "24", 200, "AG"),
                    ("rs_mt_1", "MT", 300, "CC"),
                    ("rs_mt_2", "25", 350, "T"),
                    ("rs_auto", "1", 400, "TT"),
                ],
            )

            y_scan = scan_raw_haplogroup_markers(raw_path, "Y-DNA")
            mt_scan = scan_raw_haplogroup_markers(raw_path, "mtDNA")

        self.assertEqual(y_scan.total_markers, 2)
        self.assertEqual(y_scan.called_markers, 2)
        self.assertEqual(mt_scan.total_markers, 2)
        self.assertEqual(mt_scan.called_markers, 2)
        self.assertEqual(y_scan.chromosome_counts["Y"], 1)
        self.assertEqual(y_scan.genotype_counts["A"], 1)
        self.assertEqual(len(mt_scan.marker_examples), 2)

    def test_raw_scan_result_uses_english_note(self) -> None:
        with TemporaryDirectory() as temp_dir:
            raw_path = Path(temp_dir) / "raw.tsv"
            _write_raw(raw_path, [("rs_y_1", "ChrY", 100, "A")])
            scan = scan_raw_haplogroup_markers(raw_path, "Y-DNA")

        sample = SampleAsset("sample-1", "Demo", "raw-1", [], "2026-05-01T00:00:00")
        text = raw_scan_result_text(sample, scan, lang="en")

        self.assertIn("Too few markers were found", text)
        self.assertNotIn("Найдено слишком мало", text)

    def test_parse_haplogroup_result_file_reads_labeled_text(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "ftdna-results.txt"
            result_path.write_text(
                "\n".join(
                    [
                        "Y-DNA Haplogroup: J2a1a2a",
                        "Y-DNA Terminal SNP: PF5116",
                        "mtDNA Haplogroup: H13a1a",
                    ]
                ),
                encoding="utf-8",
            )

            results = parse_haplogroup_result_file(result_path, original_file_name="FTDNA_results.txt")

        by_type = {item.haplogroup_type: item for item in results}
        self.assertEqual(by_type["Y-DNA"].haplogroup, "J2a1a2a")
        self.assertEqual(by_type["Y-DNA"].terminal_snp, "PF5116")
        self.assertEqual(by_type["Y-DNA"].source, "FTDNA file")
        self.assertEqual(by_type["mtDNA"].haplogroup, "H13a1a")

    def test_parse_haplogroup_result_file_reads_csv_columns(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "results.csv"
            result_path.write_text(
                "Name,Y-DNA Haplogroup,Y-DNA Terminal SNP,Maternal Haplogroup\n"
                "Adam,J-PF5116,PF5116,H13a1a\n",
                encoding="utf-8",
            )

            results = parse_haplogroup_result_file(result_path)

        by_type = {item.haplogroup_type: item for item in results}
        self.assertEqual(by_type["Y-DNA"].haplogroup, "J-PF5116")
        self.assertEqual(by_type["Y-DNA"].terminal_snp, "PF5116")
        self.assertEqual(by_type["mtDNA"].haplogroup, "H13a1a")

    def test_parse_haplogroup_result_file_reads_ftdna_snp_results(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            reference_path = temp_path / "isogg.tsv"
            reference_path.write_text(
                "\t".join(["SNP ", "Haplogroup ", "Other Names ", "RefSNP ID ", "Y-position (GRCh37)", "Mutation"])
                + "\n"
                + "\t".join(["J1", "J2a1", "", "", "100", "A->G"])
                + "\n"
                + "\t".join(["PF5116", "J2a1a2a", "J-TEST", "rs123", "200", "C->T"])
                + "\n"
                + "\t".join(["R1", "R1b", "", "", "300", "G->A"])
                + "\n",
                encoding="utf-8",
            )
            result_path = temp_path / "SNP_Results_BP98335.csv"
            result_path.write_text(
                "SNP Name,Test Result,Test Type\n"
                "J1,Positive,BigY\n"
                "J-TEST,Positive,BigY\n"
                "R1,Negative,BigY\n",
                encoding="utf-8",
            )

            results = parse_haplogroup_result_file(
                result_path,
                original_file_name="SNP_Results_BP98335.csv",
                reference_path=reference_path,
            )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].haplogroup_type, "Y-DNA")
        self.assertEqual(results[0].haplogroup, "J2a1a2a")
        self.assertEqual(results[0].terminal_snp, "PF5116")
        self.assertEqual(results[0].source, "FTDNA SNP Results")
        self.assertEqual(results[0].confidence, "snp-file")
        self.assertEqual(results[0].positive_snp_count, 2)
        self.assertEqual(results[0].matched_snp_count, 2)
        self.assertEqual(results[0].lineage_votes[0], ("J", 2))

    def test_parse_y_str_result_file_reads_ftdna_dys_profile(self) -> None:
        with TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "BP98335_YDNA_DYS_Results_20260501.csv"
            result_path.write_text(
                "DYS393,DYS390,DYS19,DYS385,CDY\n"
                "\" 14\",\" 22\",\" 15\",\" 14-16\",\" 36-38-39\"\n",
                encoding="utf-8",
            )

            profile = parse_y_str_result_file(result_path, original_file_name=result_path.name)

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.marker_count, 5)
        self.assertEqual(profile.marker_values["DYS393"], [14])
        self.assertEqual(profile.marker_values["DYS385"], [14, 16])
        self.assertEqual(profile.marker_values["CDY"], [36, 38, 39])

    def test_compare_y_str_profiles_counts_marker_distance(self) -> None:
        result = compare_y_str_profiles(
            "A",
            {"DYS393": [14], "DYS385": [14, 16], "DYS390": [22]},
            "B",
            {"DYS393": [13], "DYS385": [14, 17], "DYS390": [22]},
        )

        self.assertEqual(result.compared_markers, 3)
        self.assertEqual(result.distance, 2)
        self.assertEqual(result.differences[0][0], "DYS385")

    def test_y_str_without_shared_markers_does_not_report_zero_distance(self) -> None:
        result = compare_y_str_profiles("A", {"DYS393": [13]}, "B", {"DYS390": [24]})

        text = str_distance_text(result, "en")

        self.assertEqual(result.compared_markers, 0)
        self.assertNotIn("Genetic distance", text)
        self.assertIn("distance was not calculated", text)

    def test_y_snp_prediction_uses_derived_reference_alleles(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            reference_path = temp_path / "isogg.tsv"
            reference_path.write_text(
                "\t".join(["SNP ", "Haplogroup ", "Other Names ", "RefSNP ID ", "Y-position (GRCh37)", "Mutation"])
                + "\n"
                + "\t".join(["M1", "A1", "", "", "100", "A->G"])
                + "\n"
                + "\t".join(["M2", "A1b", "", "", "200", "C->T"])
                + "\n",
                encoding="utf-8",
            )
            raw_path = temp_path / "raw.tsv"
            _write_raw(raw_path, [("rs1", "Y", 100, "GG"), ("rs2", "Y", 200, "TT")])

            prediction = predict_y_haplogroup_from_raw(raw_path, reference_path=reference_path)

        self.assertEqual(prediction.haplogroup, "A1b")
        self.assertEqual(prediction.terminal_snp, "M2")
        self.assertEqual(len(prediction.positive_calls), 2)

    def test_y_snp_prediction_ignores_removed_haplogroups_for_best_call(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            reference_path = temp_path / "isogg.tsv"
            reference_path.write_text(
                "\t".join(["SNP ", "Haplogroup ", "Other Names ", "RefSNP ID ", "Y-position (GRCh37)", "Mutation"])
                + "\n"
                + "\t".join(["BAD", "Removed from R", "", "", "100", "A->G"])
                + "\n"
                + "\t".join(["GOOD", "R1b1a", "", "", "200", "C->T"])
                + "\n",
                encoding="utf-8",
            )
            raw_path = temp_path / "raw.tsv"
            _write_raw(raw_path, [("rs1", "Y", 100, "GG"), ("rs2", "Y", 200, "TT")])

            prediction = predict_y_haplogroup_from_raw(raw_path, reference_path=reference_path)

        self.assertEqual(prediction.haplogroup, "R1b1a")
        self.assertEqual(prediction.terminal_snp, "GOOD")
        self.assertEqual([call.snp_name for call in prediction.positive_calls], ["GOOD"])

    def test_y_snp_prediction_prefers_supported_lineage_over_single_deep_conflict(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            reference_path = temp_path / "isogg.tsv"
            reference_path.write_text(
                "\t".join(["SNP ", "Haplogroup ", "Other Names ", "RefSNP ID ", "Y-position (GRCh37)", "Mutation"])
                + "\n"
                + "\t".join(["R1", "R1b", "", "", "100", "A->G"])
                + "\n"
                + "\t".join(["R2", "R1b1a", "", "", "200", "C->T"])
                + "\n"
                + "\t".join(["R3", "R1b1a2", "", "", "300", "G->A"])
                + "\n"
                + "\t".join(["E_DEEP", "E1b1b1a1b1a5", "", "", "400", "T->C"])
                + "\n",
                encoding="utf-8",
            )
            raw_path = temp_path / "raw.tsv"
            _write_raw(
                raw_path,
                [
                    ("rs1", "Y", 100, "GG"),
                    ("rs2", "Y", 200, "TT"),
                    ("rs3", "Y", 300, "AA"),
                    ("rs4", "Y", 400, "CC"),
                ],
            )

            prediction = predict_y_haplogroup_from_raw(raw_path, reference_path=reference_path)

        self.assertEqual(prediction.haplogroup, "R1b1a2")
        self.assertEqual(prediction.terminal_snp, "R3")
        self.assertEqual(prediction.lineage_counts[0], ("R", 3))
        self.assertEqual(prediction.conflicting_positive_calls[0].snp_name, "E_DEEP")

    def test_y_snp_prediction_does_not_count_ct_as_c_lineage(self) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            reference_path = temp_path / "isogg.tsv"
            rows = [
                ["SNP ", "Haplogroup ", "Other Names ", "RefSNP ID ", "Y-position (GRCh37)", "Mutation"],
                ["CT1", "CT", "", "", "100", "A->G"],
                ["CT2", "CT", "", "", "200", "A->G"],
                ["C1", "C1a2a", "", "", "300", "A->G"],
                ["R1", "R1b", "", "", "400", "A->G"],
                ["R2", "R1b1a", "", "", "500", "A->G"],
            ]
            reference_path.write_text("\n".join("\t".join(row) for row in rows) + "\n", encoding="utf-8")
            raw_path = temp_path / "raw.tsv"
            _write_raw(
                raw_path,
                [
                    ("rs1", "Y", 100, "GG"),
                    ("rs2", "Y", 200, "GG"),
                    ("rs3", "Y", 300, "GG"),
                    ("rs4", "Y", 400, "GG"),
                    ("rs5", "Y", 500, "GG"),
                ],
            )

            prediction = predict_y_haplogroup_from_raw(raw_path, reference_path=reference_path)

        self.assertEqual(prediction.haplogroup, "R1b1a")
        self.assertEqual(prediction.lineage_counts[0], ("R", 2))
        self.assertNotIn("CT1", [call.snp_name for call in prediction.positive_calls])

    def test_default_y_snp_reference_loads(self) -> None:
        markers = load_y_snp_reference(DEFAULT_Y_SNP_REFERENCE_PATH)

        self.assertGreater(len(markers), 1000)

    def test_haplogroup_callback_data_stays_under_telegram_limit(self) -> None:
        asset_id = "20260430185412345678-12345678"
        record_id = "20260501090012345678-12345678"
        callbacks = [
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:root",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:trees",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:branch",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:branch:mt",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:bn:0123456789ab",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:bn:mt:0123456789ab",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:bv:0123456789ab",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:bv:mt:0123456789ab",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:y",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:mt",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:detect",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:manual",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:upload",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:upload:1",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:saved",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:saved:1",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:str",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:strv:{record_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:scmp",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:stra:{record_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:strb:{record_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:list:all:1",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:list:y",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:list:y:1",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:list:mt",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:list:mt:1",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:add:y:0",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:add:mt:0",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:dadd:y:0",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:dadd:mt:0",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:pick:y:{asset_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:pick:mt:{asset_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:dpick:y:{asset_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:dpick:mt:{asset_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:yp:{asset_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:upick:{asset_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:sample:{asset_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:sample:{asset_id}:1",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:hsample:{asset_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:hsample:{asset_id}:1",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:o:{record_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:ho:{record_id}",
        ]

        for callback in callbacks:
            self.assertLessEqual(len(callback.encode("utf-8")), 64, callback)

    def test_records_pagination_clamps_pages(self) -> None:
        records = [_haplogroup_record(index) for index in range(21)]

        first, first_page, total_pages = _paginate_records(records, 0)
        middle, middle_page, _ = _paginate_records(records, 1)
        last, last_page, _ = _paginate_records(records, 99)

        self.assertEqual(len(first), 8)
        self.assertEqual(first_page, 0)
        self.assertEqual(total_pages, 3)
        self.assertEqual(len(middle), 8)
        self.assertEqual(middle_page, 1)
        self.assertEqual(len(last), 5)
        self.assertEqual(last_page, 2)


class _LargeDocument:
    file_name = "huge-haplogroups.csv"
    file_size = HAPLOGROUP_RESULT_UPLOAD_LIMIT_BYTES + 1

    def __init__(self) -> None:
        self.get_file_called = False

    async def get_file(self):
        self.get_file_called = True
        return SimpleNamespace(download_to_drive=lambda custom_path: None)


class _DocumentMessage:
    def __init__(self, document: _LargeDocument) -> None:
        self.document = document
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs):
        self.replies.append(text)
        return SimpleNamespace(message_id=10)


class _MenuMessage:
    def __init__(self) -> None:
        self.text = ""
        self.reply_markup = None

    async def reply_text(self, text: str, **kwargs):
        self.text = text
        self.reply_markup = kwargs.get("reply_markup")
        return SimpleNamespace(message_id=10)


class _StatusMessage:
    message_id = 11

    def __init__(self) -> None:
        self.text = ""
        self.reply_markup = None
        self.photos: list[tuple[bytes, str]] = []
        self.replies: list[str] = []

    async def edit_text(self, text: str, **kwargs) -> None:
        self.text = text
        self.reply_markup = kwargs.get("reply_markup")

    async def reply_photo(self, photo, caption: str = "", **kwargs):
        self.photos.append((photo.read(), caption))
        return SimpleNamespace(message_id=12)

    async def reply_text(self, text: str, **kwargs):
        self.replies.append(text)
        return SimpleNamespace(message_id=12)


class _TextMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.status = _StatusMessage()

    async def reply_text(self, text: str, **kwargs):
        return self.status


class _YFullServiceStub:
    def lookup(self, query: str) -> YFullLookupResult:
        branch = YFullBranch(
            name="R-Y100",
            parent="R1b",
            path=("R", "R1b", "R-Y100"),
            snps=("Y100",),
            formed_ybp=4500,
            tmrca_ybp=3700,
            formed_ci_ybp=(3100, 6000),
            tmrca_ci_ybp=(2400, 5500),
            children=(
                YFullChildBranch(
                    name="R-Z200",
                    snps=("Z200",),
                    formed_ybp=3700,
                    tmrca_ybp=1600,
                    formed_ci_ybp=(2400, 5500),
                    tmrca_ci_ybp=(950, 2300),
                    public_sample_count=2,
                ),
            ),
            public_sample_count=2,
            geographies=(YFullGeography(label="Spain", count=2),),
            tree_version="14.03.00",
            release_date="16 May 2026",
            source_url="https://www.yfull.com/tree/R-Y100/",
            fetched_at="2026-06-18T00:00:00+00:00",
        )
        return YFullLookupResult(branch=branch, cache_status="live")


class _MTreeServiceStub:
    def lookup(self, query: str) -> YFullLookupResult:
        result = _YFullServiceStub().lookup(query)
        child = replace(result.branch.children[0], name="H1a1a", snps=("T16189C",))
        branch = replace(
            result.branch,
            name="H1a1",
            parent="H1",
            path=("H", "H1", "H1a1"),
            snps=("A73G", "C146T"),
            children=(child,),
            source_url="https://www.yfull.com/mtree/H1a1/",
        )
        return replace(result, branch=branch)


class _MyDataStub:
    def __init__(self) -> None:
        self.build_temp_path_called = False

    def get_sample(self, user_id: int, sample_id: str) -> SampleAsset | None:
        return SampleAsset(sample_id, "Sample One", "raw-1", [], "2026-06-16T00:00:00")

    def build_temp_path(self, user_id: int, file_name: str) -> Path:
        self.build_temp_path_called = True
        return Path(file_name)


class HaplogroupDocumentHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_branch_visual_is_sent_as_png_and_temp_file_is_removed(self) -> None:
        with TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "branch.png"
            context = SimpleNamespace(application=SimpleNamespace(bot_data={}))
            message = _StatusMessage()

            with patch("app.features.haplogroups.menu._yfull_branch_service", return_value=_YFullServiceStub()), patch(
                "app.features.haplogroups.menu._create_branch_visual_path",
                return_value=image_path,
            ):
                rendered = await _send_branch_visual(
                    message,
                    context,
                    branch_name="R-Y100",
                    user_id=123,
                    lang="ru",
                )

            self.assertTrue(rendered)
            self.assertEqual(len(message.photos), 1)
            self.assertTrue(message.photos[0][0].startswith(b"\x89PNG\r\n\x1a\n"))
            self.assertIn("R-Y100", message.photos[0][1])
            self.assertFalse(image_path.exists())

    async def test_stale_branch_flow_does_not_capture_plain_text(self) -> None:
        flow = HaplogroupFlowStore()
        flow.expect(10, 123, {}, action=_BRANCH_LOOKUP_ACTION)
        context = SimpleNamespace(application=SimpleNamespace(bot_data={"haplogroup_flow_store": flow}))
        message = _TextMessage("Smith")
        update = SimpleNamespace(
            message=message,
            effective_chat=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=123),
        )

        await haplogroups_text_input_handler(update, context)

        self.assertIsNone(flow.get(10, 123))
        self.assertEqual(message.status.text, "")

    async def test_matching_pending_takes_priority_over_haplogroup_flow(self) -> None:
        flow = HaplogroupFlowStore()
        flow.expect(10, 123, {}, action=_BRANCH_LOOKUP_ACTION)
        matching_flow = SimpleNamespace(get_pending=lambda chat_id, user_id: {"action": "snp_input"})
        context = SimpleNamespace(application=SimpleNamespace(bot_data={
            "haplogroup_flow_store": flow,
            "matching_flow_store": matching_flow,
        }))
        message = _TextMessage("rs2455144")
        update = SimpleNamespace(
            message=message,
            effective_chat=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=123),
        )

        await haplogroups_text_input_handler(update, context)

        self.assertIsNotNone(flow.get(10, 123))
        self.assertEqual(message.status.text, "")

    async def test_branch_lookup_text_flow_renders_result_and_clears_pending(self) -> None:
        flow = HaplogroupFlowStore()
        flow.expect(10, 123, {}, action=_BRANCH_LOOKUP_ACTION)
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"haplogroup_flow_store": flow})
        )
        message = _TextMessage("R-Y100")
        update = SimpleNamespace(
            message=message,
            effective_chat=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=123),
        )

        with patch("app.features.haplogroups.menu._yfull_branch_service", return_value=_YFullServiceStub()):
            with self.assertRaises(ApplicationHandlerStop):
                await haplogroups_text_input_handler(update, context)

        self.assertIsNone(flow.get(10, 123))
        self.assertIn("R-Y100", message.status.text)
        self.assertIn("Общий предок: ≈ 3 700 лет назад", message.status.text)
        nav_buttons = [
            button
            for row in message.status.reply_markup.inline_keyboard
            for button in row
            if button.callback_data and ":bn:" in button.callback_data
        ]
        self.assertEqual([button.text for button in nav_buttons], ["↑ R1b", "↓ R-Z200 · 2"])
        self.assertTrue(all(len(button.callback_data.encode("utf-8")) <= 64 for button in nav_buttons))
        visual_buttons = [
            button
            for row in message.status.reply_markup.inline_keyboard
            for button in row
            if button.callback_data and ":bv:" in button.callback_data
        ]
        self.assertEqual(len(visual_buttons), 1)
        self.assertIn("Карточка", visual_buttons[0].text)
        url_buttons = [
            button
            for row in message.status.reply_markup.inline_keyboard
            for button in row
            if button.url
        ]
        self.assertEqual(url_buttons[0].url, "https://www.yfull.com/tree/R-Y100/")

    async def test_mtdna_branch_lookup_uses_mtree_service_and_copy(self) -> None:
        flow = HaplogroupFlowStore()
        flow.expect(10, 123, {"tree_type": "mt"}, action=_BRANCH_LOOKUP_ACTION)
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"haplogroup_flow_store": flow})
        )
        message = _TextMessage("H1a1")
        update = SimpleNamespace(
            message=message,
            effective_chat=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=123),
        )

        with patch("app.features.haplogroups.menu._yfull_mtree_service", return_value=_MTreeServiceStub()):
            with self.assertRaises(ApplicationHandlerStop):
                await haplogroups_text_input_handler(update, context)

        self.assertIsNone(flow.get(10, 123))
        self.assertIn("YFull MTree", message.status.text)
        self.assertIn("Мутации:", message.status.text)
        callbacks = [
            button.callback_data
            for row in message.status.reply_markup.inline_keyboard
            for button in row
            if button.callback_data
        ]
        self.assertTrue(any(callback.startswith(f"{HAPLOGROUPS_CALLBACK_PREFIX}:bn:mt:") for callback in callbacks))
        self.assertTrue(any(callback.startswith(f"{HAPLOGROUPS_CALLBACK_PREFIX}:bv:mt:") for callback in callbacks))

    async def test_branch_lookup_prompt_sets_expected_text_flow(self) -> None:
        flow = HaplogroupFlowStore()
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"haplogroup_flow_store": flow})
        )
        message = _MenuMessage()

        await show_branch_lookup_prompt(message, context, 123, 10, lang="ru")

        self.assertEqual(flow.get(10, 123)["action"], _BRANCH_LOOKUP_ACTION)

    async def test_mtdna_branch_lookup_prompt_sets_mtree_flow(self) -> None:
        flow = HaplogroupFlowStore()
        context = SimpleNamespace(
            application=SimpleNamespace(bot_data={"haplogroup_flow_store": flow})
        )
        message = _MenuMessage()

        await show_branch_lookup_prompt(message, context, 123, 10, tree_type="mt", lang="ru")

        self.assertEqual(flow.get(10, 123)["tree_type"], "mt")
        self.assertIn("mtDNA", message.text)
        self.assertIn("/mtree/", message.text)

    async def test_root_menu_does_not_show_saved_by_sample_section(self) -> None:
        message = _MenuMessage()

        await show_haplogroups_menu(message, SimpleNamespace(), 123, lang="ru")

        callbacks = [
            button.callback_data
            for row in message.reply_markup.inline_keyboard
            for button in row
        ]
        self.assertEqual(
            callbacks,
            [
                f"{HAPLOGROUPS_CALLBACK_PREFIX}:branch:y",
                f"{HAPLOGROUPS_CALLBACK_PREFIX}:branch:mt",
                f"{HAPLOGROUPS_CALLBACK_PREFIX}:y",
                f"{HAPLOGROUPS_CALLBACK_PREFIX}:mt",
                f"{HAPLOGROUPS_CALLBACK_PREFIX}:str",
                "main:root",
                f"{HAPLOGROUPS_CALLBACK_PREFIX}:cancel",
            ],
        )
        labels = [
            button.text
            for row in message.reply_markup.inline_keyboard
            for button in row
        ]
        self.assertIn("🌳 YFull YTree · Y-DNA", labels)
        self.assertIn("🌳 YFull MTree · mtDNA", labels)

    async def test_document_upload_rejects_oversized_file_before_download(self) -> None:
        flow = HaplogroupFlowStore()
        flow.expect(10, 123, {"sample_id": "sample-1"}, action=_FILE_UPLOAD_ACTION)
        my_data_store = _MyDataStub()
        context = SimpleNamespace(
            application=SimpleNamespace(
                bot_data={
                    "haplogroup_flow_store": flow,
                    "my_data_store": my_data_store,
                }
            )
        )
        document = _LargeDocument()
        message = _DocumentMessage(document)
        update = SimpleNamespace(
            message=message,
            effective_chat=SimpleNamespace(id=10),
            effective_user=SimpleNamespace(id=123),
        )

        with self.assertRaises(ApplicationHandlerStop):
            await haplogroups_document_input_handler(update, context)

        self.assertFalse(document.get_file_called)
        self.assertFalse(my_data_store.build_temp_path_called)
        self.assertIn("слишком большой", message.replies[0])


if __name__ == "__main__":
    unittest.main()
