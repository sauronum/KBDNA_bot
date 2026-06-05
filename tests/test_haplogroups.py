from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from app.features.haplogroups.domain import (
    DEFAULT_Y_SNP_REFERENCE_PATH,
    compare_y_str_profiles,
    load_y_snp_reference,
    parse_haplogroup_result_file,
    parse_y_str_result_file,
    predict_y_haplogroup_from_raw,
    scan_raw_haplogroup_markers,
)
from app.features.haplogroups.menu import HAPLOGROUPS_CALLBACK_PREFIX, parse_haplogroup_input
from app.features.haplogroups.storage import HaplogroupStore
from app.features.haplogroups.ui import raw_scan_result_text
from app.features.my_data.storage import SampleAsset


def _write_raw(path: Path, rows: list[tuple[str, str, int, str]]) -> None:
    body = ["rsid\tchromosome\tposition\tgenotype"]
    body.extend(f"{rsid}\t{chromosome}\t{position}\t{genotype}" for rsid, chromosome, position, genotype in rows)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")


class HaplogroupTests(unittest.TestCase):
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
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:list:y",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:list:mt",
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
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:hsample:{asset_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:o:{record_id}",
            f"{HAPLOGROUPS_CALLBACK_PREFIX}:ho:{record_id}",
        ]

        for callback in callbacks:
            self.assertLessEqual(len(callback.encode("utf-8")), 64, callback)


if __name__ == "__main__":
    unittest.main()
