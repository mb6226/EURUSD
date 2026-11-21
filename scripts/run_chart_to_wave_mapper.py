from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from Modules.Elliott_Waves.Chart_To_Wave_Mapper.mapper import run
if __name__=="__main__":
    import json
    print(json.dumps(run(),ensure_ascii=False,indent=2))
