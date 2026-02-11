from __future__ import annotations
import ast
import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


def _read(p: Path) -> str:
    """
    Read the contents of a file.

    :param p: Path to the file
    :type p: Path
    :return: Contents of the file
    :rtype: str
    """
    return p.read_text(encoding="utf-8", errors="replace")


def _hash(s: str) -> str:
    """
    Hash a string using SHA-256.

    :param s: String to hash
    :type s: str
    :return: Hexadecimal hash of the string
    :rtype: str
    """
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """
    Get the signature of a function definition.

    :param node: AST node representing a function definition
    :type node: ast.FunctionDef | ast.AsyncFunctionDef
    :return: String representation of the function signature
    :rtype: str
    """
    args = []
    for a in node.args.args:
        args.append(a.arg)
    if node.args.vararg:
        args.append("*" + node.args.vararg.arg)
    for a in node.args.kwonlyargs:
        args.append(a.arg)
    if node.args.kwarg:
        args.append("**" + node.args.kwarg.arg)
    return f"{node.name}({', '.join(args)})"


def _get_doc(node: ast.AST) -> str:
    """
    Get the docstring of an AST node.

    :param node: AST node to get the docstring from
    :type node: ast.AST
    :return: Docstring of the node, or empty string if none
    :rtype: str
    """
    return ast.get_docstring(node) or ""

def build_index(root: Path) -> dict[str, Any]:
    """
    Build an index of symbols from the source code in the given directory.

    :param root: Path to the source code directory
    :type root: Path
    :return: Dictionary mapping symbol names to their metadata
    :rtype: dict[str, Any]
    """
    root = root.resolve()
    entities: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []

    for p in root.rglob("*.py"):
        if any(part in {"venv", "env", "__pycache__", ".mypy_cache", ".pytest_cache", ".git", ".idea", ".", "build"} for part in p.parts):
            continue
        rel = p.relative_to(root).as_posix()
        src = _read(p)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        mod_name = rel[:-3].replace("/", ".") # path -> module-ish
        mod_doc = _get_doc(tree)
        mod_hash = _hash(src)

        # Module entity
        entities.append({
            "kind": "module",
            "fqname": mod_name,
            "file": rel,
            "start_line": 1,
            "end_line": len(src.splitlines()),
            "signature": "",
            "docstring": mod_doc,
            "code_hash": mod_hash,
        })

        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                start = getattr(node, "lineno", 1)
                end = getattr(node, "end_lineno", start)
                fq = f"{mod_name}.{node.name}"
                entities.append({
                    "kind": "class",
                    "fqname": fq,
                    "file": rel,
                    "start_line": start,
                    "end_line": end,
                    "signature": f"class {node.name}",
                    "docstring": _get_doc(node),
                    "code_hash": _hash(ast.get_source_segment(src, node) or ""),
                })
                relations.append({
                    "src": mod_name,
                    "rel": "defines",
                    "dst": fq,
                })

                # Handle methods
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        s2tart = getattr(sub, "lineno", start)
                        e2nd = getattr(sub, "end_lineno", s2tart)
                        fq2 = f"{fq}.{sub.name}"
                        entities.append({
                            "kind": "method",
                            "fqname": fq2,
                            "file": rel,
                            "start_line": s2tart,
                            "end_line": e2nd,
                            "signature": _signature(sub),
                            "docstring": _get_doc(sub),
                            "code_hash": _hash(ast.get_source_segment(src, sub) or ""),
                        })
                        relations.append({
                            "src": mod_name,
                            "rel": "defines",
                            "dst": fq2,
                        })
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = getattr(node, "lineno", 1)
                end = getattr(node, "end_lineno", start)
                fq = f"{mod_name}.{node.name}"
                entities.append({
                    "kind": "function",
                    "fqname": fq,
                    "file": rel,
                    "start_line": start,
                    "end_line": end,
                    "signature": _signature(node),
                    "docstring": _get_doc(node),
                    "code_hash": _hash(ast.get_source_segment(src, node) or ""),
                })
                relations.append({
                    "src": mod_name,
                    "rel": "defines",
                    "dst": fq,
                })

        # Imports (simple)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    relations.append({"src": mod_name, "rel": "imports", "dst": alias.name})
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    relations.append({"src": mod_name, "rel": "imports", "dst": node.module})

    return {"root": str(root), "entities": entities, "relations": relations}
