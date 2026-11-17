from pathlib import Path
from hashlib import sha256
import re
from pypdf import PdfReader
from bs4 import BeautifulSoup
from .config import load_config, project_path
from .db import connect, init_db
from .ollama_client import embed

SUPPORTED = {".pdf", ".txt", ".md", ".html", ".htm"}

def extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    raw = path.read_text(encoding="utf-8", errors="ignore")
    if suffix in {".html", ".htm"}:
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "nav", "footer"]):
            tag.decompose()
        return soup.get_text("\n", strip=True)
    return raw

def clean_text(text):
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def split_chunks(text, size, overlap):
    text = clean_text(text)
    if not text:
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            boundary = text.rfind("\n", start, end)
            if boundary > start + size // 2:
                end = boundary
        part = text[start:end].strip()
        if part:
            chunks.append(part)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks

def ingest_file(path, source_url=None, make_embeddings=True):
    init_db()
    path = Path(path).resolve()
    if path.name == "PUT_DOCUMENTS_HERE.txt":
        return {"status": "skipped", "reason": "placeholder file", "path": str(path)}
    if path.suffix.lower() not in SUPPORTED:
        return {"status": "skipped", "reason": "unsupported extension", "path": str(path)}
    text = clean_text(extract_text(path))
    if len(text) < 40:
        return {"status": "skipped", "reason": "no extractable text (possibly scanned PDF)", "path": str(path)}
    digest = sha256(text.encode("utf-8")).hexdigest()
    cfg = load_config()
    parts = split_chunks(text, cfg["chunk_chars"], cfg["chunk_overlap"])
    with connect() as c:
        old = c.execute("SELECT id, content_hash FROM documents WHERE source_path=?", (str(path),)).fetchone()
        if old and old["content_hash"] == digest:
            return {"status": "unchanged", "path": str(path), "chunks": c.execute(
                "SELECT COUNT(*) FROM chunks WHERE document_id=?", (old["id"],)).fetchone()[0]}
        if old:
            c.execute("DELETE FROM chunks WHERE document_id=?", (old["id"],))
            c.execute("UPDATE documents SET title=?, source_url=?, source_type=?, content_hash=?, ingested_at=CURRENT_TIMESTAMP WHERE id=?",
                      (path.stem, source_url, path.suffix.lower(), digest, old["id"]))
            doc_id = old["id"]
        else:
            cur = c.execute("INSERT INTO documents(source_path,title,source_url,source_type,content_hash) VALUES(?,?,?,?,?)",
                            (str(path), path.stem, source_url, path.suffix.lower(), digest))
            doc_id = cur.lastrowid
        for i, chunk in enumerate(parts):
            vector = None
            if make_embeddings and cfg["use_embeddings"]:
                try:
                    vector = embed(chunk)
                except Exception:
                    vector = None
            import json
            c.execute("INSERT INTO chunks(document_id,chunk_index,text,embedding) VALUES(?,?,?,?)",
                      (doc_id, i, chunk, json.dumps(vector) if vector else None))
    return {"status": "ingested", "path": str(path), "chunks": len(parts), "characters": len(text)}

def ingest_folder(folder=None):
    cfg = load_config()
    folder = Path(folder) if folder else project_path(cfg["library_dir"])
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.suffix.lower() in SUPPORTED:
            try:
                results.append(ingest_file(p))
            except Exception as e:
                results.append({"status": "error", "path": str(p), "error": str(e)})
    return results
