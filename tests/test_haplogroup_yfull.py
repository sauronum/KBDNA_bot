from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageStat

from app.features.haplogroups.branch_ui import branch_lookup_result_text
from app.features.haplogroups.visualization import render_yfull_branch_png
from app.features.haplogroups.yfull import (
    YFullBranchService,
    YFullLookupError,
    normalize_yfull_branch_query,
    parse_yfull_branch_html,
)


YFULL_BRANCH_HTML = """
<html>
  <head><title>R-Y100 YTree</title></head>
  <body>
    <div id="tbl-header">YFull YTree v14.03.00</div>
    <div id="bc">
      <span><a href="/tree/">Home</a></span>
      <span><a href="/tree/R/">R</a></span>
      <span><a href="/tree/R1b/">R1b</a></span>
    </div>
    <ul id="tree" class="yfullcom-tree">
      <li id="lR-Y100">
        <a class="yf-root">R-Y100</a>
        <span class="yf-snpforhg">Y100 * FT200(H)</span>
        <span title="BY300 * BY301" class="yf-plus-snps">+2 SNPs</span>
        <span title="formed CI 95% 6000&lt;-&gt;3100 ybp, TMRCA CI 95% 5500&lt;-&gt;2400 ybp" class="yf-age">formed 4500 ybp, TMRCA 3700 ybp</span>
        <ul>
          <li id="lR-Y100*">
            <a href="/tree/R-Y100*/">R-Y100*</a>
            <ul>
              <li valSampleID="YF000001"><b title="Spain" class="yf-geo fl ES">ESP</b></li>
            </ul>
          </li>
          <li id="lR-Z200">
            <a href="/tree/R-Z200/">R-Z200</a>
            <span class="yf-snpforhg">Z200</span>
            <span title="formed CI 95% 5500&lt;-&gt;2400 ybp, TMRCA CI 95% 2300&lt;-&gt;950 ybp" class="yf-age">formed 3700 ybp, TMRCA 1600 ybp</span>
            <ul>
              <li id="lR-Z300">
                <a href="/tree/R-Z300/">R-Z300</a>
                <span class="yf-age">formed 1600 ybp, TMRCA 800 ybp</span>
                <ul>
                  <li valSampleID="YF000002"><b title="Georgia" class="yf-geo fl GE">GEO</b></li>
                </ul>
              </li>
            </ul>
          </li>
        </ul>
      </li>
    </ul>
    <p class="note">Haplogroup YTree v14.03.00 (16 May 2026)</p>
  </body>
</html>
"""


class YFullBranchTests(unittest.TestCase):
    def test_branch_visual_renders_dark_and_light_cards(self) -> None:
        with TemporaryDirectory() as temp_dir:
            service = YFullBranchService(Path(temp_dir) / "cache", fetch_html=lambda url: YFULL_BRANCH_HTML)
            result = service.lookup("R-Y100")
            dark_path = Path(temp_dir) / "dark.png"
            light_path = Path(temp_dir) / "light.png"

            render_yfull_branch_png(dark_path, result, lang="ru", theme="dark")
            render_yfull_branch_png(light_path, result, lang="en", theme="light")

            with Image.open(dark_path) as dark, Image.open(light_path) as light:
                self.assertEqual(dark.format, "PNG")
                self.assertEqual(dark.size, (1280, 900))
                self.assertEqual(light.size, (1280, 900))
                self.assertGreater(sum(ImageStat.Stat(dark).stddev), 20)
                self.assertNotEqual(dark.getpixel((10, 10)), light.getpixel((10, 10)))

    def test_normalize_branch_accepts_code_and_public_yfull_url(self) -> None:
        self.assertEqual(normalize_yfull_branch_query("r-y23968"), "R-Y23968")
        self.assertEqual(
            normalize_yfull_branch_query("https://www.yfull.com/tree/R-Y23968/"),
            "R-Y23968",
        )
        self.assertEqual(
            normalize_yfull_branch_query("https://www.yfull.com/live/tree/R-Y23968/"),
            "R-Y23968",
        )

    def test_normalize_branch_rejects_foreign_url_and_path_traversal(self) -> None:
        for value in ("https://example.com/tree/R-Y23968/", "../R-Y23968", "R Y23968", "Smith"):
            with self.subTest(value=value), self.assertRaises(YFullLookupError) as raised:
                normalize_yfull_branch_query(value)
            self.assertEqual(raised.exception.reason, "invalid_query")

    def test_parse_branch_extracts_path_snps_ages_children_and_samples(self) -> None:
        branch = parse_yfull_branch_html(
            YFULL_BRANCH_HTML,
            source_url="https://www.yfull.com/tree/R-Y100/",
        )

        self.assertEqual(branch.name, "R-Y100")
        self.assertEqual(branch.parent, "R1b")
        self.assertEqual(branch.path, ("R", "R1b", "R-Y100"))
        self.assertEqual(branch.snps, ("Y100", "FT200(H)", "BY300", "BY301"))
        self.assertEqual(branch.formed_ybp, 4500)
        self.assertEqual(branch.tmrca_ybp, 3700)
        self.assertEqual(branch.formed_ci_ybp, (3100, 6000))
        self.assertEqual(branch.tmrca_ci_ybp, (2400, 5500))
        self.assertEqual([child.name for child in branch.children], ["R-Y100*", "R-Z200"])
        self.assertEqual(branch.children[1].tmrca_ybp, 1600)
        self.assertEqual(branch.children[1].tmrca_ci_ybp, (950, 2300))
        self.assertEqual(branch.children[0].public_sample_count, 1)
        self.assertEqual(branch.children[1].public_sample_count, 1)
        self.assertNotIn("R-Z300", [child.name for child in branch.children])
        self.assertEqual(branch.public_sample_count, 2)
        self.assertEqual([(item.label, item.count) for item in branch.geographies], [("Georgia", 1), ("Spain", 1)])
        self.assertEqual(branch.tree_version, "14.03.00")
        self.assertEqual(branch.release_date, "16 May 2026")

    def test_service_uses_fresh_cache_and_falls_back_to_stale_cache(self) -> None:
        with TemporaryDirectory() as temp_dir:
            calls = []

            def fetch(url: str) -> str:
                calls.append(url)
                return YFULL_BRANCH_HTML

            service = YFullBranchService(Path(temp_dir), fetch_html=fetch)
            live = service.lookup("R-Y100")
            cached = service.lookup("R-Y100")

            def fail(url: str) -> str:
                raise YFullLookupError("unavailable")

            service.fetch_html = fail
            stale = service.lookup("R-Y100", force_refresh=True)

        self.assertEqual(live.cache_status, "live")
        self.assertEqual(cached.cache_status, "cache")
        self.assertEqual(stale.cache_status, "stale")
        self.assertEqual(len(calls), 1)
        self.assertEqual(cached.branch.children[1].snps, ("Z200",))

    def test_service_rejects_a_page_for_a_different_branch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            service = YFullBranchService(Path(temp_dir), fetch_html=lambda url: YFULL_BRANCH_HTML)

            with self.assertRaises(YFullLookupError) as raised:
                service.lookup("G-Z999")

        self.assertEqual(raised.exception.reason, "parse_error")

    def test_service_accepts_an_alias_listed_on_the_branch(self) -> None:
        with TemporaryDirectory() as temp_dir:
            service = YFullBranchService(Path(temp_dir), fetch_html=lambda url: YFULL_BRANCH_HTML)

            result = service.lookup("FT200")

        self.assertEqual(result.branch.name, "R-Y100")

    def test_result_text_is_compact_and_mentions_stale_cache(self) -> None:
        with TemporaryDirectory() as temp_dir:
            service = YFullBranchService(Path(temp_dir), fetch_html=lambda url: YFULL_BRANCH_HTML)
            result = service.lookup("R-Y100")
            stale_result = type(result)(branch=result.branch, cache_status="stale")

        text = branch_lookup_result_text(stale_result, "ru")

        self.assertIn("R-Y100", text)
        self.assertIn("Общий предок: ≈ 3 700 лет назад (95%: 2 400–5 500)", text)
        self.assertIn("16 мая 2026", text)
        self.assertIn("Грузия — 1, Испания — 1", text)
        self.assertIn("Дочерних ветвей: 1", text)
        self.assertIn("Базальных образцов: 1", text)
        self.assertIn("последняя сохранённая версия", text)
        self.assertLess(len(text), 4096)


if __name__ == "__main__":
    unittest.main()
