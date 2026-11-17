import unittest

from source_registry.adapters import FetchParseError, FetchRequest
from source_registry.adapters.fed import FedAdapter
from source_registry.adapters.fed_html import parse_fed_target_range_html


SYNTHETIC_FED_HTML = """
<!doctype html>
<html>
  <body>
    <table id="fomc-target-range-history">
      <thead>
        <tr>
          <th>Effective Date</th>
          <th>Lower Bound (%)</th>
          <th>Upper Bound (%)</th>
        </tr>
      </thead>
      <tbody>
        <tr><td>2024-12-19</td><td>4.25%</td><td>4.50%</td></tr>
        <tr><td>2024-11-08</td><td>4.50%</td><td>4.75%</td></tr>
      </tbody>
    </table>
  </body>
</html>
"""


class FedHtmlParserTests(unittest.TestCase):
    def test_extracts_records_usable_by_fed_adapter(self):
        records = parse_fed_target_range_html(SYNTHETIC_FED_HTML)
        result = FedAdapter(lambda request: records).fetch(
            FetchRequest("FED_FOMC_POLICY", "FED_TARGET_RANGE")
        )

        self.assertEqual(
            records,
            [
                {
                    "effective_date": "2024-12-19",
                    "lower_bound": "4.25",
                    "upper_bound": "4.50",
                },
                {
                    "effective_date": "2024-11-08",
                    "lower_bound": "4.50",
                    "upper_bound": "4.75",
                },
            ],
        )
        self.assertEqual(
            [
                observation.effective_at_utc.date().isoformat()
                for observation in result.observations
            ],
            ["2024-11-08", "2024-12-19"],
        )

    def test_rejects_missing_target_table(self):
        with self.assertRaisesRegex(FetchParseError, "table id"):
            parse_fed_target_range_html("<html><body>No table</body></html>")

    def test_rejects_missing_required_column(self):
        html = """
        <table id="fomc-target-range-history">
          <tr><th>Effective Date</th><th>Lower Bound</th></tr>
        </table>
        """
        with self.assertRaisesRegex(FetchParseError, "upper bound"):
            parse_fed_target_range_html(html)

    def test_rejects_rows_that_do_not_match_header_structure(self):
        html = """
        <table id="fomc-target-range-history">
          <tr>
            <th>Effective Date</th><th>Lower Bound</th><th>Upper Bound</th>
          </tr>
          <tr><td>2024-12-19</td><td>4.25</td></tr>
        </table>
        """
        with self.assertRaisesRegex(FetchParseError, "row 2"):
            parse_fed_target_range_html(html)

    def test_rejects_empty_required_values(self):
        html = """
        <table id="fomc-target-range-history">
          <tr>
            <th>Effective Date</th><th>Lower Bound</th><th>Upper Bound</th>
          </tr>
          <tr><td>2024-12-19</td><td></td><td>4.50</td></tr>
        </table>
        """
        with self.assertRaisesRegex(FetchParseError, "empty required value"):
            parse_fed_target_range_html(html)

    def test_rejects_multiple_matching_tables(self):
        table = """
        <table id="fomc-target-range-history">
          <tr>
            <th>Effective Date</th><th>Lower Bound</th><th>Upper Bound</th>
          </tr>
        </table>
        """
        with self.assertRaisesRegex(FetchParseError, "exactly one"):
            parse_fed_target_range_html(table + table)


if __name__ == "__main__":
    unittest.main()
