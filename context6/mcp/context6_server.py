from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from fastmcp import FastMCP

from context6.core.retrieve import (
    lookup_symbol,
    search,
    get_snippet,
    normalize_resolve_query,
    tiny_entity_snippet,
    class_methods,
    module_neighbors,
)
from context6.core.present import best_match_entity, pretty_lookup_entity
from context6.core.summarize import summarize_one
from context6.db.sqlite import _connect



@dataclass(frozen=True)
class cfg:
    """
    Configuration for Context6 MCP tools, loaded from environment variables with defaults.
    """
    db: Path
    source_root: Path
    default_kinds: tuple[str, ...] = ("class", "function", "method", "module")
    summarizer: str = "auto"
    codex_bin: str = "codex"


def _cfg() -> cfg:
    """
    Load configuration from environment variables, with defaults. Validates that paths exist.

    Returns:
        cfg: A cfg dataclass instance containing resolved configuration values for the database path, source root, summarizer choice, and codex binary.
    """
    raw_db = os.environ.get("CONTEXT6_DB")
    if raw_db and raw_db.strip():
        db = Path(raw_db).expanduser()
    else:
        db = Path.home() / "code" / "context6" / "arc" / "context6.db"

    raw_root = os.environ.get("CONTEXT6_SOURCE_ROOT")
    source_root = Path(raw_root).expanduser() if raw_root and raw_root.strip() else Path("")

    return cfg(db=db, 
               source_root=source_root, 
               summarizer=os.environ.get("CONTEXT6_SUMMARIZER", "auto"),
               codex_bin=os.environ.get("CONTEXT6_CODEX_BIN", "codex")
    )


def _require_paths(cfg):
    """
    Ensure that the paths specified in the configuration exist and are of the correct type.

    :param cfg: Configuration object containing paths to validate
    :type cfg: cfg
    """

    if not cfg.db.exists() or not cfg.db.is_file():
        raise RuntimeError(f"DB not found or not a file: {cfg.db}")
    if not cfg.source_root.exists() or not cfg.source_root.is_dir():
        raise RuntimeError(f"SOURCE_ROOT not found or not a dir: {cfg.source_root}")


def _normalize_kinds(kinds: Optional[Union[str, list[str]]]) -> Optional[list[str]]:
    """
    Normalize a list of kinds or a single kind into a list of strings.

    :param kinds: A single kind (str) or a list of kinds (list[str]), or None
    :type kinds: Optional[Union[str, list[str]]]
    :return: Normalized list of kinds or None if input is empty
    :rtype: list[str] | None
    """
    if not kinds:
        return None
    if isinstance(kinds, str):
        kinds = [kinds]
    out = [k.strip() for k in kinds if k and k.strip()]
    return out or None


mcp = FastMCP("Context6", "0.2.0")


@mcp.tool("context6_health")
def context6_health() -> dict[str, Any]:
    """
    Quick health check: returns resolved config and whether files exist.
    """
    cfg = _cfg()
    return {
        "db": str(cfg.db),
        "db_exists": cfg.db.exists(),
        "source_root": str(cfg.source_root),
        "source_root_exists": cfg.source_root.exists(),
        "summarizer": cfg.summarizer,
        "codex_bin": cfg.codex_bin,
    }


@mcp.tool("context6_lookup")
def context6_lookup(
    name: str,
    limit: int = 25,
    kinds: Optional[Union[str, list[str]]] = None,
) -> dict[str, Any]:
    """
    Symbol lookup by fqname/tail/substring (DB-backed).
    `kinds` can be a single kind (e.g. "method") or a list of kinds.
    """
    cfg = _cfg()
    _require_paths(cfg)
    return lookup_symbol(cfg.db, name, limit=limit, kinds=_normalize_kinds(kinds) or list(cfg.default_kinds))


@mcp.tool("context6_search")
def context6_search(
    query: str,
    limit: int = 10,
    kinds: Optional[Union[str, list[str]]] = None,
) -> dict[str, Any]:
    """
    Full-text search (FTS5) over fqname/signature/docstring/summary.
    `kinds` can be a single kind (e.g. "method") or a list of kinds.
    """
    cfg = _cfg()
    _require_paths(cfg)
    return search(cfg.db, query, limit=limit, kinds=_normalize_kinds(kinds) or list(cfg.default_kinds))

@mcp.tool("context6_snippet")
def context6_snippet(
    fqname: str,
    max_lines: int = 220,
) -> dict[str, Any]:
    """
    Return a code snippet for an entity. Truncates to max_lines to keep payload small.
    """
    cfg = _cfg()
    _require_paths(cfg)

    # get_snippet already relies on CONTEXT6_SOURCE_ROOT internally
    # so make sure env var is aligned with cfg.source_root
    os.environ["CONTEXT6_SOURCE_ROOT"] = str(cfg.source_root)

    out = get_snippet(cfg.db, fqname)
    if "text" in out:
        lines = out["text"].splitlines()
        was_truncated = len(lines) > max_lines
        out["text"] = "\n".join(lines[:max_lines])
        out["was_truncated"] = was_truncated
        out["line_count"] = len(lines)
    return out


@mcp.tool("context6_pretty_lookup")
def context6_pretty_lookup(
    name: str,
    kinds: Optional[Union[str, list[str]]] = None,
) -> dict[str, Any]:
    """
    “Best match” lookup + human-readable formatted view (summary + small snippet).
    Uses best_match_entity + pretty_lookup_entity.
    """
    cfg = _cfg()
    _require_paths(cfg)

    e = best_match_entity(cfg.db, name, kinds=_normalize_kinds(kinds))
    if not e:
        return {"error": f"No matches for: {name}"}

    # pretty_lookup_entity reads source files; keep env aligned
    os.environ["CONTEXT6_SOURCE_ROOT"] = str(cfg.source_root)

    text = pretty_lookup_entity(cfg.db, cfg.source_root, e)
    return {"entity": e, "text": text}


@mcp.tool("context6_summarize_entity")
def context6_summarize_entity(
    name: str,
    kinds: Optional[Union[str, list[str]]] = None,
) -> dict[str, Any]:
    """
    Generate + store a summary for the best-matching entity if missing.
    Returns the updated entity row (including summary fields).
    """
    cfg = _cfg()
    _require_paths(cfg)
    os.environ["CONTEXT6_SOURCE_ROOT"] = str(cfg.source_root)

    e = best_match_entity(cfg.db, name, kinds=_normalize_kinds(kinds))
    if not e:
        return {"error": f"No matches for: {name}"}

    # Only summarize if empty (you can add force=True later)
    if (e.get("summary") or "").strip():
        return {"entity": e, "did_work": False}

    summarize_one(
        db=cfg.db,
        entity_id=e["id"],
        fqname=e["fqname"],
        kind=e["kind"],
        signature=e.get("signature") or "",
        docstring=e.get("docstring") or "",
        summarizer=cfg.summarizer,
        codex_bin=cfg.codex_bin,
    )

    # Re-fetch updated row
    con = _connect(cfg.db)
    try:
        row = con.execute("SELECT * FROM entities WHERE id=?", (e["id"],)).fetchone()
        return {"entity": dict(row) if row else e, "did_work": True}
    finally:
        con.close()


@mcp.tool("context6_resolve")
def context6_resolve(query: str, limit_methods: int = 5) -> dict[str, Any]:
    """
    Resolve a fuzzy query into a compact, answer-ready payload.
    Includes best entity, tiny snippet, related class methods, and module neighbors.
    """
    cfg = _cfg()
    _require_paths(cfg)

    parsed = normalize_resolve_query(query)
    candidates = parsed.get("candidates") or []

    best: dict[str, Any] | None = None
    matched_by = ""
    for cand in candidates:
        best = best_match_entity(cfg.db, cand, kinds=list(cfg.default_kinds))
        if best:
            matched_by = cand
            break

    if not best:
        return {
            "error": f"No matches for: {query}",
            "query": parsed,
        }

    tiny = tiny_entity_snippet(cfg.source_root, best, max_lines=10)

    same_class: list[dict[str, Any]] = []
    if best["kind"] == "class":
        same_class = class_methods(cfg.db, best["fqname"], limit=max(1, limit_methods))
    elif best["kind"] == "method" and "." in best["fqname"]:
        owner = best["fqname"].rsplit(".", 1)[0]
        same_class = class_methods(cfg.db, owner, limit=max(1, limit_methods))

    neighbors = module_neighbors(
        cfg.db,
        file=best["file"],
        start_line=int(best["start_line"]),
        end_line=int(best["end_line"]),
        exclude_id=int(best["id"]),
        limit=max(3, limit_methods),
    )

    return {
        "query": parsed,
        "matched_by": matched_by,
        "entity": {
            "fqname": best["fqname"],
            "kind": best["kind"],
            "signature": best.get("signature") or "",
            "summary": (best.get("summary") or "").strip(),
            "file": best["file"],
            "start_line": best["start_line"],
            "end_line": best["end_line"],
        },
        "snippet": tiny,
        "related": {
            "class_methods": same_class,
            "module_neighbors": neighbors,
        },
    }

if __name__ == "__main__":
    mcp.run(transport="stdio")
