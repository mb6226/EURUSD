import json
import math
import re

from .db import connect, init_db
from .config import load_config
from .ollama_client import embed


def tokenize_query(q):
    terms = re.findall(r"[A-Za-z0-9_]+|[\u0600-\u06FF]+", q)
    return " OR ".join(
        '"' + t.replace('"', '""') + '"'
        for t in terms[:20]
    )


def cosine(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0

    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))

    return dot / (na * nb) if na and nb else 0.0


def source_key(row):
    return row.get("source_path") or row.get("title") or "unknown"


def retrieve(query, top_k=None):
    init_db()
    cfg = load_config()

    top_k = top_k or cfg["top_k"]
    candidate_k = max(top_k * 10, 50)

    lexical = {}
    semantic = {}

    match = tokenize_query(query)

    with connect() as c:

        # 1. Lexical search: collect a wider candidate pool.
        if match:
            try:
                rows = c.execute("""
                    SELECT ch.id, ch.text, d.title,
                           d.source_path, d.source_url,
                           bm25(chunks_fts) AS rank
                    FROM chunks_fts
                    JOIN chunks ch ON ch.id = chunks_fts.rowid
                    JOIN documents d ON d.id = ch.document_id
                    WHERE chunks_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """, (match, candidate_k)).fetchall()

                for row in rows:
                    lexical[row["id"]] = dict(row)

            except Exception:
                pass

        # 2. Semantic search.
        try:
            qv = embed(query) if cfg["use_embeddings"] else None
        except Exception:
            qv = None

        if qv:
            rows = c.execute("""
                SELECT ch.id, ch.text, ch.embedding,
                       d.title, d.source_path, d.source_url
                FROM chunks ch
                JOIN documents d ON d.id = ch.document_id
                WHERE ch.embedding IS NOT NULL
            """).fetchall()

            for row in rows:
                try:
                    score = cosine(
                        qv,
                        json.loads(row["embedding"])
                    )
                    semantic[row["id"]] = (score, dict(row))
                except Exception:
                    continue

    # 3. Combine lexical and semantic scores.
    ids = set(lexical) | set(semantic)

    lexical_scores = {
        cid: 1.0 / (1 + index)
        for index, cid in enumerate(lexical)
    }

    results = []

    for cid in ids:
        lex_score = lexical_scores.get(cid, 0.0)

        sem_score, sem_row = semantic.get(
            cid, (0.0, None)
        )

        row = lexical.get(cid) or sem_row

        if row is None:
            continue

        row["score"] = (
            0.45 * lex_score +
            0.55 * sem_score
        )

        row["chunk_id"] = cid
        results.append(row)

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    # 4. Source-aware diversification.
    # If multiple documents have relevant candidates,
    # avoid letting one document dominate the results.
    distinct_sources = {
        source_key(row) for row in results
    }

    if len(distinct_sources) > 1:
        source_limit = max(1, math.ceil(top_k / 2))
        best_score = results[0]["score"] if results else 0.0

        selected = []
        source_counts = {}

        for row in results:
            source = source_key(row)
            count = source_counts.get(source, 0)

            # Only apply the source limit to candidates
            # reasonably close to the best score.
            sufficiently_relevant = (
                row["score"] >= best_score * 0.65
            )

            if (
                sufficiently_relevant
                and count >= source_limit
            ):
                continue

            selected.append(row)
            source_counts[source] = count + 1

            if len(selected) >= top_k:
                break

        results = selected

    return results[:top_k]
