from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Any, List, Dict

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    fqname TEXT NOT NULL,
    file TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT NOT NULL,
    docstring TEXT,
    summary TEXT,

    summary_hash TEXT,
    code_truncated INTEGER DEFAULT 0,
    summary_prompt_tokens INTEGER,
    summary_coverage TEXT,
    summary_backend TEXT CHECK (summary_backend IN ('ollam', 'codex') OR summary_backend IS NULL),
    summary_error TEXT,

    code_hash TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(kind, fqname)
);

CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY,
    src TEXT NOT NULL,
    rel TEXT NOT NULL,
    dst TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts
USING fts5(
    fqname,
    signature,
    docstring,
    summary,
    content='entities',
    content_rowid='id'
);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    conn = _connect(db_path)
    with conn:
        conn.executescript(SCHEMA)
        _ensure_schema_columns(conn)


def _ensure_schema_columns(conn: sqlite3.Connection) -> None:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(entities)").fetchall()}
    if "summary_backend" not in cols:
        conn.execute(
            "ALTER TABLE entities ADD COLUMN summary_backend TEXT CHECK (summary_backend IN ('ollam', 'codex') OR summary_backend IS NULL)"
        )


def ingest_index(db_path: Path, idx: dict[str, Any]) -> None:
    conn = _connect(db_path)
    with conn:
        # Relations: simplest is replace-all each run
        conn.execute("DELETE FROM relations")
        conn.executemany(
            "INSERT INTO relations (src, rel, dst) VALUES (?, ?, ?)",
            [(r["src"], r["rel"], r["dst"]) for r in idx["relations"]]
        )

        for e in idx["entities"]:
            # upsert entity
            conn.execute("""
            INSERT INTO entities(kind, fqname, file, start_line, end_line, signature, docstring, summary, code_hash)
            VALUES(?, ?, ?, ?, ?, ?, ?, COALESCE(?, ''), ?)
            ON CONFLICT(kind, fqname) DO UPDATE SET
                file=excluded.file,
                start_line=excluded.start_line,
                end_line=excluded.end_line,
                signature=excluded.signature,
                docstring=excluded.docstring,
                code_hash=excluded.code_hash,
                updated_at=datetime('now')
            """,                 
            (e["kind"], e["fqname"], e["file"], e["start_line"], e["end_line"],
                 e.get("signature",""), e.get("docstring",""), e.get("summary",""), e["code_hash"])
            )

        # rebuild fts (simple approach for MVP)
        conn.execute("INSERT INTO entities_fts(entities_fts) VALUES('rebuild')")

def get_entities_needing_summary(db_path: Path, kinds=None, limit: int = 200):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    kinds = kinds or ["module", "class", "function", "method"]

    q = f"""
    SELECT
        id, kind, fqname, file, start_line, end_line,
        signature, docstring,
        code_hash,
        summary, summary_hash, summary_error
    FROM entities
    WHERE (summary IS NULL OR summary = '')
      AND kind IN ({",".join(["?"] * len(kinds))})
    ORDER BY kind, fqname
    LIMIT ?
    """
    rows = con.execute(q, (*kinds, limit)).fetchall()
    return [dict(r) for r in rows]


def write_summary(db_path: Path, entity_id: int, summary: str) -> None:
    con = sqlite3.connect(str(db_path))
    with con:
        con.execute(
            "UPDATE entities SET summary=?, updated_at=datetime('now') WHERE id=?",
            (summary, entity_id),
        )
