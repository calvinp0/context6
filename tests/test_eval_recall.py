from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from context6.core.eval import evaluate_recall_at_k
from context6.db.sqlite import ingest_index, init_db


class TestEvalRecall(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tmpdir.name)
        self.db = self.root / "context6.db"
        init_db(self.db)
        ingest_index(
            self.db,
            {
                "root": str(self.root),
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
                        "start_line": 3,
                        "end_line": 5,
                        "signature": "class C",
                        "docstring": "",
                        "summary": "container object",
                        "code_hash": "h2",
                    },
                ],
                "relations": [],
            },
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_recall_at_k_search(self) -> None:
        qrels = [
            {"query": "adds", "relevant": ["pkg.mod.fn"]},
            {"query": "container", "relevant": ["pkg.mod.C"]},
        ]
        out = evaluate_recall_at_k(self.db, qrels, k=1, retriever="search", kinds=["class", "function"])
        self.assertEqual(2, out["num_queries"])
        self.assertAlmostEqual(1.0, out["recall_at_k"])
        self.assertAlmostEqual(1.0, out["hit_rate_at_k"])

    def test_recall_at_k_lookup_partial(self) -> None:
        qrels = [{"query": "mod", "relevant": ["pkg.mod.fn", "pkg.mod.C"]}]
        out = evaluate_recall_at_k(self.db, qrels, k=1, retriever="lookup", kinds=["class", "function"])
        self.assertEqual(1, out["num_queries"])
        self.assertAlmostEqual(0.5, out["recall_at_k"])
        self.assertAlmostEqual(1.0, out["hit_rate_at_k"])

    def test_recall_at_k_defaults_to_class(self) -> None:
        qrels = [{"query": "adds", "relevant": ["pkg.mod.fn"]}]
        out = evaluate_recall_at_k(self.db, qrels, k=1, retriever="search")
        self.assertEqual(["class"], out["kinds"])
        self.assertAlmostEqual(0.0, out["recall_at_k"])
        self.assertTrue(out["warnings"])
        self.assertEqual("pkg.mod.fn", out["details"][0]["excluded_relevant_by_kinds"][0]["fqname"])

    def test_qrels_supports_relevant_object_with_kind(self) -> None:
        qrels = [
            {
                "query": "container",
                "relevant": [{"fqname": "pkg.mod.C", "kind": "class"}],
            }
        ]
        out = evaluate_recall_at_k(self.db, qrels, k=1, retriever="search", kinds=["class"])
        self.assertAlmostEqual(1.0, out["recall_at_k"])
        self.assertEqual([], out["warnings"])

    def test_recall_uses_eligible_relevant_only(self) -> None:
        qrels = [
            {
                "query": "container",
                "relevant": [
                    {"fqname": "pkg.mod.C", "kind": "class"},
                    {"fqname": "pkg.mod.fn", "kind": "function"},
                ],
            }
        ]
        out = evaluate_recall_at_k(self.db, qrels, k=1, retriever="search", kinds=["class"])
        self.assertEqual(2, out["details"][0]["relevant_count"])
        self.assertEqual(1, out["details"][0]["eligible_relevant_count"])
        self.assertEqual(1, out["details"][0]["eligible_matched_count"])
        self.assertAlmostEqual(1.0, out["recall_at_k"])
        self.assertTrue(out["warnings"])


if __name__ == "__main__":
    unittest.main()
