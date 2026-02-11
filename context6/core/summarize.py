from __future__ import annotations
from pathlib import Path
import time
import sqlite3
from context6.core.ollama_summarizer import summarize_entity
from context6.core.summarize_router import summarize_entity_routed
from context6.db.sqlite import _connect, get_entities_needing_summary
from context6.core.retrieve import get_snippet



def write_summary_cur(
    con: sqlite3.Connection,
    entity_id: int,
    summary: str,
    code_hash: str,
    was_truncated: bool,
    approx_tokens: int,
    coverage: str,
    summary_backend: str,
) -> None:
    """
    Write a summary for a code entity to the database.
    
    :param con: SQLite connection object
    :type con: sqlite3.Connection
    :param entity_id: ID of the entity being summarized
    :type entity_id: int
    :param summary: The generated summary for the code entity
    :type summary: str
    :param code_hash: Hash of the code entity, used for change detection
    :type code_hash: str
    :param was_truncated: Whether the code was truncated during summarization
    :type was_truncated: bool
    :param approx_tokens: Approximate number of tokens used in the summary
    :type approx_tokens: int
    :param coverage: Coverage level of the summary (e.g., "full", "partial", "unclear")
    :type coverage: str
    :param summary_backend: The backend used for summarization (e.g., "ollama", "codex")
    :type summary_backend: str
    """

    if summary_backend not in ("ollama", "codex"):
        raise ValueError(f"Invalid summary_backend: {summary_backend}")

    cur = con.execute(
        """
        UPDATE entities
        SET summary=?,
            summary_hash=?,
            code_truncated=?,
            summary_prompt_tokens=?,
            summary_coverage=?,
            summary_backend=?,
            summary_error=NULL,
            updated_at=datetime('now')
        WHERE id=?
        """,
        (summary, code_hash, int(was_truncated), int(approx_tokens), coverage, summary_backend, entity_id),
    )
    if cur.rowcount != 1:
        raise RuntimeError(f"UPDATE rowcount={cur.rowcount} for id={entity_id}")


def write_summary_error_cur(con: sqlite3.Connection, entity_id: int, err: str) -> None:
    con.execute(
        "UPDATE entities SET summary_error=?, updated_at=datetime('now') WHERE id=?",
        (err[:500], entity_id),
    )


def run_summarize(db: Path, limit: int = 200, summarizer: str = "auto", codex_bin: str = "codex") -> int:
    """
    This is the main entry point for summarization. It finds entities that need summaries, generates them, and writes back to the DB.
    
    :param db: Path to the SQLite database file
    :type db: Path
    :param limit: Maximum number of entities to summarize in one run
    :type limit: int
    :param summarizer: Summarization mode ("auto", "ollama", "codex")
    :type summarizer: str
    :param codex_bin: Path to the Codex binary
    :type codex_bin: str
    :return: Number of entities summarized
    :rtype: int
    """
    todo = get_entities_needing_summary(db, kinds=["module", "class", "function", "method"], limit=limit)
    total = len(todo)
    if total == 0:
        print("Nothing to summarize.")
        return 0

    con = sqlite3.connect(str(db))
    try:
        # Good practice for concurrent readers (e.g., you inspecting with sqlite3)
        con.execute("PRAGMA journal_mode=WAL;")

        n = 0
        t0 = time.time()

        for i, e in enumerate(todo, start=1):
            fq = e["fqname"]
            kind = e["kind"]
            print(f"[{i}/{total}] {kind:7s} {fq}", flush=True)

            snip = get_snippet(db, fq)
            if "text" not in snip:
                print(f"  -> skipped (no snippet): {snip.get('error','unknown')}", flush=True)
                continue

            t_ent0 = time.time()
            try:
                result = summarize_entity_routed(
                    kind=kind,
                    fqname=fq,
                    signature=e.get("signature") or "",
                    docstring=e.get("docstring") or "",
                    code=snip["text"],
                    mode=summarizer,
                    codex_bin=codex_bin,
                )

                summary = result["summary"]
                if not summary.strip():
                    raise RuntimeError("Empty summary from Ollama")

                write_summary_cur(
                    con,
                    e["id"],
                    summary,
                    code_hash=e["code_hash"],
                    was_truncated=result["was_truncated"],
                    approx_tokens=result["approx_tokens"],
                    coverage=result["coverage"],
                    summary_backend=result["backend"],
                )

            except Exception as ex:
                write_summary_error_cur(con, e["id"], str(ex))
                print(f"  -> ERROR: {ex}", flush=True)

            finally:
                con.commit()

            n += 1

            dt = time.time() - t_ent0
            elapsed = time.time() - t0
            avg = elapsed / max(1, n)
            remain = (total - i) * avg
            print(f"  -> done in {dt:.1f}s | avg {avg:.1f}s/item | ~{remain/60:.1f} min left", flush=True)

        print(f"Summarized {n}/{total} entities in {(time.time()-t0)/60:.1f} min")
        return n

    except KeyboardInterrupt:
        con.commit()
        print("\nInterrupted; progress saved.", flush=True)
        return n

    finally:
        con.close()


def summarize_one(db: Path, entity_id: int, fqname: str, kind: str, signature: str, docstring: str, summarizer: str = "auto", codex_bin: str = "codex") -> str:
    snip = get_snippet(db, fqname)
    if "text" not in snip:
        raise RuntimeError(f"Cannot summarize {fqname}: no snippet ({snip.get('error','unknown')})")

    result = summarize_entity_routed(
        kind=kind,
        fqname=fqname,
        signature=signature or "",
        docstring=docstring or "",
        code=snip["text"],
        mode=summarizer,
        codex_bin=codex_bin,
    )
    summary = result["summary"]
    if not summary.strip():
        raise RuntimeError(f"Ollama returned empty summary for {fqname}")

    # get code_hash from DB (source of truth)
    con = _connect(db)
    try:
        row = con.execute("SELECT code_hash FROM entities WHERE id=?", (entity_id,)).fetchone()
        if not row:
            raise RuntimeError(f"Entity id not found: {entity_id}")
        code_hash = row["code_hash"]

        write_summary_cur(
            con,
            entity_id,
            summary,
            code_hash=code_hash,
            was_truncated=result["was_truncated"],
            approx_tokens=result["approx_tokens"],
            coverage=result["coverage"],
            summary_backend=result["backend"],
        )
        con.commit()

        row2 = con.execute(
            "SELECT length(summary) AS n, summary_coverage, summary_prompt_tokens FROM entities WHERE id=?",
            (entity_id,),
        ).fetchone()
        print(
            f"DB verify: summary_len={row2['n']} coverage={row2['summary_coverage']} tokens={row2['summary_prompt_tokens']}",
            flush=True,
        )

    finally:
        con.close()

    return summary
