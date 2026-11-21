import json
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'Modules'/'Elliott_Waves'/'Dataset'/'generated'
files=['causal_swings.jsonl','weak_structure_labels.jsonl','multitimeframe_asof_events.jsonl']
counts={}
for name in files:
    path=root/name
    n=0
    with path.open(encoding='utf-8') as f:
        for line in f:
            row=json.loads(line)
            n+=1
            if name=='multitimeframe_asof_events.jsonl':
                cutoff=row['event_time']
                assert all(v['available_at'] <= cutoff for v in row['asof_swing_context'].values()), 'future context leak'
            if name=='weak_structure_labels.jsonl':
                assert row['available_at']
                assert row['label_source']=='elliott_rule_engine_weak_label'
    counts[name]=n
manifest=json.loads((root/'dataset_manifest.json').read_text(encoding='utf-8'))
assert counts['causal_swings.jsonl']==manifest['totals']['swings']
assert counts['weak_structure_labels.jsonl']==manifest['totals']['structure_candidates']
assert counts['multitimeframe_asof_events.jsonl']==manifest['totals']['multitimeframe_events']
print('JSONL_COUNTS',json.dumps(counts))
print('FILE_SIZES',{n:(root/n).stat().st_size for n in files})
print('MANIFEST_TOTALS',json.dumps(manifest['totals']))
print('ASOF_LEAKAGE_CHECK=PASS')
