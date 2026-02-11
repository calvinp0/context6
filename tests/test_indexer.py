from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from context6.core.indexer import build_index


class TestIndexer(unittest.TestCase):
    """Tests for Python source indexing into entities and relations."""

    def test_build_index_extracts_entities_and_relations(self) -> None:
        """Indexer should emit module/class/method/function entities and import/define relations."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "pkg" / "mod.py"
            src.parent.mkdir(parents=True, exist_ok=True)
            src.write_text(
                '"""module docs"""\n'
                "import os\n"
                "from math import sqrt\n\n"
                "class A:\n"
                '    """class docs"""\n'
                "    def m(self, x):\n"
                '        """method docs"""\n'
                "        return x\n\n"
                "def f(a, *args, **kwargs):\n"
                "    return a\n",
                encoding="utf-8",
            )

            idx = build_index(root)

        kinds_by_name = {e["fqname"]: e["kind"] for e in idx["entities"]}
        self.assertEqual("module", kinds_by_name["pkg.mod"])
        self.assertEqual("class", kinds_by_name["pkg.mod.A"])
        self.assertEqual("method", kinds_by_name["pkg.mod.A.m"])
        self.assertEqual("function", kinds_by_name["pkg.mod.f"])

        sigs = {e["fqname"]: e["signature"] for e in idx["entities"]}
        self.assertEqual("m(self, x)", sigs["pkg.mod.A.m"])
        self.assertEqual("f(a, *args, **kwargs)", sigs["pkg.mod.f"])

        rels = {(r["src"], r["rel"], r["dst"]) for r in idx["relations"]}
        self.assertIn(("pkg.mod", "imports", "os"), rels)
        self.assertIn(("pkg.mod", "imports", "math"), rels)
        self.assertIn(("pkg.mod", "defines", "pkg.mod.A"), rels)
        self.assertIn(("pkg.mod", "defines", "pkg.mod.A.m"), rels)
        self.assertIn(("pkg.mod", "defines", "pkg.mod.f"), rels)

    def test_build_index_skips_syntax_error_files(self) -> None:
        """Files with syntax errors should be skipped without producing output rows."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bad = root / "bad.py"
            bad.write_text("def x(:\n    pass\n", encoding="utf-8")
            idx = build_index(root)
        self.assertEqual([], idx["entities"])
        self.assertEqual([], idx["relations"])


if __name__ == "__main__":
    unittest.main()
