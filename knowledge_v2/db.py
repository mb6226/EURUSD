import sqlite3
from .config import load_config, project_path

def connect():
    cfg = load_config()
    db_path = project_path(cfg["database"])
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_path TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            source_url TEXT,
            source_type TEXT,
            ingested_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            content_hash TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            embedding TEXT,
            UNIQUE(document_id, chunk_index)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            text, content='chunks', content_rowid='id'
        );
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.id, old.text);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.id, old.text);
            INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
        END;
        """)
    return True
