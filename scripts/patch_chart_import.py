from pathlib import Path
p=Path(r"C:\Users\mahdi\Downloads\EURUSD-AI\scripts\elliott_chart_lab.py")
s=p.read_text(encoding="utf-8").replace("from src.eurusd_ai.market_data import Candle","from eurusd_ai.market_data import Candle")
p.write_text(s,encoding="utf-8")
print("fixed package import")
