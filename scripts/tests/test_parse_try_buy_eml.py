import tempfile
import textwrap
import unittest
from pathlib import Path

from scripts.parse_try_buy_eml import (
    extract_gw_badges,
    extract_gw_meta,
    extract_wines_from_tokens,
    parse_eml_plaintext,
    parse_gw_product_title,
    split_wine_section,
)


SAMPLE_EML = textwrap.dedent(
    """\
    From: demo@example.com
    To: demo@example.com
    Subject: Try & Buy FAQ
    MIME-Version: 1.0
    Content-Type: text/plain; charset="UTF-8"
    Content-Transfer-Encoding: quoted-printable

    Intro section
    WINE LIST
    Canadian Cuties
    Revel x GW =E2=80=98Chambarine=E2=80=99 Nectarine, Chambourcin & Apple, Guelph, Ontario
    https://grapewitches.com/products/revel-chambarine
    Salty & Savoury
    Clai =E2=80=98Baracija=E2=80=99 Malvasia, Istria, Croatia
    https://grapewitches.com/products/clai-baracija
    Website https://www.grapewitches.com/
    """
)


class ParseTryBuyEmlTests(unittest.TestCase):
    def test_parse_and_extract_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            eml_path = Path(tmp) / "sample.eml"
            eml_path.write_text(SAMPLE_EML, encoding="utf-8")
            plain = parse_eml_plaintext(eml_path)
            tokens = split_wine_section(plain)
            records = extract_wines_from_tokens(tokens)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].category, "Canadian Cuties")
        self.assertEqual(records[1].category, "Salty & Savoury")
        self.assertEqual(records[0].grape_witches_url, "https://grapewitches.com/products/revel-chambarine")
        self.assertIn("Chambarine", records[0].raw_wine_line)

    def test_handles_smart_quotes_decoding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            eml_path = Path(tmp) / "sample.eml"
            eml_path.write_text(SAMPLE_EML, encoding="utf-8")
            plain = parse_eml_plaintext(eml_path)
        self.assertIn("'Chambarine'", plain)

    def test_extract_gw_thumbnail_from_meta(self) -> None:
        html = """
        <meta property="og:title" content="Revel Chambarine">
        <meta property="og:description" content="Juicy and bright.">
        <meta property="og:image" content="https://cdn.grapewitches.com/image.jpg">
        <meta property="product:price:amount" content="41.00">
        """
        title, description, thumb, price, excerpt = extract_gw_meta(html)
        self.assertEqual(title, "Revel Chambarine")
        self.assertEqual(description, "Juicy and bright.")
        self.assertEqual(thumb, "https://cdn.grapewitches.com/image.jpg")
        self.assertEqual(price, "$41.00")
        self.assertIsNone(excerpt)

    def test_extract_gw_prefers_product_body_over_truncated_og(self) -> None:
        html = """
        <meta property="og:title" content="Khush Raho">
        <meta property="og:description" content="Viognier, Niagara, Ontario A luscious and lovely viognier skin-contact made in collaboration with one of our favourite local fermenters! Winemaker Nupur Gogia is a wine agent, nice pal, Vinequity co-founder and MW from Toronto! #LetsSeeYourCV? 'Khush' is her flourishing low-intervention wine project named after the Hi">
        <div class="product__description rte">
          <p>END of full copy on site with Koh Lipe and porch.</p>
        </div>
        """
        title, description, thumb, price, excerpt = extract_gw_meta(html)
        self.assertEqual(title, "Khush Raho")
        self.assertIn("Koh Lipe", description or "")
        self.assertNotIn("named after the Hi", description or "")
        self.assertIsNone(thumb)
        self.assertEqual(description, excerpt)

    def test_extract_gw_badges_from_bottomline_tags(self) -> None:
        html = """
        <ul class="bottomline-tags">
        <li class="taglist"><img src="https://cdn.example.com/freaky.png">
          <span class="badge-content"><i>Freaky Level 1 </i> <br> Natural wine isn't *always* freaky! </span>
        </li>
        <li class="taglist"><img src="https://cdn.example.com/bangers.png">
          <span class="badge-content"><i> Weekday Bangers </i><br> Tuesday-friendly with incredible value.</span>
        </li>
        </ul>
        """
        badges = extract_gw_badges(html)
        self.assertEqual(len(badges), 2)
        self.assertEqual(badges[0]["image_url"], "https://cdn.example.com/freaky.png")
        self.assertEqual(badges[0]["label"], "Freaky Level 1")
        self.assertIn("freaky", badges[0]["description"].lower())
        self.assertEqual(badges[1]["label"], "Weekday Bangers")
        self.assertIn("Tuesday-friendly", badges[1]["description"])

    def test_extract_gw_prefers_jsonld_product_description(self) -> None:
        html = """
        <meta property="og:title" content="Sample">
        <meta property="og:description" content="Short OG blurb.">
        <script type="application/ld+json">
        {"@context":"http://schema.org","@type":"Product","description":"Much longer structured description from JSON-LD including Koh Lipe and the porch."}
        </script>
        """
        _, description, _, _, excerpt = extract_gw_meta(html)
        self.assertIn("longer structured", description or "")
        self.assertIn("Koh Lipe", description or "")
        self.assertEqual(description, excerpt)

    def test_extract_gw_price_cents_metadata(self) -> None:
        html = """<meta property="product:price:amount" content="2300">"""
        _, _, _, price, _ = extract_gw_meta(html)
        self.assertEqual(price, "$23.00")

    def test_parse_gw_product_title_splits_winery_wine_grape_region(self) -> None:
        title = "Laurent Saillard 'Blank' Sauvignon Blanc Loire"
        parts = parse_gw_product_title(title)
        self.assertEqual(parts["winery"], "Laurent Saillard")
        self.assertEqual(parts["wine"], "Blank")
        self.assertEqual(parts["grapes"], "Sauvignon Blanc")
        self.assertEqual(parts["region"], "Loire")


if __name__ == "__main__":
    unittest.main()
