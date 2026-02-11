from __future__ import annotations

from pathlib import Path
from typing import Any
import sqlite3
import re

def _connect(db: Path) -> sqlite3.Connection:
    """
    Establish a connection to the SQLite database.
    
    :param db: Path to the SQLite database file
    :type db: Path
    :return: SQLite connection object
    :rtype: sqlite3.Connection
    """

    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    return con


def _extract_init_header(snippet_text: str) -> str:
    """
    Try to find the __init__ def line (and decorator lines just above it).
    Returns a short block (<= ~10 lines).
    
    :param snippet_text: The text of the code snippet to search
    :type snippet_text: str
    :return: The extracted __init__ header block, or an empty string if not found
    :rtype: str
    """
    lines = snippet_text.splitlines()
    for i, line in enumerate(lines):
        if re.match(r"^\s*def\s+__init__\s*\(", line):
            # include up to 3 decorator lines above
            start = i
            j = i - 1
            while j >= 0 and lines[j].lstrip().startswith("@") and (i - j) <= 3:
                start = j
                j -= 1
            end = min(len(lines), i + 8)
            return "\n".join(lines[start:end]).rstrip()
    return ""

def _small_snippet_for_entity(arc_root: Path, e: dict[str, Any], max_lines: int = 40) -> str:
    """
    For classes: docstring + __init__ header if we can find it.
    Otherwise: first max_lines of the entity block.
    """
    file_path = arc_root / e["file"]
    lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, int(e["start_line"]))
    end = min(len(lines), int(e["end_line"]))
    block = lines[start - 1 : end]

    if e["kind"] == "class":
        # Pull docstring from DB (already extracted reliably)
        doc = (e.get("docstring") or "").strip()
        doc_first = doc.splitlines()[:20]  # keep docstring small
        doc_text = "\n".join(doc_first).rstrip()

        # Find __init__ header inside the class block (cheap heuristic)
        block_text = "\n".join(block[:800])  # don’t scan thousands of lines
        init_hdr = _extract_init_header(block_text)

        parts = []
        if doc_text:
            parts.append('"""' + ("\n" + doc_text if "\n" in doc_text else doc_text) + '"""')
        if init_hdr:
            parts.append(init_hdr)
        if parts:
            return "\n\n".join(parts).rstrip()

    # Fallback: first max_lines of the entity
    return "\n".join(block[:max_lines]).rstrip()

def pretty_lookup(db: Path, name: str, arc_root: Path) -> str:
    """
    Pretty-print a lookup result for a given symbol name.
    
    :param db: Path to the SQLite database file
    :type db: Path
    :param name: The symbol name to look up (can be fqname, tail,
                or substring)
    :type name: str
    :param arc_root: Path to the root of the source code (for snippet retrieval)
    :type arc_root: Path
    :return: A formatted string containing the lookup result, including header, summary, and snippet
    :rtype: str
    """

    con = _connect(db)

    # Pick best match: exact fqname > tail match > substring
    rows = con.execute(
        """
        SELECT * FROM entities
        WHERE fqname = ?
        UNION
        SELECT * FROM entities
        WHERE fqname LIKE ?
        UNION
        SELECT * FROM entities
        WHERE fqname LIKE ?
        LIMIT 10
        """,
        (name, f"%.{name}", f"%{name}%"),
    ).fetchall()

    if not rows:
        return f"No matches for: {name}"

    # choose first row as best (we can rank later if needed)
    e = dict(rows[0])

    header = f"{e['fqname']}  ({e['kind']})\n{e['file']}:{e['start_line']}-{e['end_line']}\n{(e.get('signature') or '').strip()}"
    summary = (e.get("summary") or "").strip()
    snippet = _small_snippet_for_entity(arc_root, e)

    out = [header]

    if summary:
        out.append("\nSummary:\n" + summary)
    else:
        out.append("\nSummary:\n<empty> (run `context6 summarize` to populate)")

    if snippet:
        out.append("\nSnippet:\n" + snippet)

    return "\n".join(out).rstrip()


def pretty_lookup_entity(db: Path, arc_root: Path, e: dict[str, Any]) -> str:
    """
    Pretty-print a lookup result for a given entity row.
    
    :param db: Path to the SQLite database file
    :type db: Path
    :param arc_root: Path to the root of the source code (for snippet retrieval)
    :type arc_root: Path
    :param e: The entity row to pretty-print, as a dictionary
    :type e: dict[str, Any]
    :return: A formatted string containing the lookup result for the given entity, including header, summary, and snippet
    :rtype: str
    """

    header = f"{e['fqname']}  ({e['kind']})\n{e['file']}:{e['start_line']}-{e['end_line']}\n{(e.get('signature') or '').strip()}"
    summary = (e.get("summary") or "").strip()
    snippet = _small_snippet_for_entity(arc_root, e)

    out = [header]
    out.append("\nSummary:\n" + (summary if summary else "<empty> (run `context6 summarize` to populate)"))
    out.append("\nSnippet:\n" + (snippet if snippet else ""))
    return "\n".join([x for x in out if x]).rstrip()


def best_match_entity(
    db: Path,
    name: str,
    kinds: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any] | None:
    """
    Look up an entity by name, trying to find the best match. Matches can be:
    - Exact fqname match
    - Tail match (e.g., "Class.method")
    - Substring match
    
    :param db: Path to the SQLite database file
    :type db: Path
    :param name: A string representing the symbol name to look up. This can be a fully qualified name (e.g., "package.module.Class.method"), a tail name (e.g., "Class.method"), or a substring (e.g., "method").
    :type name: str
    :param kinds: Optional list or tuple of kinds to filter by
    :type kinds: list[str] | tuple[str, ...] | None
    :return: The best-matching entity row as a dictionary, or None if no match is found
    :rtype: dict[str, Any] | None
    """

    con = _connect(db)
    kind_clause = ""
    kind_params: tuple[Any, ...] = ()
    if kinds:
        norm = [k.strip() for k in kinds if k and k.strip()]
        if norm:
            placeholders = ",".join(["?"] * len(norm))
            kind_clause = f" AND kind IN ({placeholders})"
            kind_params = tuple(norm)

    rows = con.execute(
        f"""
        SELECT e.*
        FROM entities e
        JOIN (
            SELECT id, MIN(rank) AS best_rank
            FROM (
                SELECT id, 0 AS rank FROM entities WHERE fqname = ?{kind_clause}
                UNION ALL
                SELECT id, 1 AS rank FROM entities WHERE fqname LIKE ?{kind_clause}
                UNION ALL
                SELECT id, 2 AS rank FROM entities WHERE fqname LIKE ?{kind_clause}
            )
            GROUP BY id
        ) r ON r.id = e.id
        ORDER BY
            r.best_rank,
            CASE e.kind
                WHEN 'class' THEN 0
                WHEN 'module' THEN 1
                WHEN 'function' THEN 2
                WHEN 'method' THEN 3
                ELSE 9
            END,
            e.fqname
        LIMIT 1
        """,
        (
            name,
            *kind_params,
            f"%.{name}",
            *kind_params,
            f"%{name}%",
            *kind_params,
        ),
    ).fetchall()
    return dict(rows[0]) if rows else None
