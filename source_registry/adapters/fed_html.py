from __future__ import annotations

from html.parser import HTMLParser
import re

from .exceptions import FetchParseError

FED_TARGET_RANGE_TABLE_ID = "fomc-target-range-history"
_REQUIRED_HEADERS = ("effective date", "lower bound", "upper bound")


class _TargetRangeTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.target_table_count = 0
        self.target_table_rows: list[list[tuple[str, str]]] = []
        self.in_target_table = False
        self.current_row: list[tuple[str, str]] | None = None
        self.current_cell_kind: str | None = None
        self.current_cell_text: list[str] = []
        self.error: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            if self.in_target_table:
                self.error = "Nested tables are not supported"
                return
            if any(
                name == "id" and value == FED_TARGET_RANGE_TABLE_ID
                for name, value in attrs
            ):
                self.target_table_count += 1
                self.in_target_table = True
            return

        if not self.in_target_table or self.error is not None:
            return
        if tag == "tr":
            if self.current_row is not None:
                self.error = "Nested table rows are not supported"
                return
            self.current_row = []
        elif tag in ("th", "td") and self.current_row is not None:
            if self.current_cell_kind is not None:
                self.error = "Nested table cells are not supported"
                return
            self.current_cell_kind = tag
            self.current_cell_text = []
        elif tag == "br" and self.current_cell_kind is not None:
            self.current_cell_text.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if not self.in_target_table or self.error is not None:
            return
        if tag in ("th", "td") and self.current_cell_kind is not None:
            if tag != self.current_cell_kind:
                self.error = "Mismatched table cell tags"
                return
            text = re.sub(
                r"\s+",
                " ",
                "".join(self.current_cell_text),
            ).strip()
            if self.current_row is None:
                self.error = "Table cell is outside a row"
                return
            self.current_row.append((tag, text))
            self.current_cell_kind = None
            self.current_cell_text = []
        elif tag == "tr" and self.current_row is not None:
            if self.current_cell_kind is not None:
                self.error = "Unclosed table cell"
                return
            self.target_table_rows.append(self.current_row)
            self.current_row = None
        elif tag == "table":
            if self.current_cell_kind is not None or self.current_row is not None:
                self.error = "Unclosed table row or cell"
                return
            self.in_target_table = False

    def handle_data(self, data: str) -> None:
        if self.in_target_table and self.current_cell_kind is not None:
            self.current_cell_text.append(data)


def _canonical_header(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    if normalized.endswith(" (%)"):
        normalized = normalized[:-4].strip()
    return normalized


def parse_fed_target_range_html(html: str) -> list[dict[str, str]]:
    """Parse the documented synthetic fixture contract, not live Fed HTML."""
    if not isinstance(html, str) or not html.strip():
        raise FetchParseError("Fed HTML must be a non-empty string")

    parser = _TargetRangeTableParser()
    parser.feed(html)
    parser.close()

    if parser.error is not None:
        raise FetchParseError(parser.error)
    if parser.in_target_table:
        raise FetchParseError("Fed target-range table is not closed")
    if parser.target_table_count == 0:
        raise FetchParseError(
            f"Fed target-range table id {FED_TARGET_RANGE_TABLE_ID!r} was not found"
        )
    if parser.target_table_count != 1:
        raise FetchParseError("Fed HTML must contain exactly one target-range table")
    if not parser.target_table_rows:
        raise FetchParseError("Fed target-range table is missing its header row")

    header_row = parser.target_table_rows[0]
    if not header_row or any(kind != "th" for kind, _ in header_row):
        raise FetchParseError("Fed target-range table must begin with a header row")
    headers = [_canonical_header(text) for _, text in header_row]
    if len(set(headers)) != len(headers):
        raise FetchParseError("Fed target-range table contains duplicate headers")
    missing_headers = [header for header in _REQUIRED_HEADERS if header not in headers]
    if missing_headers:
        raise FetchParseError(
            "Fed target-range table is missing required columns: "
            + ", ".join(missing_headers)
        )

    column_indexes = {
        header: headers.index(header) for header in _REQUIRED_HEADERS
    }
    records: list[dict[str, str]] = []
    for row_number, row in enumerate(parser.target_table_rows[1:], start=2):
        if len(row) != len(headers) or any(kind != "td" for kind, _ in row):
            raise FetchParseError(
                f"Fed target-range row {row_number} does not match the header structure"
            )
        values = [text for _, text in row]
        record = {
            "effective_date": values[column_indexes["effective date"]],
            "lower_bound": values[column_indexes["lower bound"]].removesuffix("%").strip(),
            "upper_bound": values[column_indexes["upper bound"]].removesuffix("%").strip(),
        }
        if any(not value for value in record.values()):
            raise FetchParseError(
                f"Fed target-range row {row_number} has an empty required value"
            )
        records.append(record)

    return records
