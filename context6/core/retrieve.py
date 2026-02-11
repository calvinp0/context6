from __future__ import annotations
from contextlib import closing
import sqlite3
from pathlib import Path
from typing import Any, Mapping
import re

_FQNAME_LIKE = re.compile(r"^[A-Za-z0-9_.]+$")
_CODE_LIKE = re.compile(r"(^from\s+[\w.]+\s+import\s+[\w*]+$)|(^import\s+[\w.]+$)")
_IDENT = re.compile(r"[A-Za-z_]\w*")

def _connect(db_path: Path) -> sqlite3.Connection:
    """
    Establish a connection to the SQLite database.
    
    :param db_path: Path to the SQLite database file
    :type db_path: Path
    :return: SQLite connection object
    :rtype: sqlite3.Connection
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _has_table(con: sqlite3.Connection, table: str) -> bool:
    """
    Check if a specific table exists in the SQLite database.
    
    :param con: Database connection object
    :type con: sqlite3.Connection
    :param table: Desired table name to check for existence
    :type table: str
    :return: True if the table exists, False otherwise
    :rtype: bool
    """

    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _ensure_initialized(con: sqlite3.Connection, db_path: Path) -> None:
    """
    Ensure that the database is initialized with the required tables.
    
    :param con: Database connection object
    :type con: sqlite3.Connection
    :param db_path: Path to the SQLite database file
    :type db_path: Path
    :raises RuntimeError: If the required tables are missing
    """
    if _has_table(con, "entities") and _has_table(con, "entities_fts"):
        return
    raise RuntimeError(
        "Database does not look like a context6 index (missing tables). "
        f"Got: {db_path}. If you ran `context6 index ... --out <dir>`, the DB is `<dir>/context6.db`."
    )


def _normalize_kinds(kinds: list[str] | tuple[str, ...] | None) -> list[str] | None:
    """
    Normalize the kinds filter by stripping whitespace and removing empty entries.

    :param kinds: List or tuple of kind strings, or None
    :type kinds: list[str] | tuple[str, ...] | None
    :return: Normalized list of kinds, or None if input is None or empty after
                normalization
    :rtype: list[str] | None
    """
    if kinds is None:
        return None
    out = [k.strip() for k in kinds if k and k.strip()]
    return out or None


def _fqname_boost(fqname: str, query: str) -> int:
    """
    Calculate a boost score for a fully qualified name (FQNAME) based on a query.

    :param fqname: Fully qualified name of the entity
    :type fqname: str
    :param query: Query string to match against the FQNAME
    :type query: str
    :return: Boost score based on the match
    :rtype: int
    """
    q = (query or "").strip().lower()
    f = (fqname or "").strip().lower()
    if not q or not f:
        return 0
    if q == f:
        return 1000
    if q == f.rsplit(".", 1)[-1]:
        return 600
    if q in f:
        return 250
    return 0


def _fts_phrase(q: str) -> str:
    """Escape a string to be used as a literal phrase in an FTS5 query.
    This is a simple heuristic that wraps the string in double quotes and escapes internal quotes.
    It does not handle all edge cases (e.g. newlines), but should work for typical symbol names and code snippets.
    """
    q = q.replace('"', '""')
    return f'"{q}"'

def _normalize_fts_query(q: str) -> str:
    """
    Normalize a full-text search query for FTS5, treating fqnames and code-like queries as literal phrases.
    
    :param q: The query string to normalize
    :type q: str
    :return: The normalized query string, with heuristics applied to treat certain patterns as literal phrases for FTS5
    :rtype: str
    """
    q = q.strip()
    if _FQNAME_LIKE.fullmatch(q):
        return _fts_phrase(q)
    if _CODE_LIKE.fullmatch(q) or (("." in q) and (" " in q) and ("import" in q or "from" in q)):
        return _fts_phrase(q)
    return q


def lookup_symbol(
    db: Path,
    name: str,
    limit: int = 25,
    kinds: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """
    Lookup symbols in the database by name, with optional filtering by kind and limit on number of results.
    kinds are defined as the "kind" field in the entities table, e.g. "class", "function", "method", "module".
    
    :param db: Path to the SQLite database file
    :type db: Path
    :param name: Name of the symbol to lookup (can be fqname, tail name, or substring)
    :type name: str
    :param limit: Maximum number of results to return
    :type limit: int
    :param kinds: List or tuple of kind strings to filter by, or None for no filtering
    :type kinds: list[str] | tuple[str, ...] | None
    :return: Dictionary containing the matched symbols
    :rtype: dict[str, Any]
    """

    with closing(_connect(db)) as con:
        _ensure_initialized(con, db)
        kinds = _normalize_kinds(kinds)
        kind_clause = ""
        kind_params: tuple[Any, ...] = ()
        if kinds:
            placeholders = ",".join(["?"] * len(kinds))
            kind_clause = f" AND kind IN ({placeholders})"
            kind_params = tuple(kinds)
        # Prefer exact fqname match; fall back to tail match
        q = f"""
        SELECT *, 0 AS rank FROM entities WHERE fqname = ?{kind_clause}
        UNION
        SELECT *, 1 AS rank FROM entities WHERE fqname LIKE ?{kind_clause}
        UNION
        SELECT *, 2 AS rank FROM entities WHERE fqname LIKE ?{kind_clause}
        ORDER BY rank, kind, fqname
        LIMIT ?
        """
        params = (
            name,
            *kind_params,
            f"%.{name}",
            *kind_params,
            f"%{name}%",
            *kind_params,
            limit,
        )
        rows = con.execute(q, params).fetchall()
        return {"matches": [dict(r) for r in rows]}


def search(db: Path, query: str, limit: int = 10, kinds=None) -> dict[str, Any]:
    """
    Search for symbols in the database using a full-text search query, with optional filtering by kind and limit on number of results.
    The algorithm used in the search is as follows:

    1. Normalize the query for FTS5 syntax, with heuristics to treat fqnames and code-like queries as literal phrases.
    2. Execute an FTS5 query against the entities_fts virtual table, joining with entities for metadata, and applying kind filters if provided.
    3. If the FTS5 query fails due to syntax errors (e.g. unbalanced quotes), retry the query with the entire query treated as a literal phrase.
    4. Rank the results by a combination of FQNAME boost (exact match > tail match > substring) and the FTS5 BM25 score.
    5. Return the top-k results as a list of dictionaries.

    :param db: Path to the SQLite database file
    :type db: Path
    :param query: Text query to search for (can be any string, will be normalized for FTS5)
    :type query: str
    :param limit: Maximum number of results to return
    :type limit: int
    :param kinds: List or tuple of kind strings to filter by, or None for no filtering
    :type kinds: list[str] | tuple[str, ...] | None
    :return: Dictionary containing the search results
    :rtype: dict[str, Any]
    """

    raw_query = query
    query = _normalize_fts_query(query)

    with closing(_connect(db)) as con:
        _ensure_initialized(con, db)
        kinds = _normalize_kinds(kinds)

        kind_clause = ""
        params: tuple[Any, ...] = (query,)
        if kinds:
            placeholders = ",".join(["?"] * len(kinds))
            kind_clause = f" AND e.kind IN ({placeholders})"
            params = (query, *kinds)

        q = f"""
        SELECT e.*, bm25(entities_fts) AS fts_score
        FROM entities_fts f
        JOIN entities e ON e.id = f.rowid
        WHERE entities_fts MATCH ?
        {kind_clause}
        ORDER BY bm25(entities_fts)
        LIMIT ?
        """
        candidate_limit = max(limit, min(1000, limit * 20))

        try:
            rows = con.execute(q, (*params, candidate_limit)).fetchall()
        except sqlite3.OperationalError as e:
            msg = str(e)
            if "fts5: syntax error" in msg:
                # Retry as a literal phrase
                quoted = _fts_phrase(raw_query.strip())
                retry_params = (quoted, *kinds) if kinds else (quoted,)
                rows = con.execute(q, (*retry_params, candidate_limit)).fetchall()
                query = quoted 
            else:
                raise

        ranked = sorted(
            rows,
            key=lambda r: (
                -_fqname_boost(r["fqname"], raw_query),
                float(r["fts_score"]),
                r["kind"],
                r["fqname"],
            ),
        )
        return {"results": [dict(r) for r in ranked[:limit]]}


def get_snippet(db: Path, fqname: str) -> dict[str, Any]:
    """
    Retrieve a snippet of code for a given fully qualified name (fqname) from the database.

    :param db: Path to the SQLite database file
    :type db: Path
    :param fqname: Fully qualified name of the entity to retrieve
    :type fqname: str
    :return: Dictionary containing the snippet information, including file path, line numbers, and code text
    :rtype: dict[str, Any]
    """

    con = _connect(db)
    row = con.execute(
        "SELECT file, start_line, end_line, kind, signature FROM entities WHERE fqname = ? LIMIT 1",
        (fqname,),
    ).fetchone()
    if not row:
        return {"error": f"fqname not found: {fqname}"}

    # You stored file paths relative to ARC root in the DB.
    # Put the ARC root path in a tiny metadata table later; for MVP pass it in as env var.
    import os
    arc_root = os.environ.get("CONTEXT6_SOURCE_ROOT")
    if not arc_root:
        return {"error": "Set CONTEXT6_SOURCE_ROOT=/path/to/ARC"}

    path = Path(arc_root) / row["file"]
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, int(row["start_line"]))
    end = min(len(lines), int(row["end_line"]))
    text = "\n".join(lines[start - 1 : end])

    return {
        "fqname": fqname,
        "kind": row["kind"],
        "signature": row["signature"],
        "file": row["file"],
        "start_line": start,
        "end_line": end,
        "text": text,
    }


def normalize_resolve_query(query: str) -> dict[str, Any]:
    """
    Normalize a fuzzy resolve query into a structured format with candidate symbol names.
    The function applies heuristics to extract potential symbol names from the query, including:
    - Parsing "from X import Y" and "import X" statements to extract module and symbol names.
    - Extracting dotted tokens that look like qualified names.
    - Falling back to treating the entire query as a candidate if it looks like an identifier or contains code-like patterns.
    The output includes the original raw query, a normalized query (the first candidate or the raw query), and a list of candidate symbol names to attempt to resolve against the database.
    
    :param query: The raw input query string to normalize
    :type query: str
    :return: A dictionary containing the raw query, normalized query, and list of candidate symbol names
    :rtype: dict[str, Any]
    """

    raw_query = (query or "").strip()
    if not raw_query:
        return {"raw_query": raw_query, "normalized_query": "", "candidates": []}

    candidates: list[str] = []
    seen: set[str] = set()

    def add(v: str) -> None:
        v = v.strip()
        if not v or v in seen:
            return
        seen.add(v)
        candidates.append(v)

    from_m = re.match(r"^\s*from\s+([A-Za-z_][\w.]*)\s+import\s+(.+?)\s*$", raw_query)
    if from_m:
        mod = from_m.group(1)
        imported = from_m.group(2)
        for part in imported.split(","):
            sym = part.strip().split(" as ", 1)[0].strip()
            if not _IDENT.fullmatch(sym):
                continue
            add(sym)
            add(f"{mod}.{sym}")

    import_m = re.match(r"^\s*import\s+([A-Za-z_][\w.]*)", raw_query)
    if import_m:
        mod = import_m.group(1)
        add(mod)
        add(mod.rsplit(".", 1)[-1])

    cleaned = re.sub(r"[`()\[\]{}:,]+", " ", raw_query)
    dotted = [t.strip() for t in re.split(r"\s+", cleaned) if "." in t]
    for tok in dotted:
        parts = [p for p in tok.split(".") if p]
        if not parts:
            continue
        add(tok)
        add(parts[-1])
        if len(parts) >= 2:
            add(".".join(parts[-2:]))
            add(parts[-2])

    add(raw_query)
    if "." in raw_query:
        add(raw_query.rsplit(".", 1)[-1])

    return {
        "raw_query": raw_query,
        "normalized_query": candidates[0] if candidates else raw_query,
        "candidates": candidates,
    }


def tiny_entity_snippet(
    source_root: Path,
    entity: Mapping[str, Any],
    max_lines: int = 10,
) -> dict[str, Any]:
    """
    Retrieve a tiny snippet of code for a given entity, based on its file and line numbers.
    
    :param source_root: The root directory of the source code
    :type source_root: Path
    :param entity: A dictionary containing the entity's metadata, including file and line numbers
    :type entity: Mapping[str, Any]
    :param max_lines: The maximum number of lines to include in the snippet
    :type max_lines: int
    :return: A dictionary containing the file path, start line, end line, and snippet text
    :rtype: dict[str, Any]
    """

    rel_file = str(entity["file"])
    path = source_root / rel_file
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, int(entity["start_line"]))
    end = min(len(lines), start + max(1, max_lines) - 1)
    return {
        "file": rel_file,
        "start_line": start,
        "end_line": end,
        "text": "\n".join(lines[start - 1 : end]),
    }


def class_methods(db: Path, class_fqname: str, limit: int = 5) -> list[dict[str, Any]]:
    """
    Retrieve a list of methods for a given class, ranked by relevance.
    
    :param db: The path to the database containing entity information
    :type db: Path
    :param class_fqname: The fully qualified name of the class
    :type class_fqname: str
    :param limit: The maximum number of methods to return
    :type limit: int
    :return: A list of dictionaries, each containing metadata about a method belonging to the specified class, ranked by relevance based on naming heuristics and line number proximity.
    :rtype: list[dict[str, Any]]
    """

    with closing(_connect(db)) as con:
        rows = con.execute(
            """
            SELECT id, kind, fqname, signature, file, start_line, end_line, summary
            FROM entities
            WHERE kind='method' AND fqname LIKE ?
            ORDER BY start_line, fqname
            LIMIT 250
            """,
            (f"{class_fqname}.%",),
        ).fetchall()

    def _method_name(fqname: str) -> str:
        if not fqname.startswith(class_fqname + "."):
            return fqname.rsplit(".", 1)[-1]
        return fqname[len(class_fqname) + 1 :]

    prefer_exact = {
        "__init__",
        "from_dict",
        "as_dict",
        "to_dict",
        "from_json",
        "to_json",
    }
    prefer_prefix = ("from_", "as_", "to_", "get_", "set_", "is_", "has_")

    ranked: list[tuple[tuple[int, int, str], dict[str, Any]]] = []
    for row in rows:
        e = dict(row)
        method = _method_name(e["fqname"])
        if "." in method:
            continue
        if method in prefer_exact:
            score = 0
        elif method.startswith(prefer_prefix):
            score = 1
        else:
            score = 5
        ranked.append(((score, int(e["start_line"]), method), e))

    ranked.sort(key=lambda x: x[0])
    return [e for _, e in ranked[: max(1, limit)]]


def module_neighbors(
    db: Path,
    file: str,
    start_line: int,
    end_line: int,
    *,
    exclude_id: int | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Retrieve a list of neighboring entities in the same module, ranked by proximity to the given line numbers.

    :param db: The path to the database containing entity information
    :type db: Path
    :param file: The relative file path of the module to search within
    :type file: str
    :param start_line: The starting line number of the reference entity
    :type start_line: int
    :param end_line: The ending line number of the reference entity
    :type end_line: int
    :param exclude_id: An optional entity ID to exclude from the results (e.g.,
                        the reference entity itself)
    :type exclude_id: int | None
    :param limit: The maximum number of neighboring entities to return
    :type limit: int
    :return: A list of dictionaries, each containing metadata about a neighboring entity in the same
                module, ranked by proximity to the reference line numbers and filtered by kind (class, function, method).
    :rtype: list[dict[str, Any]]
    """
    with closing(_connect(db)) as con:
        rows = con.execute(
            """
            SELECT id, kind, fqname, signature, file, start_line, end_line, summary
            FROM entities
            WHERE file = ?
              AND kind IN ('class', 'function', 'method')
            ORDER BY start_line, fqname
            """,
            (file,),
        ).fetchall()

    def _distance(row: Mapping[str, Any]) -> int:
        s = int(row["start_line"])
        e = int(row["end_line"])
        if e < start_line:
            return start_line - e
        if s > end_line:
            return s - end_line
        return 0

    kind_rank = {"class": 0, "function": 0, "method": 1}
    scored: list[tuple[tuple[int, int, int, str], dict[str, Any]]] = []
    for row in rows:
        e = dict(row)
        if exclude_id is not None and int(e["id"]) == int(exclude_id):
            continue
        d = _distance(e)
        scored.append(((kind_rank.get(e["kind"], 9), d, int(e["start_line"]), e["fqname"]), e))
    scored.sort(key=lambda x: x[0])
    return [e for _, e in scored[: max(1, limit)]]
