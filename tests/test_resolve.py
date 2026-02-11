from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from context6.core.retrieve import (
    class_methods,
    module_neighbors,
    normalize_resolve_query,
    tiny_entity_snippet,
)
from context6.db.sqlite import ingest_index, init_db


class TestResolve(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.db = self.root / "context6.db"
        self.src_root = self.root / "src"
        (self.src_root / "pkg").mkdir(parents=True, exist_ok=True)

        (self.src_root / "pkg" / "mod.py").write_text(
            "class C:\n"
            "    \"\"\"Main class.\"\"\"\n"
            "\n"
            "    def __init__(self, x):\n"
            "        self.x = x\n"
            "\n"
            "    def get_x(self):\n"
            "        return self.x\n"
            "\n"
            "    def helper(self):\n"
            "        return self.x + 1\n"
            "\n"
            "def nearby():\n"
            "    return C(1)\n"
            "\n"
            "def farther():\n"
            "    return 42\n",
            encoding="utf-8",
        )

        init_db(self.db)
        ingest_index(
            self.db,
            {
                "root": str(self.src_root),
                "entities": [
                    {
                        "kind": "class",
                        "fqname": "pkg.mod.C",
                        "file": "pkg/mod.py",
                        "start_line": 1,
                        "end_line": 11,
                        "signature": "class C",
                        "docstring": "Main class.",
                        "summary": "Core class",
                        "code_hash": "h1",
                    },
                    {
                        "kind": "method",
                        "fqname": "pkg.mod.C.__init__",
                        "file": "pkg/mod.py",
                        "start_line": 4,
                        "end_line": 5,
                        "signature": "__init__(self, x)",
                        "docstring": "",
                        "summary": "",
                        "code_hash": "h2",
                    },
                    {
                        "kind": "method",
                        "fqname": "pkg.mod.C.get_x",
                        "file": "pkg/mod.py",
                        "start_line": 7,
                        "end_line": 8,
                        "signature": "get_x(self)",
                        "docstring": "",
                        "summary": "",
                        "code_hash": "h3",
                    },
                    {
                        "kind": "method",
                        "fqname": "pkg.mod.C.helper",
                        "file": "pkg/mod.py",
                        "start_line": 10,
                        "end_line": 11,
                        "signature": "helper(self)",
                        "docstring": "",
                        "summary": "",
                        "code_hash": "h4",
                    },
                    {
                        "kind": "function",
                        "fqname": "pkg.mod.nearby",
                        "file": "pkg/mod.py",
                        "start_line": 13,
                        "end_line": 14,
                        "signature": "nearby()",
                        "docstring": "",
                        "summary": "",
                        "code_hash": "h5",
                    },
                    {
                        "kind": "function",
                        "fqname": "pkg.mod.farther",
                        "file": "pkg/mod.py",
                        "start_line": 16,
                        "end_line": 17,
                        "signature": "farther()",
                        "docstring": "",
                        "summary": "",
                        "code_hash": "h6",
                    },
                ],
                "relations": [],
            },
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_normalize_resolve_query_extracts_symbol(self) -> None:
        parsed = normalize_resolve_query("from pkg.mod import C")
        self.assertIn("C", parsed["candidates"])
        self.assertIn("pkg.mod.C", parsed["candidates"])

    def test_class_methods_prefers_common_entrypoints(self) -> None:
        rows = class_methods(self.db, "pkg.mod.C", limit=3)
        names = [r["fqname"] for r in rows]
        self.assertEqual("pkg.mod.C.__init__", names[0])
        self.assertIn("pkg.mod.C.get_x", names)

    def test_module_neighbors_prefers_nearby_symbols(self) -> None:
        rows = module_neighbors(
            self.db,
            file="pkg/mod.py",
            start_line=1,
            end_line=11,
            exclude_id=1,
            limit=2,
        )
        names = [r["fqname"] for r in rows]
        self.assertIn("pkg.mod.nearby", names)

    def test_tiny_entity_snippet_returns_short_window(self) -> None:
        entity = {
            "file": "pkg/mod.py",
            "start_line": 1,
        }
        out = tiny_entity_snippet(self.src_root, entity, max_lines=3)
        self.assertEqual(1, out["start_line"])
        self.assertEqual(3, out["end_line"])
        self.assertIn("class C:", out["text"])


if __name__ == "__main__":
    unittest.main()
