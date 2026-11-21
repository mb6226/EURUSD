from Modules.Elliott_Waves.Research_Collector.collector import Parser, clean_url, candidate, extract


def test_parser_reads_metadata_and_links():
    html = """
    <html><head>
      <meta property="og:title" content="EURUSD Elliott Wave Analysis">
      <meta property="og:description" content="Wave 3 is bearish on H4">
    </head><body><a href="/analysis/eurusd-wave-count">EURUSD wave count</a></body></html>
    """
    parsed = Parser()
    parsed.feed(html)
    assert parsed.meta["og:title"] == "EURUSD Elliott Wave Analysis"
    assert parsed.links == [("/analysis/eurusd-wave-count", "EURUSD wave count")]


def test_clean_url_removes_tracking_and_fragment():
    assert clean_url("https://Example.com/a/?utm_source=x#chart") == "https://example.com/a"


def test_candidate_requires_pair_and_elliott_wave_context():
    assert candidate("https://fxstreet.com/analysis/eurusd-wave", "EURUSD Elliott Wave", "fxstreet.com")
    assert not candidate("https://fxstreet.com/analysis/eurusd-news", "EURUSD news", "fxstreet.com")


def test_extract_marks_hints_not_labels():
    result = extract("EURUSD Elliott Wave bearish H4", "Wave (iii) may target 1.1050")
    assert result["bias_mentioned"] == "bearish"
    assert "H4" in result["timeframes_mentioned"]
    assert "1.1050" in result["eurusd_price_levels_mentioned"]
    assert "human verification" in result["extraction_note"]
