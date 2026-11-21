from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from Modules.Elliott_Waves.Research_Collector.collector import collect

if __name__ == "__main__":
    result = collect()
    print(f"Checked: {result['checked']} article pages")
    print(f"New references: {result['added']}")
    print(f"New chart images extracted: {result.get('images_saved', 0)}")
    print(f"Errors: {len(result['errors'])}")
    print(f"JSONL: {result['output']}")
    print(f"Report: {result['report']}")
    for error in result["errors"]:
        print(f"WARNING: {error}")
    runpy.run_path(str(ROOT / "scripts" / "extract_existing_chart_images.py"), run_name="__main__")
    runpy.run_path(str(ROOT / "scripts" / "build_elliott_chart_review.py"), run_name="__main__")
    runpy.run_path(str(ROOT / "scripts" / "run_chart_to_wave_mapper.py"), run_name="__main__")
