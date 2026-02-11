from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from context6.core.summarize import write_summary_cur
from context6.db.sqlite import init_db


class TestCodeTruncatedColumn(unittest.TestCase):
    """Tests for the `code_truncated` schema and summary write path."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test.sqlite3"
        init_db(self.db_path)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _insert_entity(self, con: sqlite3.Connection) -> int:
        cur = con.execute(
            """
            INSERT INTO entities (
                kind, fqname, file, start_line, end_line, signature, docstring, summary, code_hash
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "function",
                "pkg.mod.fn",
                "pkg/mod.py",
                1,
                5,
                "def fn(): ...",
                "",
                "",
                "abc123",
            ),
        )
        return int(cur.lastrowid)

    def test_entities_schema_uses_code_truncated(self) -> None:
        """Schema should include `code_truncated` and exclude legacy `summary_truncated`."""
        con = sqlite3.connect(str(self.db_path))
        try:
            cols = {
                row[1]
                for row in con.execute("PRAGMA table_info(entities)").fetchall()
            }
        finally:
            con.close()

        self.assertIn("code_truncated", cols)
        self.assertIn("summary_backend", cols)
        self.assertNotIn("summary_truncated", cols)

    def test_write_summary_cur_updates_code_truncated(self) -> None:
        """`write_summary_cur` should persist truncation and summary metadata fields."""
        con = sqlite3.connect(str(self.db_path))
        try:
            entity_id = self._insert_entity(con)

            write_summary_cur(
                con=con,
                entity_id=entity_id,
                summary="summary text",
                code_hash="abc123",
                was_truncated=True,
                approx_tokens=321,
                coverage="full",
                summary_backend="codex",
            )
            con.commit()

            row = con.execute(
                """
                SELECT summary, summary_hash, code_truncated, summary_prompt_tokens, summary_coverage, summary_backend
                FROM entities
                WHERE id=?
                """,
                (entity_id,),
            ).fetchone()
        finally:
            con.close()

        assert row is not None
        self.assertEqual("summary text", row[0])
        self.assertEqual("abc123", row[1])
        self.assertEqual(1, row[2])
        self.assertEqual(321, row[3])
        self.assertEqual("full", row[4])
        self.assertEqual("codex", row[5])


if __name__ == "__main__":
    unittest.main()
