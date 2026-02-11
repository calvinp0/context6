"""
Write full snippet into a temp file
Shells out to codex and captures the output
Returns the result as a dict shaped
{
    "summary": str,
    "was_truncated": bool,
    "approx_tokens": int,
    "coverage": "full" | "partial" | "unclear",
}
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _require_codex(codex_bin: str) -> str:
    """
    Ensure the Codex binary is available and return its path.
    
    :param codex_bin: Name or path of the Codex binary
    :type codex_bin: str
    :return: Resolved path to the Codex binary
    :rtype: str
    """

    resolved = shutil.which(codex_bin)
    if not resolved:
        raise RuntimeError(f"codex binary not found: {codex_bin}")
    return resolved


def summmarize_entity_codex(kind: str, fqname: str, signature: str, docstring: str, code: str, codex_bin: str = "codex", timeout_s: int = 180) -> dict[str, Any]:
    """
    Summarize a code entity using the Codex binary.

    :param kind: The kind of the entity (e.g., "class", "function")
    :type kind: str
    :param fqname: The fully qualified name of the entity
    :type fqname: str
    :param signature: The signature of the entity (e.g., function parameters)
    :type signature: str
    :param docstring: The docstring of the entity
    :type docstring: str
    :param code: The code snippet of the entity
    :type code: str
    :param codex_bin: The name or path of the Codex binary to use (default: "codex")
    :type codex_bin: str
    :param timeout_s: Timeout in seconds for the Codex execution (default: 180)
    :type timeout_s: int
    :return: A dictionary containing the summary, truncation status, approximate token count, and coverage level
    :rtype: dict[str, Any]
    """

    codex_bin = _require_codex(codex_bin)

    template = (
        "Produce a 12-lines-or-less structured summary with these headings:\n"
        "1) Purpose:\n"
        "2) Responsibilities:\n"
        "3) Inputs/Outputs:\n"
        "4) Side effects:\n"
        "5) Error modes:\n"
        "6) Key methods/flows:\n"
        "7) Extension points:\n"
        "8) Related concepts:\n"
        "(Skip headings that are not applicable, but still stay <=12 lines.)\n"
        "Last line MUST be: Coverage: full|partial|unclear\n"
        "Coverage should be 'full' if the file content is complete.\n"
    )

    payload_text = (
        f"ENTITY\nkind: {kind}\n"
        f"fqname: {fqname}\n"
        f"signature: {signature}\n\n"
        f"DOCSTRING (may be empty)\n{docstring}\n\n"
        f"CODE\n{code}\n"
    )

    with tempfile.TemporaryDirectory(prefix="context6_codex_") as td:
        p = Path(td) / "entity.txt"
        p.write_text(payload_text, encoding="utf-8", errors="replace")

        prompt = (
            f"Read the file at: {p.as_posix()}\n\n"
            f"{template}"
        )
        out_path = Path(td) / "out.txt"
        proc = subprocess.run(
            [
                codex_bin, "exec",
                "--skip-git-repo-check",
                "--color", "never",
                "--output-last-message", str(out_path),
                "-",  # read prompt from stdin
            ],
            input=prompt,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
        )

        if proc.returncode != 0:
            raise RuntimeError(f"codex failed with code {proc.returncode}: {proc.stderr}")
        
        text = (proc.stdout or "").strip()
        if not text:
            raise RuntimeError("codex returned empty output")
        
        prompt_chars = len(payload_text) + len(template)
        approx_tokens = prompt_chars // 4

        return {
            "summary": text,
            "was_truncated": False,  # codex doesn't have a built-in truncation
            "approx_tokens": approx_tokens,
            "coverage": "full" if "Coverage:" in text else "unclear",
        }

