from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from context6.core.present import (
    _extract_init_header,
    _first_nonempty_line,
    best_match_entity,
    pretty_lookup_entity,
)
from context6.db.sqlite import ingest_index, init_db


class TestPresent(unittest.TestCase):
    """Tests for presentation utilities and entity ranking behavior."""

    def test_first_nonempty_line(self) -> None:
        """Should return the first non-blank line or an empty string if none exist."""
        self.assertEqual("abc", _first_nonempty_line("\n   \nabc\nz"))
        self.assertEqual("", _first_nonempty_line(" \n\t\n"))

    def test_extract_init_header_includes_decorators(self) -> None:
        """Initializer header extraction should include nearby decorators."""
        text = (
            "class C:\n"
            "    @dec1\n"
            "    @dec2\n"
            "    def __init__(self, x):\n"
            "        self.x = x\n"
        )
        hdr = _extract_init_header(text)
        self.assertIn("@dec1", hdr)
        self.assertIn("def __init__(self, x):", hdr)

    def test_best_match_prefers_exact_and_kind_order(self) -> None:
        """Best-match selection should prioritize exact matches and stable kind ranking."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            db = root / "c6.db"
            init_db(db)
            ingest_index(
                db,
                {
                    "root": str(root),
                    "entities": [
                        {
                            "kind": "function",
                            "fqname": "pkg.target",
                            "file": "f.py",
                            "start_line": 1,
                            "end_line": 1,
                            "signature": "target()",
                            "docstring": "",
                            "summary": "",
                            "code_hash": "1",
                        },
                        {
                            "kind": "class",
                            "fqname": "pkg.sub.target",
                            "file": "f.py",
                            "start_line": 1,
                            "end_line": 1,
                            "signature": "class target",
                            "docstring": "",
                            "summary": "",
                            "code_hash": "2",
                        },
                    ],
                    "relations": [],
                },
            )

            exact = best_match_entity(db, "pkg.target")
            self.assertIsNotNone(exact)
            self.assertEqual("pkg.target", exact["fqname"])

            tail = best_match_entity(db, "target")
            self.assertIsNotNone(tail)
            self.assertEqual("pkg.sub.target", tail["fqname"])

            only_functions = best_match_entity(db, "target", kinds=["function"])
            self.assertIsNotNone(only_functions)
            self.assertEqual("pkg.target", only_functions["fqname"])

    def test_pretty_lookup_entity_formats_summary_and_snippet(self) -> None:
        """Entity rendering should include header, summary placeholder, and code snippet."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "pkg.py"
            src.write_text("def f():\n    return 1\n", encoding="utf-8")
            e = {
                "fqname": "pkg.f",
                "kind": "function",
                "file": "pkg.py",
                "start_line": 1,
                "end_line": 2,
                "signature": "f()",
                "summary": "",
                "docstring": "",
            }
            out = pretty_lookup_entity(root / "db.sqlite", root, e)
            self.assertIn("pkg.f  (function)", out)
            self.assertIn("<empty> (run `context6 summarize` to populate)", out)
            self.assertIn("def f():", out)


if __name__ == "__main__":
    unittest.main()
