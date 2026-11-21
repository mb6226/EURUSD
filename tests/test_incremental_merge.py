import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from merge_incremental_data import merge_files

def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w=csv.writer(f); w.writerow(["timestamp","open","high","low","close","volume"]); w.writerows(rows)

def read_rows(path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def test_incremental_merge_sorts_and_deduplicates_with_new_data_winning(tmp_path):
    base=tmp_path/"base.csv"; inc=tmp_path/"inc.csv"
    write_csv(base, [[1000,1.0,1.2,0.9,1.1,10],[2000,1.1,1.3,1.0,1.2,11]])
    write_csv(inc, [[2000,1.2,1.4,1.1,1.3,12],[3000,1.3,1.5,1.2,1.4,13]])
    result=merge_files(base,inc); rows=read_rows(base)
    assert result["rows"]==3
    assert [int(x["timestamp"]) for x in rows]==[1000,2000,3000]
    assert float(rows[1]["close"])==1.3 and float(rows[1]["volume"])==12

def test_incremental_merge_rejects_invalid_ohlc(tmp_path):
    base=tmp_path/"base.csv"; inc=tmp_path/"inc.csv"
    write_csv(base, [[1000,1.0,1.2,0.9,1.1,10]])
    write_csv(inc, [[2000,1.0,0.8,0.9,1.1,10]])
    try:
        merge_files(base,inc)
    except ValueError as exc:
        assert "Invalid OHLCV" in str(exc)
    else:
        raise AssertionError("Invalid OHLCV row was accepted")
