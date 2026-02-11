# context6

Local code context indexer and retriever with:
- A CLI for indexing/search/lookup/snippets/summarization
- A FastMCP server exposing those capabilities as MCP tools

## Attribution

This project is inspired by Context7.  
Credit to the Context7 project and contributors for the original concept and direction.

## What It Does

`context6` scans a Python codebase, stores entities in SQLite, and lets you:
- Find symbols by name (`lookup`)
- Search by text (`search`)
- Pull exact source snippets (`snippet`)
- Generate compact summaries (`summarize`)
- Evaluate recall against qrels (`eval-recall`)

## Prerequisites

- Python 3.10+
- `pip` (or another Python package installer)

Optional (only needed for summarization modes):
- Ollama running locally for `ollama`/`auto` mode
- OpenAI Codex CLI binary for `codex` mode fallback/direct use

## Install

From repo root:

```bash
python -m pip install -e .
```

This installs the package and the `context6` CLI entrypoint from `pyproject.toml`.
If your shell cannot find `context6`, use module form: `python -m context6.cli ...`.

## Quick Start

1) Build an index for a source tree:

```bash
python -m context6.cli index --source /path/to/your/python/project --out ./arc
```

This creates `./arc/context6.db`.

2) Search for relevant entities:

```bash
python -m context6.cli search --db ./arc/context6.db "database connection pooling"
```

3) Lookup by symbol:

```bash
python -m context6.cli lookup --db ./arc/context6.db --source /path/to/your/python/project MyClass
```

4) Get a snippet:

```bash
python -m context6.cli snippet --db ./arc/context6.db mypkg.module.MyClass.method_name
```

## CLI Commands

Show all commands:

```bash
python -m context6.cli --help
```

Available subcommands:
- `index`: build an index and ingest into SQLite
- `lookup`: find best symbol match
- `search`: FTS search over fqname/signature/docstring/summary
- `snippet`: retrieve source text for a fully-qualified name
- `summarize`: fill missing summaries for indexed entities
- `eval-recall`: evaluate retrieval against qrels data

### Useful examples

Filter by kinds:

```bash
python -m context6.cli search --db ./arc/context6.db "ARC execute" --kinds class,method
```

Run summarization:

```bash
python -m context6.cli summarize --db ./arc/context6.db --limit 100 --summarizer auto
```

Evaluate recall:

```bash
python -m context6.cli eval-recall --db ./arc/context6.db --qrels ./qrels.json --k 10 --retriever search
```

## Environment Variables

These are used by CLI and/or MCP tools:

- `CONTEXT6_SOURCE_ROOT`: source root used when loading snippets
- `CONTEXT6_DB`: default DB path for MCP server (default: `~/code/context6/arc/context6.db`)
- `CONTEXT6_SUMMARIZER`: `auto`, `ollama`, or `codex` for MCP summarize tool
- `CONTEXT6_CODEX_BIN`: path/name for codex binary (default: `codex`)
- `CONTEXT6_MODEL`: Ollama model (default: `qwen2.5:7b`)
- `OLLAMA_HOST`: Ollama endpoint (default: `http://localhost:11434`)
- `CONTEXT6_NUM_CTX`: Ollama context size override (default: `6144`)

## Running as an MCP Server

Run the server over stdio:

```bash
python -m context6.mcp.context6_server
```

Before launching, set at least:

```bash
export CONTEXT6_DB=/absolute/path/to/context6.db
export CONTEXT6_SOURCE_ROOT=/absolute/path/to/source/root
```

The server exposes tools including:
- `context6_health`
- `context6_lookup`
- `context6_search`
- `context6_snippet`
- `context6_pretty_lookup`
- `context6_summarize_entity`
- `context6_resolve`

## Development

Run tests:

```bash
python -m pytest -q
```
