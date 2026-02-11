import argparse
import json
from pathlib import Path
import sys
import os
from context6.core.indexer import build_index
from context6.db.sqlite import init_db, ingest_index
from context6.core.retrieve import search, get_snippet
from context6.core.summarize import run_summarize
from context6.core.present import best_match_entity, pretty_lookup_entity
from context6.core.eval import evaluate_recall_at_k, load_qrels


def _parse_kinds_csv(raw: str | None) -> list[str] | None:
    """
    Parse a comma-separated string of kinds into a list of strings, or return None if input is empty.
    :param raw: Comma-separated string of kinds (e.g., "class,function") or None
    :type raw: str | None
    :return: List of kinds (e.g., ["class", "function"]) or None if input is empty
    :rtype: list[str] | None
    """

    if raw is None:
        return None
    kinds = [x.strip() for x in raw.split(",") if x.strip()]
    return kinds or None


def _print_json(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main():
    p = argparse.ArgumentParser(description="Context6: A code search and navigation tool")
    sub = p.add_subparsers(dest="cmd", required=True)
    p_index = sub.add_parser("index", help="Build an index and load into the database")
    p_index.add_argument("--source", type=Path, help="Source code directory to index")
    p_index.add_argument("--out", type=Path, default=Path.home()/"code/context6/arc", help="Output directory")
    p_index.add_argument("--db", type=Path, default=None, help="Path to the database (overrides --out)")

    p_lookup = sub.add_parser("lookup", help="Lookup a symbol by name")
    p_lookup.add_argument("--db", type=Path, required=True, help="Path to the database")
    p_lookup.add_argument("name", type=str, help="Name of the symbol to lookup")
    p_lookup.add_argument("--source", type=Path, default=None, help="Path to ARC repo root (or set CONTEXT6_SOURCE_ROOT)")
    p_lookup.add_argument("--kinds", type=str, default="class", help="Comma-separated kinds filter (default: class)")
    p_lookup.add_argument("--summarizer", choices=["auto", "ollama", "codex"], default="auto")
    p_lookup.add_argument("--codex-bin", type=str, default=os.environ.get("CONTEXT6_CODEX_BIN", "codex"))


    p_search = sub.add_parser("search", help="Search by text query")
    p_search.add_argument("--db", type=Path, required=True, help="Path to the database")
    p_search.add_argument("query", type=str, help="Text query to search for")
    p_search.add_argument("--kinds", type=str, default="class", help="Comma-separated kinds filter (default: class)")

    p_snip = sub.add_parser("snippet", help="Show code snippet for fqname")
    p_snip.add_argument("--db", type=Path, required=True, help="Path to the database")
    p_snip.add_argument("fqname", type=str, help="Fully qualified name of the symbol")

    p_sum = sub.add_parser("summarize", help="Generate summaries")
    p_sum.add_argument("--db", type=Path, required=True)
    p_sum.add_argument("--limit", type=int, default=200)
    p_sum.add_argument("--summarizer", choices=["auto", "ollama", "codex"], default="auto")
    p_sum.add_argument("--codex-bin", type=str, default=os.environ.get("CONTEXT6_CODEX_BIN", "codex"))

    p_eval = sub.add_parser("eval-recall", help="Evaluate retrieval recall@k from qrels")
    p_eval.add_argument("--db", type=Path, required=True, help="Path to the database")
    p_eval.add_argument("--qrels", type=Path, required=True, help="Path to qrels .json or .jsonl file")
    p_eval.add_argument("--k", type=int, default=10, help="Top-k cutoff")
    p_eval.add_argument("--retriever", choices=["search", "lookup"], default="search")
    p_eval.add_argument("--kinds", type=str, default="class", help="Comma-separated kinds filter (default: class)")

    args = p.parse_args()

    if args.cmd == "index":
        print(f"Indexing source code in {args.source}...")
        out = args.out
        out.mkdir(parents=True, exist_ok=True)
        db_path = args.db or (out / "context6.db")
        init_db(db_path)
        idx = build_index(args.source)
        ingest_index(db_path, idx)
        print(f"Index {len(idx)} symbols built.")
        print(f"Indexing complete. Database saved to {db_path}")

    elif args.cmd == "lookup":


        source = args.source or Path(os.environ.get("CONTEXT6_SOURCE_ROOT", ""))
        if not source or not source.exists():
            print("Set --source /path/to/ARC or export CONTEXT6_SOURCE_ROOT=/path/to/ARC")
            return

        lookup_kinds = _parse_kinds_csv(args.kinds)
        e = best_match_entity(args.db, args.name, kinds=lookup_kinds)
        if not e:
            print(f"No matches for: {args.name}")
            return
        print(pretty_lookup_entity(args.db, source, e))


    elif args.cmd == "search":
        try:
            res = search(args.db, args.query, kinds=_parse_kinds_csv(args.kinds))
        except Exception as e:
            print(str(e), file=sys.stderr)
            raise SystemExit(2)
        _print_json(res)

    elif args.cmd == "snippet":
        try:
            res = get_snippet(args.db, args.fqname)
        except Exception as e:
            print(str(e), file=sys.stderr)
            raise SystemExit(2)
        _print_json(res)
    
    elif args.cmd == "summarize":
        n = run_summarize(args.db, limit=args.limit, summarizer=args.summarizer, codex_bin=args.codex_bin)
        print(f"Summarized {n} entities")

    elif args.cmd == "eval-recall":
        qrels = load_qrels(args.qrels)
        out = evaluate_recall_at_k(
            args.db,
            qrels,
            k=args.k,
            retriever=args.retriever,
            kinds=_parse_kinds_csv(args.kinds),
        )
        _print_json(out)


if __name__ == "__main__":
    main()
