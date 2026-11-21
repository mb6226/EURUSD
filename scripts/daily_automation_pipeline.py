from __future__ import annotations
import argparse, json, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PY=sys.executable
def run(label,args):
    started=time.time(); print(f"\n=== {label} ===",flush=True)
    p=subprocess.run(args,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    print(p.stdout[-16000:],flush=True)
    if p.returncode: raise RuntimeError(f"{label} failed with exit code {p.returncode}")
    print(f"{label} OK ({time.time()-started:.1f}s)",flush=True)
def main():
    p=argparse.ArgumentParser(); p.add_argument("--incremental",type=Path,required=True); a=p.parse_args()
    inc=a.incremental.resolve()
    base=ROOT/"data/eurusd-m1-bid-2021-11-20-2026-11-20.csv"
    started=datetime.now(timezone.utc).isoformat()
    run("Merge + validate M1",[PY,"scripts/merge_incremental_data.py","--base",str(base),"--incremental",str(inc)])
    run("Resample M5/M15/H1/H4/D1",[PY,"scripts/resample_timeframes.py"])
    run("Rebuild causal Elliott dataset (Stage 2)",[PY,"scripts/build_elliott_learning_dataset.py"])
    # Keep the generated dataset manifest's date range aligned with the rolling M1 source.
    import csv
    with base.open("r",encoding="utf-8-sig",newline="") as handle:
        reader=csv.DictReader(handle)
        first=next(reader)
        last=first
        for last in reader: pass
    manifest_path=ROOT/"Modules/Elliott_Waves/Dataset/generated/dataset_manifest.json"
    manifest=json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["date_range_utc"]=[datetime.fromtimestamp(int(first["timestamp"])/1000,tz=timezone.utc).date().isoformat(),
                                datetime.fromtimestamp(int(last["timestamp"])/1000,tz=timezone.utc).date().isoformat()]
    manifest["generated_at_utc"]=datetime.now(timezone.utc).isoformat()
    manifest_path.write_text(json.dumps(manifest,indent=2),encoding="utf-8")
    run("Refresh multi-timeframe reasoning (Stage 4)",[PY,"scripts/run_multitimeframe_reasoning.py"])
    run("Generate daily Elliott forecast (Stage 7)",[PY,"scripts/daily_elliott_forecaster.py"])
    report=ROOT/"Modules/Elliott_Waves/Evaluation/stage7/daily_elliott_forecast.json"
    data=json.loads(report.read_text(encoding="utf-8"))
    summary={"started_at_utc":started,"finished_at_utc":datetime.now(timezone.utc).isoformat(),"decision":data.get("decision"),
             "as_of":data.get("market_data",{}).get("as_of"),"next_session":data.get("forecast_for_next_ny_weekday_session"),"abstain_reasons":data.get("abstain_reasons"),"forecast_file":str(report)}
    out=ROOT/"Modules/Elliott_Waves/Evaluation/automation"; out.mkdir(parents=True,exist_ok=True)
    (out/"latest_pipeline_run.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print("\nPIPELINE_SUMMARY="+json.dumps(summary),flush=True)
if __name__=="__main__": main()
