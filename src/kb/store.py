"""
Hybrid KB store: SQLite for structured records + ChromaDB for semantic search.

Write path: upsert the structured row, then upsert the embedding under the same
id. Both sides always stay consistent — if the embedding insert fails, the
caller sees the exception and can retry the whole record.

Read path: SQL for exact lookups / joins / trace traversal; Chroma for "find
similar requirements / test cases / clauses". The validation engine uses both:
SQL to enumerate "all requirements at ASIL-D level", Chroma to retrieve
relevant standards clauses for grounding.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Optional

from src.config import settings
from src.kb.models import (
    Defect,
    Requirement,
    StandardsClause,
    TestCase,
    TraceLink,
)

# Lazy imports — chroma + sentence-transformers are heavy, so we only load them
# when a collection is actually touched. Keeps `--help` fast.


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS requirements (
    id TEXT PRIMARY KEY,
    level TEXT NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    asil TEXT NOT NULL,
    parent_id TEXT,
    source TEXT,
    tags_json TEXT
);

CREATE TABLE IF NOT EXISTS test_cases (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    level TEXT NOT NULL,
    objective TEXT NOT NULL,
    preconditions TEXT,
    steps TEXT NOT NULL,
    expected_result TEXT NOT NULL,
    verifies_req_ids_json TEXT,
    asil_coverage_hint TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS defects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    severity TEXT,
    against_req_ids_json TEXT,
    against_test_ids_json TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS trace_links (
    parent_id TEXT NOT NULL,
    child_id TEXT NOT NULL,
    link_type TEXT NOT NULL,
    PRIMARY KEY (parent_id, child_id, link_type)
);

CREATE TABLE IF NOT EXISTS standards_clauses (
    id TEXT PRIMARY KEY,
    standard TEXT NOT NULL,
    part TEXT,
    clause TEXT,
    title TEXT,
    text TEXT NOT NULL,
    applicable_asil_json TEXT
);

CREATE INDEX IF NOT EXISTS ix_req_level ON requirements(level);
CREATE INDEX IF NOT EXISTS ix_req_asil ON requirements(asil);
CREATE INDEX IF NOT EXISTS ix_tc_level ON test_cases(level);
CREATE INDEX IF NOT EXISTS ix_def_status ON defects(status);
"""


class KBStore:
    def __init__(self, kb_dir: Optional[Path] = None) -> None:
        self.kb_dir = kb_dir or settings.kb_dir
        self.kb_dir.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()
        self._chroma = None
        self._embedder = None

    # ----------------------------- SQLite ---------------------------------

    def _init_sqlite(self) -> None:
        with self._sql() as con:
            con.executescript(SCHEMA_SQL)

    @contextmanager
    def _sql(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(settings.sqlite_path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ----------------------------- Chroma ---------------------------------

    def _chroma_client(self):
        if self._chroma is None:
            import chromadb

            self._chroma = chromadb.PersistentClient(path=str(settings.chroma_path))
        return self._chroma

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embedder is None:
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer(settings.embedding_model)
        return self._embedder.encode(texts, convert_to_numpy=False, show_progress_bar=False)

    def _collection(self, name: str):
        return self._chroma_client().get_or_create_collection(name)

    # ----------------------------- Upserts --------------------------------

    def upsert_requirements(self, reqs: Iterable[Requirement]) -> int:
        reqs = list(reqs)
        if not reqs:
            return 0
        with self._sql() as con:
            con.executemany(
                """INSERT INTO requirements
                   (id, level, title, text, asil, parent_id, source, tags_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     level=excluded.level, title=excluded.title, text=excluded.text,
                     asil=excluded.asil, parent_id=excluded.parent_id,
                     source=excluded.source, tags_json=excluded.tags_json""",
                [
                    (r.id, r.level.value, r.title, r.text, r.asil.value,
                     r.parent_id, r.source, json.dumps(r.tags))
                    for r in reqs
                ],
            )
        self._index_chroma(
            "requirements",
            ids=[r.id for r in reqs],
            docs=[f"{r.title}\n\n{r.text}" for r in reqs],
            metadatas=[{"level": r.level.value, "asil": r.asil.value} for r in reqs],
        )
        return len(reqs)

    def upsert_test_cases(self, tcs: Iterable[TestCase]) -> int:
        tcs = list(tcs)
        if not tcs:
            return 0
        with self._sql() as con:
            con.executemany(
                """INSERT INTO test_cases
                   (id, title, level, objective, preconditions, steps, expected_result,
                    verifies_req_ids_json, asil_coverage_hint, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     title=excluded.title, level=excluded.level, objective=excluded.objective,
                     preconditions=excluded.preconditions, steps=excluded.steps,
                     expected_result=excluded.expected_result,
                     verifies_req_ids_json=excluded.verifies_req_ids_json,
                     asil_coverage_hint=excluded.asil_coverage_hint, source=excluded.source""",
                [
                    (t.id, t.title, t.level.value, t.objective, t.preconditions,
                     t.steps, t.expected_result, json.dumps(t.verifies_req_ids),
                     t.asil_coverage_hint, t.source)
                    for t in tcs
                ],
            )
            # Trace links: each verifies_req_id implies a (req -> tc, "verifies") edge.
            con.executemany(
                """INSERT OR IGNORE INTO trace_links (parent_id, child_id, link_type)
                   VALUES (?, ?, 'verifies')""",
                [(req_id, t.id) for t in tcs for req_id in t.verifies_req_ids],
            )
        self._index_chroma(
            "test_cases",
            ids=[t.id for t in tcs],
            docs=[f"{t.title}\n{t.objective}\n\nSteps:\n{t.steps}\n\nExpected: {t.expected_result}"
                  for t in tcs],
            metadatas=[{"level": t.level.value} for t in tcs],
        )
        return len(tcs)

    def upsert_defects(self, defects: Iterable[Defect]) -> int:
        defects = list(defects)
        if not defects:
            return 0
        with self._sql() as con:
            con.executemany(
                """INSERT INTO defects
                   (id, title, description, status, severity,
                    against_req_ids_json, against_test_ids_json, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     title=excluded.title, description=excluded.description,
                     status=excluded.status, severity=excluded.severity,
                     against_req_ids_json=excluded.against_req_ids_json,
                     against_test_ids_json=excluded.against_test_ids_json,
                     source=excluded.source""",
                [
                    (d.id, d.title, d.description, d.status.value, d.severity,
                     json.dumps(d.against_req_ids), json.dumps(d.against_test_ids),
                     d.source)
                    for d in defects
                ],
            )
        self._index_chroma(
            "defects",
            ids=[d.id for d in defects],
            docs=[f"{d.title}\n\n{d.description}" for d in defects],
            metadatas=[{"status": d.status.value} for d in defects],
        )
        return len(defects)

    def upsert_trace_links(self, links: Iterable[TraceLink]) -> int:
        links = list(links)
        if not links:
            return 0
        with self._sql() as con:
            con.executemany(
                """INSERT OR IGNORE INTO trace_links (parent_id, child_id, link_type)
                   VALUES (?, ?, ?)""",
                [(l.parent_id, l.child_id, l.link_type) for l in links],
            )
        return len(links)

    def upsert_standards_clauses(self, clauses: Iterable[StandardsClause]) -> int:
        clauses = list(clauses)
        if not clauses:
            return 0
        with self._sql() as con:
            con.executemany(
                """INSERT INTO standards_clauses
                   (id, standard, part, clause, title, text, applicable_asil_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     standard=excluded.standard, part=excluded.part, clause=excluded.clause,
                     title=excluded.title, text=excluded.text,
                     applicable_asil_json=excluded.applicable_asil_json""",
                [
                    (c.id, c.standard, c.part, c.clause, c.title, c.text,
                     json.dumps([a.value for a in c.applicable_asil]))
                    for c in clauses
                ],
            )
        self._index_chroma(
            "standards_clauses",
            ids=[c.id for c in clauses],
            docs=[f"{c.title}\n\n{c.text}" for c in clauses],
            metadatas=[{"standard": c.standard, "part": c.part} for c in clauses],
        )
        return len(clauses)

    def _index_chroma(
        self,
        collection_name: str,
        *,
        ids: list[str],
        docs: list[str],
        metadatas: list[dict],
    ) -> None:
        if not ids:
            return
        coll = self._collection(collection_name)
        embeddings = [list(vec) for vec in self._embed(docs)]
        coll.upsert(ids=ids, documents=docs, metadatas=metadatas, embeddings=embeddings)

    # ------------------------------ Reads ---------------------------------

    def stats(self) -> dict[str, int]:
        with self._sql() as con:
            return {
                "requirements": con.execute("SELECT COUNT(*) FROM requirements").fetchone()[0],
                "test_cases": con.execute("SELECT COUNT(*) FROM test_cases").fetchone()[0],
                "defects": con.execute("SELECT COUNT(*) FROM defects").fetchone()[0],
                "trace_links": con.execute("SELECT COUNT(*) FROM trace_links").fetchone()[0],
                "standards_clauses": con.execute("SELECT COUNT(*) FROM standards_clauses").fetchone()[0],
            }

    def list_requirements(self, level: Optional[str] = None) -> list[dict]:
        with self._sql() as con:
            if level:
                rows = con.execute(
                    "SELECT * FROM requirements WHERE level = ? ORDER BY id",
                    (level,),
                ).fetchall()
            else:
                rows = con.execute("SELECT * FROM requirements ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def find_similar_requirements(self, query: str, k: int = 5) -> list[dict]:
        coll = self._collection("requirements")
        emb = list(self._embed([query])[0])
        res = coll.query(query_embeddings=[emb], n_results=k)
        # Flatten Chroma's nested-list response (single query → first row).
        return [
            {"id": rid, "document": doc, "metadata": meta, "distance": dist}
            for rid, doc, meta, dist in zip(
                res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
            )
        ]

    def find_relevant_clauses(self, query: str, k: int = 5) -> list[dict]:
        coll = self._collection("standards_clauses")
        emb = list(self._embed([query])[0])
        res = coll.query(query_embeddings=[emb], n_results=k)
        return [
            {"id": rid, "text": doc, "metadata": meta, "distance": dist}
            for rid, doc, meta, dist in zip(
                res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
            )
        ]
