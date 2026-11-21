from Modules.Elliott_Waves.Research_Collector.collector import Parser
from Modules.Elliott_Waves.Research_Collector.image_extractor import _host_allowed, PRICE_RE, WAVE_RE


def test_parser_collects_open_graph_chart_image_and_img_src():
    html = """
    <html><head><meta property="og:image" content="/charts/eurusd.png"></head>
    <body><img src="/assets/chart.webp"><a href="/x">EURUSD Elliott Wave</a></body></html>
    """
    parsed = Parser()
    parsed.feed(html)
    assert parsed.meta["og:image"] == "/charts/eurusd.png"
    assert parsed.images == ["/assets/chart.webp"]


def test_image_host_allowlist_is_strict():
    assert _host_allowed("https://cdn.example.com/chart.png", ["example.com"])
    assert not _host_allowed("https://example.com.attacker.test/chart.png", ["example.com"])
    assert not _host_allowed("file:///chart.png", ["example.com"])


def test_ocr_token_patterns_are_conservative():
    assert WAVE_RE.fullmatch("(iii)".strip("()"))
    assert not WAVE_RE.fullmatch("triangle")
    assert PRICE_RE.search("target 1.12345")
    assert not PRICE_RE.search("1.12")
    assert not PRICE_RE.search("0.618")


from Modules.Elliott_Waves.Research_Collector.image_extractor import _wave_token, _axis_calibration


def test_wave_token_normalizes_common_elliott_labels():
    assert _wave_token("(iii)") == "iii"
    assert _wave_token("Wave 4") == "4"
    assert _wave_token("Wave (B)") == "B"
    assert _wave_token("(B)") == "B"
    assert _wave_token("triangle") is None


def test_axis_calibration_uses_right_axis_price_ticks():
    detections = [
        {"text": "1.17000", "center_normalized": [0.95, 0.10]},
        {"text": "1.16000", "center_normalized": [0.95, 0.30]},
        {"text": "1.15000", "center_normalized": [0.95, 0.50]},
    ]
    result = _axis_calibration(detections)
    assert result["status"] == "approximate_linear"
    fit = result["price_from_y"]
    assert round(fit["intercept"] + fit["slope"] * 0.30, 5) == 1.16
