import argparse, json
from pathlib import Path
from .db import init_db, connect
from .config import load_config, project_path
from .ingest import ingest_folder, ingest_file
from .answer import ask
from .ollama_client import list_models

def main():
    p = argparse.ArgumentParser(description="EURUSD AI Knowledge Base / RAG")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    f = sub.add_parser("ingest-folder"); f.add_argument("folder", nargs="?")
    one = sub.add_parser("ingest-file"); one.add_argument("file")
    q = sub.add_parser("ask"); q.add_argument("question")
    sub.add_parser("status")
    sub.add_parser("models")
    args = p.parse_args()

    if args.cmd == "init":
        init_db()
        cfg = load_config()
        project_path(cfg["library_dir"]).mkdir(parents=True, exist_ok=True)
        print("Knowledge DB initialized.")
    elif args.cmd == "ingest-folder":
        print(json.dumps(ingest_folder(args.folder), ensure_ascii=False, indent=2))
    elif args.cmd == "ingest-file":
        print(json.dumps(ingest_file(args.file), ensure_ascii=False, indent=2))
    elif args.cmd == "ask":
        result = ask(args.question)
        print("\nANSWER\n", result["answer"])
        print("\nSOURCES")
        print(json.dumps(result["sources"], ensure_ascii=False, indent=2))
    elif args.cmd == "status":
        init_db()
        with connect() as c:
            docs = c.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            chunks = c.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
            vectors = c.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]
        print(json.dumps({"documents": docs, "chunks": chunks, "embedded_chunks": vectors}, indent=2))
    elif args.cmd == "models":
        print(json.dumps(list_models(), ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
