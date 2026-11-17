from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = {
    "ollama_url": "http://localhost:11434",
    "chat_model": "qwen2.5vl:7b",
    "embedding_model": "nomic-embed-text",
    "database": "data/knowledge/knowledge.db",
    "library_dir": "knowledge/library",
    "chunk_chars": 1400,
    "chunk_overlap": 220,
    "top_k": 6,
    "use_embeddings": True,
    "temperature": 0.1,
}

def load_config():
    path = ROOT / "knowledge_v2" / "config.json"
    if not path.exists():
        path.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    data = json.loads(path.read_text(encoding="utf-8"))
    return {**DEFAULT_CONFIG, **data}

def project_path(value):
    p = Path(value)
    return p if p.is_absolute() else ROOT / p
