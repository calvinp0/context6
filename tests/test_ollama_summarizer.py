from __future__ import annotations

import unittest
from unittest.mock import patch

from context6.core import ollama_summarizer as s


class TestOllamaSummarizer(unittest.TestCase):
    """Tests for summarizer post-processing around coverage and truncation."""

    def test_summarize_entity_sets_full_coverage_when_not_truncated(self) -> None:
        """When code is not truncated, final coverage should be forced to `full`."""
        with patch.object(s, "_post_json", return_value={"response": "Purpose: test"}):
            out = s.summarize_entity(
                kind="function",
                fqname="pkg.f",
                signature="f()",
                docstring="",
                code="def f():\n    return 1\n",
                stream=False,
            )
        self.assertIn("Purpose: test", out["summary"])
        self.assertTrue(out["summary"].splitlines()[-1].startswith("Coverage:"))
        self.assertEqual("full", out["coverage"])
        self.assertEqual("Coverage: full", out["summary"].splitlines()[-1])

    def test_summarize_entity_forces_partial_on_truncation(self) -> None:
        """When code is truncated, final coverage should be forced to `partial`."""
        code = "x" * 3000
        with patch.object(s, "BUDGET_CHARS", 2200), patch.object(
            s, "_post_json", return_value={"response": "Purpose: test\nCoverage: full"}
        ):
            out = s.summarize_entity(
                kind="function",
                fqname="pkg.f",
                signature="f()",
                docstring="",
                code=code,
                stream=False,
            )
        self.assertTrue(out["was_truncated"])
        self.assertEqual("partial", out["coverage"])
        self.assertEqual("Coverage: partial", out["summary"].splitlines()[-1])


if __name__ == "__main__":
    unittest.main()
