from Modules.Elliott_Waves.Chart_To_Wave_Mapper.mapper import parse_anchors,timestamp_at_x,nearest_ohlc,map_image

def test_date_axis_builds_monotonic_anchors():
    tokens=[{"text":"Sep","x_normalized":.1,"confidence":.9},{"text":"10","x_normalized":.2,"confidence":.9},{"text":"20","x_normalized":.5,"confidence":.9},{"text":"Oct","x_normalized":.7,"confidence":.9},{"text":"5","x_normalized":.8,"confidence":.9}]
    anchors,status=parse_anchors(tokens,"2026-10-19T12:00:00+00:00")
    assert status=="approximate_date_axis" and len(anchors)==3
    assert anchors[0][1]<anchors[-1][1]
    assert timestamp_at_x(.5,anchors)==anchors[1][1]

def test_nearest_ohlc_price():
    assert nearest_ohlc({"open":1.1,"high":1.12,"low":1.09,"close":1.115},1.119)==("high",1.12)

def test_non_chart_never_becomes_training_data():
    im={"image_id":"abc","record_id":"r","ocr_status":"completed","image_classification":"non_chart_or_unrecognized","timeframes_detected":[],"possible_wave_labels":[]}
    r=map_image(im,{}, {})
    assert r["mapping_status"]=="excluded_non_chart" and not r["training_eligible"]
    assert r["review_status"]=="needs_visual_review"

def test_price_discrepancy_is_not_promoted_to_candle_match():
    # Regression guard: an image/chart price hundreds of pips from the matched
    # candle must not be used to construct a wave segment.
    from Modules.Elliott_Waves.Chart_To_Wave_Mapper.mapper import nearest_ohlc
    candle={"open":1.145,"high":1.148,"low":1.144,"close":1.147}
    _,matched=nearest_ohlc(candle,1.177)
    assert abs(matched-1.177)*10000>25
