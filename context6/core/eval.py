from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from context6.core.retrieve import lookup_symbol, search


def _normalize_qrels_item(item: dict[str, Any]) -> dict[str, Any]:
    query = (item.get("query") or "").strip()
    relevant = item.get("relevant")
    if relevant is None:
        relevant = item.get("relevant_fqnames")
    if not isinstance(relevant, list):
        raise ValueError("Each qrels item must include list field 'relevant' (or 'relevant_fqnames').")
    relevant_out: list[str] = []
    relevant_kinds: dict[str, str] = {}
    for raw in relevant:
        if isinstance(raw, str):
            fq = raw.strip()
            if fq:
                relevant_out.append(fq)
            continue
        if isinstance(raw, dict):
            fq = str(raw.get("fqname") or "").strip()
            if not fq:
                raise ValueError("Qrels relevant object must include non-empty 'fqname'.")
            relevant_out.append(fq)
            kind = str(raw.get("kind") or "").strip()
            if kind:
                relevant_kinds[fq] = kind
            continue
        raise ValueError("Qrels 'relevant' entries must be string fqname or object with fqname/kind.")

    relevant = [x for x in relevant_out if x]
    if not query:
        raise ValueError("Each qrels item must include non-empty 'query'.")
    if not relevant:
        raise ValueError(f"Qrels for query '{query}' has no relevant fqnames.")
    out = {"query": query, "relevant": relevant}
    if relevant_kinds:
        out["relevant_kinds"] = relevant_kinds
    return out


def _fetch_entity_kinds(db: Path, fqnames: set[str]) -> dict[str, str]:
    if not fqnames:
        return {}
    con = sqlite3.connect(str(db))
    try:
        placeholders = ",".join(["?"] * len(fqnames))
        rows = con.execute(
            f"SELECT fqname, kind FROM entities WHERE fqname IN ({placeholders})",
            tuple(sorted(fqnames)),
        ).fetchall()
        return {str(r[0]): str(r[1]) for r in rows}
    finally:
        con.close()


def load_qrels(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        rows: list[dict[str, Any]] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            rows.append(_normalize_qrels_item(json.loads(line)))
        if not rows:
            raise ValueError(f"No qrels rows found in {path}")
        return rows

    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("JSON qrels file must be a list of objects.")
    rows = [_normalize_qrels_item(x) for x in data]
    if not rows:
        raise ValueError(f"No qrels rows found in {path}")
    return rows


def evaluate_recall_at_k(
    db: Path,
    qrels: list[dict[str, Any]],
    k: int = 10,
    retriever: str = "search",
    kinds: list[str] | tuple[str, ...] | None = ("class",),
) -> dict[str, Any]:
    if k <= 0:
        raise ValueError("k must be > 0")
    if retriever not in ("search", "lookup"):
        raise ValueError("retriever must be 'search' or 'lookup'")

    details: list[dict[str, Any]] = []
    warnings: list[str] = []
    recall_sum = 0.0
    hit_sum = 0.0

    all_relevant = set()
    for row in qrels:
        item = _normalize_qrels_item(row)
        all_relevant.update(item["relevant"])
    db_kinds = _fetch_entity_kinds(db, all_relevant)

    for row in qrels:
        item = _normalize_qrels_item(row)
        query = item["query"]
        relevant = set(item["relevant"])
        explicit_kinds = item.get("relevant_kinds") or {}
        relevant_kind_map = {fq: explicit_kinds.get(fq) or db_kinds.get(fq) for fq in relevant}

        excluded_relevant = []
        eligible_relevant: set[str] = set(relevant)
        if kinds:
            allowed = set(kinds)
            eligible_relevant = set()
            for fq in sorted(relevant):
                knd = relevant_kind_map.get(fq)
                if knd in allowed:
                    eligible_relevant.add(fq)
                    continue
                excluded_relevant.append({"fqname": fq, "kind": knd or "unknown"})
            if excluded_relevant:
                warnings.append(
                    f"Query '{query}': {len(excluded_relevant)}/{len(relevant)} relevant targets are excluded by kinds filter {list(kinds)}."
                )

        if retriever == "search":
            out = search(db, query, limit=k, kinds=kinds)
            returned = [r["fqname"] for r in out["results"][:k]]
        else:
            out = lookup_symbol(db, query, limit=k, kinds=kinds)
            returned = [r["fqname"] for r in out["matches"][:k]]

        returned_set = set(returned)
        eligible_matched = sorted(eligible_relevant.intersection(returned_set))
        eligible_relevant_count = len(eligible_relevant)
        recall = (len(eligible_matched) / eligible_relevant_count) if eligible_relevant_count else 0.0
        hit = 1.0 if eligible_matched else 0.0

        recall_sum += recall
        hit_sum += hit
        details.append(
            {
                "query": query,
                "relevant_count": len(relevant),
                "eligible_relevant_count": eligible_relevant_count,
                "retrieved_count": len(returned),
                "matched_count": len(eligible_matched),
                "eligible_matched_count": len(eligible_matched),
                "recall_at_k": recall,
                "hit_at_k": hit,
                "matched_fqnames": eligible_matched,
                "excluded_relevant_by_kinds": excluded_relevant,
            }
        )

    n = len(details)
    return {
        "k": k,
        "retriever": retriever,
        "kinds": list(kinds) if kinds else None,
        "num_queries": n,
        "recall_at_k": (recall_sum / n) if n else 0.0,
        "hit_rate_at_k": (hit_sum / n) if n else 0.0,
        "warnings": sorted(set(warnings)),
        "details": details,
    }
