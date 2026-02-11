from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from context6.core.retrieve import get_snippet, lookup_symbol, search
from context6.db.sqlite import get_entities_needing_summary, ingest_index, init_db


class TestDbAndRetrieve(unittest.TestCase):
    """Integration-style tests for DB ingestion and retrieval helpers."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.db = self.root / "context6.db"
        self.src_root = self.root / "src"
        self.src_root.mkdir(parents=True, exist_ok=True)
        (self.src_root / "pkg").mkdir(parents=True, exist_ok=True)
        (self.src_root / "pkg" / "mod.py").write_text(
            "def fn(x):\n"
            "    return x + 1\n",
            encoding="utf-8",
        )

        init_db(self.db)
        ingest_index(
            self.db,
            {
                "root": str(self.src_root),
                "entities": [
                    {
                        "kind": "function",
                        "fqname": "pkg.mod.fn",
                        "file": "pkg/mod.py",
                        "start_line": 1,
                        "end_line": 2,
                        "signature": "fn(x)",
                        "docstring": "",
                        "summary": "adds one",
                        "code_hash": "h1",
                    },
                    {
                        "kind": "class",
                        "fqname": "pkg.mod.C",
                        "file": "pkg/mod.py",
                        "start_line": 1,
                        "end_line": 2,
                        "signature": "class C",
                        "docstring": "",
                        "summary": "",
                        "code_hash": "h2",
                    },
                ],
                "relations": [
                    {"src": "pkg.mod", "rel": "defines", "dst": "pkg.mod.fn"},
                ],
            },
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_get_entities_needing_summary_filters_empty(self) -> None:
        """Only entities with empty summaries should be returned for summarization."""
        todo = get_entities_needing_summary(self.db)
        names = {e["fqname"] for e in todo}
        self.assertIn("pkg.mod.C", names)
        self.assertNotIn("pkg.mod.fn", names)

    def test_lookup_symbol_and_search(self) -> None:
        """Symbol lookup and FTS search should return expected indexed entities."""
        out = lookup_symbol(self.db, "fn")
        self.assertTrue(any(m["fqname"] == "pkg.mod.fn" for m in out["matches"]))

        res = search(self.db, "adds")
        self.assertTrue(any(r["fqname"] == "pkg.mod.fn" for r in res["results"]))

    def test_search_with_kind_filter(self) -> None:
        """Search kind filters should restrict result kinds."""
        res = search(self.db, "adds", kinds=["class"])
        self.assertEqual([], res["results"])

    def test_get_snippet_requires_source_root(self) -> None:
        """Snippet retrieval should fail with a clear error when source root is unset."""
        old = os.environ.pop("CONTEXT6_SOURCE_ROOT", None)
        try:
            res = get_snippet(self.db, "pkg.mod.fn")
            self.assertIn("Set CONTEXT6_SOURCE_ROOT", res["error"])
        finally:
            if old is not None:
                os.environ["CONTEXT6_SOURCE_ROOT"] = old

    def test_get_snippet_returns_text(self) -> None:
        """Snippet retrieval should return text content when source root is configured."""
        old = os.environ.get("CONTEXT6_SOURCE_ROOT")
        os.environ["CONTEXT6_SOURCE_ROOT"] = str(self.src_root)
        try:
            res = get_snippet(self.db, "pkg.mod.fn")
            self.assertEqual("pkg.mod.fn", res["fqname"])
            self.assertIn("def fn(x):", res["text"])
        finally:
            if old is None:
                os.environ.pop("CONTEXT6_SOURCE_ROOT", None)
            else:
                os.environ["CONTEXT6_SOURCE_ROOT"] = old

    def test_lookup_raises_on_uninitialized_db(self) -> None:
        """Lookup should raise when the DB is missing required context6 tables."""
        bad_db = self.root / "empty.db"
        sqlite3.connect(str(bad_db)).close()
        with self.assertRaises(RuntimeError):
            lookup_symbol(bad_db, "fn")

    def test_search_boosts_exact_symbol_shape(self) -> None:
        """Search should rank exact-symbol-like fqnames above broader substring matches."""
        ingest_index(
            self.db,
            {
                "root": str(self.src_root),
                "entities": [
                    {
                        "kind": "class",
                        "fqname": "arc.main.ARC",
                        "file": "pkg/mod.py",
                        "start_line": 1,
                        "end_line": 2,
                        "signature": "class ARC",
                        "docstring": "",
                        "summary": "main ARC class",
                        "code_hash": "h3",
                    },
                    {
                        "kind": "method",
                        "fqname": "arc.main.ARC.execute",
                        "file": "pkg/mod.py",
                        "start_line": 1,
                        "end_line": 2,
                        "signature": "execute(self)",
                        "docstring": "",
                        "summary": "execute ARC run",
                        "code_hash": "h4",
                    },
                ],
                "relations": [],
            },
        )

        res = search(self.db, "ARC", limit=10, kinds=["class", "method", "module", "function"])
        names = [r["fqname"] for r in res["results"]]
        self.assertIn("arc.main.ARC", names)
        self.assertIn("arc.main.ARC.execute", names)
        self.assertLess(names.index("arc.main.ARC"), names.index("arc.main.ARC.execute"))


if __name__ == "__main__":
    unittest.main()
