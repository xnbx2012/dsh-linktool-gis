import os
import sys
import json
import sqlite3
import struct

import httpx
import sqlite_vec
from mcp.server.fastmcp import FastMCP

# ── Config ─────────────────────────────────────────────────────────────────────
SILICONFLOW_API_KEY = os.environ.get(
    "SILICONFLOW_API_KEY"
)
SILICONFLOW_BASE_URL = "https://api.siliconflow.cn"
EMBEDDING_MODEL = "Qwen/Qwen3-Embedding-4B"
RERANKER_MODEL = "Qwen/Qwen3-Reranker-8B"
VECTOR_DIM = 512

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.sqlite")

mcp = FastMCP("KnowledgeDB MCP Server")


# ── DB Init ────────────────────────────────────────────────────────────────────
def get_db() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def init_vec_table(db: sqlite3.Connection) -> None:
    db.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
            chunk_id INTEGER PRIMARY KEY,
            embedding float[{VECTOR_DIM}]
        )
    """)
    count = db.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0]
    if count == 0:
        print("Populating vec_chunks from chunks table...", file=sys.stderr)
        rows = db.execute("SELECT id, embedding FROM chunks").fetchall()
        for row_id, emb_blob in rows:
            db.execute(
                "INSERT INTO vec_chunks(chunk_id, embedding) VALUES (?, ?)",
                [row_id, emb_blob],
            )
        db.commit()
        print(f"Indexed {len(rows)} chunks into vec_chunks.", file=sys.stderr)


# ── SiliconFlow API ────────────────────────────────────────────────────────────
def get_embedding(text: str) -> bytes:
    resp = httpx.post(
        f"{SILICONFLOW_BASE_URL}/v1/embeddings",
        headers={"Authorization": f"Bearer {SILICONFLOW_API_KEY}"},
        json={"model": EMBEDDING_MODEL, "input": text, "dimensions": VECTOR_DIM},
        timeout=30,
    )
    resp.raise_for_status()
    floats = resp.json()["data"][0]["embedding"]
    return struct.pack(f"{VECTOR_DIM}f", *floats)


def rerank(query: str, documents: list[str], top_n: int) -> list[dict]:
    resp = httpx.post(
        f"{SILICONFLOW_BASE_URL}/v1/rerank",
        headers={"Authorization": f"Bearer {SILICONFLOW_API_KEY}"},
        json={
            "model": RERANKER_MODEL,
            "query": query,
            "documents": documents,
            "top_n": top_n,
        },
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["results"]


# ── MCP Tool ───────────────────────────────────────────────────────────────────
@mcp.tool()
async def search_knowledge(query: str, top_k: int = 10, use_rerank: bool = True) -> str:
    """在向量数据库中搜索相关文档

    Args:
        query: 搜索关键词或问题
        top_k: 返回结果数量，默认10条
        use_rerank: 是否使用Reranker优化结果，默认True
    """
    db = get_db()
    try:
        init_vec_table(db)
        query_vec = get_embedding(query)

        # KNN vector search — fetch more candidates when reranking
        fetch_k = top_k * 3 if use_rerank else top_k
        vec_results = db.execute(
            """
            SELECT chunk_id, distance
            FROM vec_chunks
            WHERE embedding MATCH ?
            ORDER BY distance
            LIMIT ?
            """,
            [query_vec, fetch_k],
        ).fetchall()

        if not vec_results:
            return json.dumps({"results": [], "total": 0}, ensure_ascii=False)

        ids = [r[0] for r in vec_results]
        dist_map = {r[0]: r[1] for r in vec_results}

        # Fetch chunk metadata
        placeholders = ",".join("?" * len(ids))
        chunks = db.execute(
            f"SELECT id, source_file, h1, h2, content FROM chunks WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
        chunk_map = {c[0]: c for c in chunks}

        # Build ordered result list (preserve KNN order)
        results = []
        for cid in ids:
            if cid not in chunk_map:
                continue
            c = chunk_map[cid]
            results.append(
                {
                    "id": c[0],
                    "source_file": c[1],
                    "h1": c[2],
                    "h2": c[3],
                    "content": c[4],
                    "distance": dist_map[cid],
                }
            )

        if use_rerank and len(results) > 1:
            docs = [r["content"] for r in results]
            rerank_results = rerank(query, docs, top_n=top_k)
            reranked = []
            for item in rerank_results:
                r = results[item["index"]]
                r["rerank_score"] = item["relevance_score"]
                reranked.append(r)
            results = reranked
        else:
            results = results[:top_k]

        return json.dumps({"results": results, "total": len(results)}, ensure_ascii=False)
    finally:
        db.close()


if __name__ == "__main__":
    mcp.run(transport="stdio")
