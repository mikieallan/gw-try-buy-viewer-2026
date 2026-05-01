import unittest

from scripts.parse_try_buy_eml import WineRecord, confidence_from_score, parse_vivino_page, score_candidate


SAMPLE_VIVINO_HTML = """
<html>
  <head>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Trail Estate Supersonic",
      "aggregateRating": {"ratingValue": "3.9", "ratingCount": "128"}
    }
    </script>
  </head>
</html>
"""


class VivinoMatchingTests(unittest.TestCase):
    def test_parse_vivino_jsonld(self) -> None:
        rating, count, title = parse_vivino_page(SAMPLE_VIVINO_HTML)
        self.assertEqual(rating, 3.9)
        self.assertEqual(count, 128)
        self.assertEqual(title, "Trail Estate Supersonic")

    def test_score_candidate_producer_and_cuvee_overlap(self) -> None:
        record = WineRecord(
            category="Canadian Cuties",
            raw_wine_line="Trail Estate, Supersonic Concord, Prince Edward County, Ontario",
            grape_witches_url="https://grapewitches.com/products/trail-estate-super-sonic",
            normalized_name="Trail Estate Supersonic",
            producer="Trail Estate",
            cuvee="Supersonic Concord",
        )
        score, reason = score_candidate(record, "Trail Estate Supersonic Red")
        self.assertGreater(score, 0.5)
        self.assertIn("producer_overlap", reason)

    def test_confidence_thresholds(self) -> None:
        self.assertEqual(confidence_from_score(0.9), "high")
        self.assertEqual(confidence_from_score(0.6), "medium")
        self.assertEqual(confidence_from_score(0.2), "low")


if __name__ == "__main__":
    unittest.main()
