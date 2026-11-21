from pathlib import Path
p=Path(r"C:\Users\mahdi\Downloads\EURUSD-AI\scripts\elliott_chart_lab.py")
s=p.read_text(encoding="utf-8")
a=s.index("def get_payload(tf,bars):")
b=s.index("\nclass Handler",a)
new='''def get_payload(tf,bars):
    candles,start,total=load_candles(tf,bars)
    # Re-detect on the visible window so the chart always has pivots and hypotheses
    # for the exact bars being displayed, even when a saved Stage 1 snapshot is older.
    from src.eurusd_ai.market_data import Candle
    from Modules.Elliott_Waves.Detection.detector import detect_pivots
    from Modules.Elliott_Waves.Detection.engine import ElliottEngine
    thresholds={"M5":8.0,"M15":15.0,"H1":25.0,"H4":40.0,"D1":60.0}
    bars_as_candles=[Candle(x["time"],x["open"],x["high"],x["low"],x["close"],x["volume"]) for x in candles]
    pivots=detect_pivots(bars_as_candles,thresholds[tf],0.0001)
    candidates=[x.to_dict() for x in ElliottEngine(0.0001,25.0).analyze_pivots(pivots)]
    return {"timeframe":tf,"start_index":0,"source_start_index":start,"candles":candles,
            "pivots":[x.__dict__ for x in pivots],"candidates":candidates[:150]}
'''
p.write_text(s[:a]+new+s[b:],encoding="utf-8")
print("patched",p)
