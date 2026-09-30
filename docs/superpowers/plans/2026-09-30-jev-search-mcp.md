# jev-search-mcp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a public, installable stdio MCP server that exposes the pinned `jev-search` CLI as one tool, with bilingual README and a detailed Russian guide.

**Architecture:** Single module `jev_search_mcp.py` built on the official MCP Python SDK v2 (`MCPServer`). The one tool shells out to `[sys.executable, "-m", "jev_search", ...]` (pinned git dependency in the same venv) and trims its JSON. All file checks, limits and validation stay in the CLI.

**Tech Stack:** Python ≥3.11, `mcp>=2.2,<2.3` (verified API: `from mcp.server import MCPServer`, `from mcp.server.mcpserver.exceptions import ToolError`, `mcp.run()`, test client `from mcp import Client, StdioServerParameters`, `Client(mcp)` in-memory, `client.instructions`, `result.is_error`, `result.content[i].text`), setuptools, stdlib `unittest`, uv.

**Spec:** `docs/superpowers/specs/2026-09-30-jev-search-mcp-design.md`

## Global Constraints

- Repo root: `D:\Dev\jev-search-mcp` (git, branch `main`). Public GitHub: `https://github.com/Vento741/jev-search-mcp`.
- Upstream pin: `jev-search @ git+https://github.com/larguesa/jev-search@8aa403554d7904d3c14224cfda02a4e2144c0ccd`.
- `mcp>=2.2,<2.3`; `requires-python = ">=3.11"`; no other runtime dependencies (pydantic comes with mcp).
- Must work on Windows and Linux.
- Never pass the key in argv, never print it, never include it in output or errors. Tests must never make a paid call: every test removes `JEV_SEARCH_API_KEY` from the environment it runs the CLI in (the dev machine HAS a real key set).
- Tool name `jev_search`; server name `jev-search`; console script `jev-search-mcp`.
- Commit identity: `git -c user.name=Vento741 -c user.email=vento741@mail.ru commit ...`; every commit message ends with a blank line and `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Dev commands (uv is invoked as `python -m uv` on this machine): `python -m uv sync` then `python -m uv run python -m unittest discover -s tests -v`. Commit `uv.lock`.
- The CLI is always spawned as `[sys.executable, "-I", "-m", "jev_search", ...]` (`-I` prevents a `jev_search.py` in the working directory from shadowing the pinned CLI - reproduced by review).
- `files` must be absolute paths; the tool rejects relative ones before spawning.

## Review Focus

- A `jev_search.py` in the client's project directory must not be executed instead of the pinned CLI -> `-I` flag + regression test with a fake module in cwd (Task 2).

- The MCP stdio channel is the server's stdin/stdout: the CLI child must get `stdin=DEVNULL` and captured stdout, or it can steal/corrupt protocol bytes → test asserts `stdin=subprocess.DEVNULL` (Task 2).
- Claude Desktop on Windows launches without a console: the child must use `CREATE_NO_WINDOW` so no console window flashes → test asserts `creationflags` on Windows (Task 2).
- Queries or paths beginning with `-` (e.g. `-refund`) must not be parsed as CLI flags → `--query=<q>` form and `--` before files; dry-run test with query `-refund` (Task 2).
- A real key present in the developer's environment must never cause a paid call during tests → shared helper strips the key; missing-key test proves the CLI refuses (Task 2).
- CLI failures that are not JSON (argparse error, interpreter crash) must still give a readable, bounded error → `cli_error` fallback test (Task 2).

---

## File map

| File | Responsibility |
|---|---|
| `pyproject.toml` | metadata, deps, console script |
| `jev_search_mcp.py` | `INSTRUCTIONS`, `shape_output`, `cli_error`, `run_cli`, tool `jev_search`, `main` |
| `tests/__init__.py` | empty |
| `tests/fixtures/sample.txt` | 2-line synthetic text |
| `tests/test_shape.py` | pure output-shaping tests |
| `tests/test_server.py` | tool, error, stdio end-to-end tests |
| `.github/workflows/ci.yml` | offline tests on ubuntu + windows |
| `.gitignore`, `LICENSE` | housekeeping |
| `README.md`, `README.ru.md` | bilingual landing |
| `docs/GUIDE.md` | detailed Russian guide |

---

### Task 1: Package skeleton and output shaping

**Files:**
- Create: `pyproject.toml`, `jev_search_mcp.py`, `tests/__init__.py`, `tests/test_shape.py`, `.gitignore`, `LICENSE`

**Interfaces:**
- Produces: `shape_output(data: dict) -> dict` in `jev_search_mcp.py`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"

[project]
name = "jev-search-mcp"
version = "0.1.0"
description = "MCP server for jev-search: complementary semantic line search for AI agents"
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
license-files = ["LICENSE"]
authors = [{name = "Vento741"}]
dependencies = [
  "mcp>=2.2,<2.3",
  "jev-search @ git+https://github.com/larguesa/jev-search@8aa403554d7904d3c14224cfda02a4e2144c0ccd",
]
classifiers = [
  "Development Status :: 3 - Alpha",
  "Operating System :: POSIX :: Linux",
  "Operating System :: Microsoft :: Windows",
  "Programming Language :: Python :: 3",
]

[project.scripts]
jev-search-mcp = "jev_search_mcp:main"

[project.urls]
Repository = "https://github.com/Vento741/jev-search-mcp"
Upstream = "https://github.com/larguesa/jev-search"

[tool.setuptools]
py-modules = ["jev_search_mcp"]
```

Create a placeholder `README.md` containing `# jev-search-mcp` (setuptools needs the file; Task 3 replaces it).

- [ ] **Step 2: Create `.gitignore` and `LICENSE`**

`.gitignore`:
```
.venv/
__pycache__/
*.egg-info/
build/
dist/
.env*
```

`LICENSE`: standard MIT text, `Copyright (c) 2026 Vento741`.

- [ ] **Step 3: Create `tests/__init__.py`** (runs before any test module is imported):

```python
import os

# The developer machine has a real key and may have provider settings: no test may
# ever reach a paid provider or depend on local JEV_SEARCH_* configuration.
for _name in [k for k in os.environ if k.startswith("JEV_SEARCH_")]:
    del os.environ[_name]
```

Then write failing tests `tests/test_shape.py`:

```python
import unittest
from jev_search_mcp import shape_output

ROWS = [{"file": "/x/a.txt", "line": 1, "original": "Hello"}]


class ShapeOutput(unittest.TestCase):
    def test_dry_run_drops_request_and_reports_openrouter(self):
        data = {"mode": "dry-run", "requests": 1, "payload_bytes": 10, "rows": ROWS,
                "request": {"model": "typesafe/jev-1.13", "provider": {"only": ["typesafe"]}},
                "unjudged": {"reason": "dry-run", "candidates": ["l0"]}}
        out = shape_output(data)
        self.assertNotIn("request", out)
        self.assertEqual(out["rows"], ROWS)
        self.assertEqual(out["model"], "typesafe/jev-1.13")
        self.assertEqual(out["provider"], "openrouter")
        self.assertEqual(out["unjudged"], data["unjudged"])

    def test_dry_run_without_provider_block_is_typesafe(self):
        out = shape_output({"mode": "dry-run", "rows": ROWS, "request": {"model": "jev-1.13.0"}})
        self.assertEqual(out["provider"], "typesafe")

    def test_sent_moves_raw_response_into_meta(self):
        results = [dict(ROWS[0], probability=0.9, match=True)]
        data = {"mode": "sent", "latency_seconds": 0.5, "results": results,
                "ranked_results": results,
                "raw_response": {"id": "gen-1", "model": "typesafe/jev-1.13-20260917",
                                 "answers": {"l0": {}},
                                 "usage": {"cost": 1.9e-05, "input_tokens": 10, "output_tokens": 2}}}
        out = shape_output(data)
        self.assertNotIn("raw_response", out)
        self.assertEqual(out["results"], results)
        self.assertEqual(out["ranked_results"], results)
        self.assertEqual(out["meta"], {"model": "typesafe/jev-1.13-20260917", "generation_id": "gen-1",
                                       "cost": 1.9e-05, "input_tokens": 10, "output_tokens": 2})

    def test_missing_cost_is_null_not_zero(self):
        out = shape_output({"mode": "sent", "results": [], "raw_response": {"model": "jev-1.13.0", "answers": {}}})
        self.assertIsNone(out["meta"]["cost"])
        self.assertIsNone(out["meta"]["generation_id"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 4: Run — expect failure**

Run: `python -m uv sync && python -m uv run python -m unittest discover -s tests -v`
Expected: ImportError / cannot import `shape_output`.

- [ ] **Step 5: Implement minimal `jev_search_mcp.py`**

```python
"""Stdio MCP server exposing the jev-search CLI as one tool."""
from typing import Any


def shape_output(data: dict) -> dict:
    """Drop bulky duplicates from CLI JSON; keep results and provenance unchanged."""
    if data.get("mode") == "dry-run":
        request = data.get("request") or {}
        out = {k: v for k, v in data.items() if k != "request"}
        out["model"] = request.get("model")
        # The CLI sends a routing block only on the OpenRouter route.
        out["provider"] = "openrouter" if "provider" in request else "typesafe"
        return out
    raw = data.get("raw_response") or {}
    usage = raw.get("usage") or {}
    out = {k: v for k, v in data.items() if k != "raw_response"}
    out["meta"] = {"model": raw.get("model"), "generation_id": raw.get("id"), "cost": usage.get("cost"),
                   "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens")}
    return out
```

- [ ] **Step 6: Run — expect 4 passing tests.**

- [ ] **Step 7: Commit** — `git add -A && git commit -m "feat: package skeleton and CLI output shaping"`.

---

### Task 2: CLI runner, MCP tool, server entry point, CI

**Files:**
- Modify: `jev_search_mcp.py`
- Create: `tests/test_server.py`, `tests/fixtures/sample.txt`, `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `shape_output(data: dict) -> dict`.
- Produces: `INSTRUCTIONS: str`, `mcp: MCPServer`, `cli_error(stderr: bytes) -> str`, `run_cli(args: list[str]) -> dict`, tool `jev_search(query: str, files: list[str], top_k: int | None = None, dry_run: bool = False) -> dict[str, Any]`, `main() -> None` (supports `--version`).

- [ ] **Step 1: Fixture** `tests/fixtures/sample.txt` (LF endings):
```
Hello, nice to meet you.
The invoice is due Friday.
```

- [ ] **Step 2: Failing tests `tests/test_server.py`**

```python
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import anyio
from mcp import Client, StdioServerParameters

import jev_search_mcp
from jev_search_mcp import cli_error, mcp, run_cli
from mcp.server.mcpserver.exceptions import ToolError

FIXTURE = str(Path(__file__).parent / "fixtures" / "sample.txt")
KEYLESS_ENV = {k: v for k, v in os.environ.items() if not k.startswith("JEV_SEARCH_")}  # tests/__init__ already stripped them


def call(name, args):
    async def go():
        async with Client(mcp) as client:
            return await client.call_tool(name, args)
    return anyio.run(go)


class ToolBehaviour(unittest.TestCase):
    def setUp(self):
        self.assertNotIn("JEV_SEARCH_API_KEY", os.environ)  # guard: never a paid call

    def test_dry_run_returns_rows_without_request(self):
        result = call("jev_search", {"query": "greeting", "files": [FIXTURE], "dry_run": True})
        self.assertFalse(result.is_error)
        out = json.loads(result.content[0].text)
        self.assertEqual(out["mode"], "dry-run")
        self.assertNotIn("request", out)
        self.assertEqual([r["original"] for r in out["rows"]], ["Hello, nice to meet you.", "The invoice is due Friday."])
        self.assertEqual(out["provider"], "openrouter")

    def test_query_starting_with_dash_is_not_a_flag(self):
        result = call("jev_search", {"query": "-refund", "files": [FIXTURE], "dry_run": True})
        self.assertFalse(result.is_error, result.content[0].text)

    def test_disallowed_file_type_is_tool_error(self):
        result = call("jev_search", {"query": "greeting", "files": [__file__], "dry_run": True})
        self.assertTrue(result.is_error)
        self.assertIn("disallowed filename", result.content[0].text)

    def test_missing_key_refuses_without_network(self):
        result = call("jev_search", {"query": "greeting", "files": [FIXTURE]})
        self.assertTrue(result.is_error)
        self.assertIn("JEV_SEARCH_API_KEY", result.content[0].text)

    def test_schema_bounds_are_enforced_by_the_server(self):
        for args in ({"query": "q", "files": [], "dry_run": True},
                     {"query": "q", "files": [FIXTURE], "top_k": 65, "dry_run": True}):
            result = call("jev_search", args)
            self.assertTrue(result.is_error)
            self.assertIn("validation error", result.content[0].text)

    def test_schema_and_annotations_are_published(self):
        async def go():
            async with Client(mcp) as client:
                return (await client.list_tools()).tools[0]
        tool = anyio.run(go)
        props = tool.input_schema["properties"]
        self.assertEqual((props["files"]["minItems"], props["files"]["maxItems"]), (1, 8))
        self.assertIn({"maximum": 64, "minimum": 1, "type": "integer"}, props["top_k"]["anyOf"])
        self.assertTrue(tool.annotations.read_only_hint)
        self.assertTrue(tool.annotations.open_world_hint)

    def test_relative_path_is_rejected(self):
        result = call("jev_search", {"query": "greeting", "files": ["sample.txt"], "dry_run": True})
        self.assertTrue(result.is_error)
        self.assertIn("absolute", result.content[0].text)

    def test_nul_byte_in_query_is_clear_error(self):
        result = call("jev_search", {"query": "a\x00b", "files": [FIXTURE], "dry_run": True})
        self.assertTrue(result.is_error)
        self.assertIn("invalid input or output", result.content[0].text)


class RunnerDetails(unittest.TestCase):
    def fake(self, returncode=0, stdout=b"{}", stderr=b""):
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)

    def test_child_gets_devnull_stdin_and_no_window(self):
        with mock.patch.object(jev_search_mcp.subprocess, "run", return_value=self.fake()) as run:
            run_cli(["--dry-run"])
        kwargs = run.call_args.kwargs
        self.assertEqual(run.call_args.args[0][:4], [sys.executable, "-I", "-m", "jev_search"])
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertTrue(kwargs["capture_output"])
        self.assertEqual(kwargs["timeout"], jev_search_mcp.TIMEOUT)
        if os.name == "nt":
            self.assertEqual(kwargs["creationflags"], subprocess.CREATE_NO_WINDOW)

    def test_cli_in_working_directory_cannot_shadow_pinned_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "jev_search.py").write_text('print(\'{"mode": "HIJACKED"}\')\n', encoding="utf8")
            old = os.getcwd()
            os.chdir(tmp)
            try:
                out = run_cli(["--query=greeting", "--dry-run", "--", FIXTURE])
            finally:
                os.chdir(old)
        self.assertEqual(out["mode"], "dry-run")

    def test_timeout_becomes_tool_error(self):
        with mock.patch.object(jev_search_mcp.subprocess, "run", side_effect=subprocess.TimeoutExpired("x", 330)):
            with self.assertRaisesRegex(ToolError, "timed out; not retried"):
                run_cli(["--dry-run"])

    def test_json_error_is_extracted(self):
        self.assertEqual(cli_error(b'{"error": "line limit exceeded", "unjudged": {}}\n'), "line limit exceeded")

    def test_non_json_error_is_bounded(self):
        msg = cli_error(b"error: invalid arguments; use --help for usage\n" + b"x" * 2000)
        self.assertTrue(msg.startswith("jev-search failed: error: invalid arguments"))
        self.assertLessEqual(len(msg), len("jev-search failed: ") + 500)

    def test_nonzero_exit_raises_cli_message(self):
        with mock.patch.object(jev_search_mcp.subprocess, "run",
                               return_value=self.fake(1, b"", b'{"error": "possible secret rejected"}')):
            with self.assertRaisesRegex(ToolError, "possible secret rejected"):
                run_cli(["--dry-run"])


class StdioEndToEnd(unittest.TestCase):
    def test_real_stdio_session(self):
        params = StdioServerParameters(command=sys.executable, args=["-m", "jev_search_mcp"], env=KEYLESS_ENV)

        async def go():
            with anyio.fail_after(60):  # a hang on Windows CI must fail, not block
                async with Client(params) as client:
                    tools = await client.list_tools()
                    result = await client.call_tool("jev_search", {"query": "greeting", "files": [FIXTURE], "dry_run": True})
                    return client.instructions, [t.name for t in tools.tools], result
        instructions, names, result = anyio.run(go)
        self.assertEqual(names, ["jev_search"])
        self.assertIn("complement", instructions)
        self.assertFalse(result.is_error, result.content[0].text)
        self.assertEqual(json.loads(result.content[0].text)["mode"], "dry-run")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run — expect ImportError on `cli_error`/`mcp`/`run_cli`.**

- [ ] **Step 4: Implement** — replace `jev_search_mcp.py` with:

```python
"""Stdio MCP server exposing the jev-search CLI as one tool."""
import json
import os
import subprocess
import sys
from importlib.metadata import version
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

TIMEOUT = 330  # the CLI's own socket timeout is 300 s

INSTRUCTIONS = """jev-search is complementary semantic line search: it judges whether each line
expresses an intent, even in different words. Use it alongside exact/lexical search,
never instead of it.
- First orient with filenames, links and exact search; then pass 1-8 small, relevant
  UTF-8 .txt/.md/.csv/.jsonl/.log files by ABSOLUTE path (<=16 KB and <=64 lines
  combined; no directories or globs). For bigger files, search a reviewed excerpt.
- Merge its matches with lexical hits and read the original context before answering.
  Cite files and lines, not scores; scores are not calibrated probabilities.
- Every selected nonblank line and the query are sent to the inference provider
  (OpenRouter/TypeSafe). Only send content the user has authorized.
- Real searches cost money (fractions of a cent each). dry_run=true is free and offline.
  Ask the user before bulk or repeated large searches."""

mcp = MCPServer("jev-search", instructions=INSTRUCTIONS, version=version("jev-search-mcp"))


def shape_output(data: dict) -> dict:
    ...  # unchanged from Task 1


def cli_error(stderr: bytes) -> str:
    """The CLI prints {"error": ...} JSON on failure; anything else is shown bounded."""
    text = stderr.decode("utf-8", "replace").strip()
    try:
        return json.loads(text.splitlines()[-1])["error"]
    except (ValueError, KeyError, IndexError, TypeError):
        return "jev-search failed: " + text[:500]


def run_cli(args: list[str]) -> dict:
    """Run the pinned CLI from this environment; the key is inherited, never passed."""
    try:
        proc = subprocess.run(
            # -I: never import a jev_search.py from the working directory or PYTHONPATH.
            [sys.executable, "-I", "-m", "jev_search", *args],
            stdin=subprocess.DEVNULL,  # stdin is the MCP channel
            capture_output=True,
            timeout=TIMEOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except subprocess.TimeoutExpired:
        raise ToolError("jev-search timed out; not retried; a charge may have occurred") from None
    except ValueError as e:  # e.g. NUL byte in an argument
        raise ToolError(f"jev-search: invalid input or output ({type(e).__name__})") from None
    if proc.returncode != 0:
        raise ToolError(cli_error(proc.stderr))
    try:
        return json.loads(proc.stdout)
    except ValueError as e:
        raise ToolError(f"jev-search: invalid input or output ({type(e).__name__})") from None


@mcp.tool(annotations=ToolAnnotations(title="Semantic line search", readOnlyHint=True,
                                      destructiveHint=False, openWorldHint=True))
def jev_search(
    query: Annotated[str, Field(description="The intent to find, in natural language (<=512 bytes).")],
    files: Annotated[list[str], Field(min_length=1, max_length=8,
                                      description="1-8 ABSOLUTE paths to UTF-8 .txt/.md/.csv/.jsonl/.log files "
                                                  "(no directories or globs); <=16 KB and <=64 lines combined.")],
    top_k: Annotated[int | None, Field(ge=1, le=64,
                                       description="Also return up to k matches sorted by score (ranked_results).")] = None,
    dry_run: Annotated[bool, Field(description="Free offline preview of what would be sent; no key, no network.")] = False,
) -> dict[str, Any]:
    """Complementary semantic search over lines of small text files.

    Returns every nonblank line with probability and match (>=0.5), plus source file and
    1-based line. All selected lines leave the machine; a real search costs money.
    """
    if not all(os.path.isabs(f) for f in files):
        raise ToolError("files must be absolute paths (the server's working directory is arbitrary)")
    args = [f"--query={query}"]
    if dry_run:
        args.append("--dry-run")
    if top_k is not None:
        args += ["--top-k", str(top_k)]
    return shape_output(run_cli([*args, "--", *files]))


def main() -> None:
    if sys.argv[1:] == ["--version"]:
        print(version("jev-search-mcp"))
        return
    mcp.run()


if __name__ == "__main__":
    main()
```

(Keep the full `shape_output` body from Task 1 — do not leave `...`.)

- [ ] **Step 5: Run all tests — expect all pass** (`python -m uv run python -m unittest discover -s tests -v`). If `test_real_stdio_session` hangs, check the server writes nothing to stdout besides the protocol.

- [ ] **Step 6: Smoke `--version`**: `python -m uv run jev-search-mcp --version` → `0.1.0`.

- [ ] **Step 7: CI `.github/workflows/ci.yml`**

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        python: ["3.11", "3.13"]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --locked --python ${{ matrix.python }}
      - run: uv run python -m unittest discover -s tests -v
      - run: uv run jev-search-mcp --version
```

- [ ] **Step 8: Commit** — `feat: jev_search MCP tool over the pinned CLI`.

---

### Task 3: README.md (English) and README.ru.md (Russian)

**Files:** Replace `README.md`; create `README.ru.md`.

**Interfaces:** Consumes tool contract from Task 2 (names, params, limits). No code.

Requirements (both files identical in structure; RU is a natural translation, not word-for-word):

- [ ] **Step 1: Header** — centered block: title `jev-search-mcp`, one-line pitch ("Find by meaning what keywords miss — as an MCP tool for your agents."), shields.io badges (License MIT, Python 3.11+, MCP stdio, CI status for `Vento741/jev-search-mcp` workflow `ci.yml`), language switcher `English | [Русский](README.ru.md)` (and mirror in RU).
- [ ] **Step 2: Sections in order**
  1. *What it is* — 3 bullets: complementary semantic line search; runs locally next to your files (stdio); every client that speaks MCP.
  2. *How it works* — a Mermaid `flowchart LR`: Agent → (stdio) jev-search-mcp → jev-search CLI → (HTTPS) OpenRouter → TypeSafe Jev model.
  3. **Quick start** (must fit one messenger message): (1) install uv — Windows `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`, Linux/macOS `curl -LsSf https://astral.sh/uv/install.sh | sh`; (2) create your own OpenRouter key with a spending limit at https://openrouter.ai/settings/keys and set `JEV_SEARCH_API_KEY` (Windows: `[Environment]::SetEnvironmentVariable('JEV_SEARCH_API_KEY', '<key>', 'User')` then fully restart the client; Linux/VPS: add `export JEV_SEARCH_API_KEY=...` to `~/.bashrc` - `~/.profile` alone misses non-login shells); (3) install `uv tool install git+https://github.com/Vento741/jev-search-mcp@v0.1.0` and connect. Put a *Requirements: uv + git* line above the steps.
  4. *Connect your client* - Claude Code: `claude mcp add --scope user jev-search -- jev-search-mcp` (inherits the key from its environment). Claude Desktop: JSON for `claude_desktop_config.json` (`%APPDATA%\Claude\` on Windows, `~/Library/Application Support/Claude/` on macOS) with `"command": "<full path to jev-search-mcp(.exe)>"` (find it with `where jev-search-mcp` / `which jev-search-mcp`) and **`"env": {"JEV_SEARCH_API_KEY": "<your key>"}`** - Desktop does not pass user environment variables; warn that the key is plaintext in that user-private file, never commit or share it. Any MCP client: generic stdio JSON, same `env` rule. Zero-install alternative: `uvx --from git+https://github.com/Vento741/jev-search-mcp@v0.1.0 jev-search-mcp` (slower start, may contact GitHub on each start).
  5. *Tool* — table of `query`, `files`, `top_k`, `dry_run` with rules; example call and trimmed example output (dry-run JSON shape and sent JSON shape with `results` + `meta`).
  6. *Limits* — 1–8 files, extensions, 16 KB/64 lines combined, 2 KB per line, 512-byte query, one request per call, no retries.
  7. *Privacy & cost* — all selected nonblank lines + query go to OpenRouter and TypeSafe; ~$0.00002 for a 2-line search (measured 2026-09-30, varies); use your own key with a provider-side limit; missing cost ≠ free.
  8. *Documentation* — link to `docs/GUIDE.md` (Russian, detailed scenarios).
  9. *Credits & license* — built on [larguesa/jev-search](https://github.com/larguesa/jev-search) (MIT, pinned to commit `8aa4035`), inspired by uehaj/jev-semgrep; this wrapper MIT © 2026 Vento741. Not affiliated with TypeSafe or OpenRouter.
- [ ] **Step 3: Verify** every command/snippet against Task 2 names; check that `claude mcp add` syntax matches `claude mcp add --help` on this machine; no key values anywhere.
- [ ] **Step 4: Commit** — `docs: bilingual README`.

---

### Task 4: docs/GUIDE.md (Russian, detailed)

**Files:** Create `docs/GUIDE.md`.

- [ ] **Step 1: Write sections**
  1. Что это и когда применять (и когда нет: точные имена/символы → grep).
  2. Как устроено и что уходит провайдеру; стоимость.
  3. Требования: `uv` и `git`. Установка: Windows / Linux / VPS (без sudo, uv в `~/.local/bin`); основной путь `uv tool install git+https://github.com/Vento741/jev-search-mcp@v0.1.0`, `uvx` - альтернатива (медленнее старт, может ходить в GitHub при каждом запуске); обновление (`uv tool install --force ...@<новый тег>`), закрепление версии тегом; удаление (`uv tool uninstall jev-search-mcp`).
  4. Ключ: создание в OpenRouter с лимитом расходов. Кто как получает ключ: **Claude Code** наследует окружение - Windows: пользовательская переменная + **полный** перезапуск клиента (главный процесс VS Code, не Reload Window); Linux/VPS: `~/.bashrc` или файл `~/.config/jev-search.env` с `chmod 600`, подключаемый из `~/.bashrc` через `set -a; . ~/.config/jev-search.env; set +a` (`~/.profile` не читается не-login оболочками). **Claude Desktop и другие клиенты на MCP SDK НЕ передают пользовательские переменные** - ключ обязательно в блоке `env` конфига (открытым текстом в личном файле, не коммитить и не пересылать). Свои ключи коллегам не передавать - у каждого свой.
  5. Подключение: Claude Code (user scope vs проектный `.mcp.json` с `"env": {"JEV_SEARCH_API_KEY": "${JEV_SEARCH_API_KEY}"}`), проверка `claude mcp list`; Claude Desktop (пути конфига Windows/macOS, перезапуск); Claude Agent SDK на Python (`ClaudeAgentOptions(mcp_servers={...}, allowed_tools=["mcp__jev-search__jev_search"])` — verify against current Agent SDK docs via context7 before writing); любой MCP-клиент/оркестратор (общий stdio JSON); провайдер TypeSafe через `env` `JEV_SEARCH_PROVIDER=typesafe`.
  6. **Сценарии** (каждый: задача → как выбрать файлы → пример запроса агенту → что ожидать): документация и ADR проекта; заметки Obsidian/second brain; разбор логов на VPS (выборка `tail -n 60` во временный `.log`); тикеты поддержки в CSV; связка grep + смысл (поиск синонимичных формулировок, которых нет в ключевых словах); большой файл → нарезка на проверенные фрагменты с сохранением номеров строк; `dry_run` для проверки перед отправкой конфиденциального.
  7. Готовый блок для `CLAUDE.md`/`AGENTS.md` проекта (5–8 строк правил использования).
  8. Ограничения и справочник ошибок (таблица: текст ошибки CLI → причина → что делать: `disallowed filename`, `symlink rejected`, `total byte limit 16384 exceeded`, `line limit exceeded`, `possible secret rejected`, `set JEV_SEARCH_API_KEY...`, `HTTP 401/402/429; not retried`, `timed out`).
  9. Диагностика: ключ не виден; `uvx` не найден (PATH, полный путь к `uvx`); первый запуск долгий (скачивание — предзагрузить `uvx --from ... jev-search-mcp --version`); таймаут клиента (у многих ~60 с) не отменяет списание; ошибка «files must be absolute paths»; проверка офлайн через `dry_run`.
- [ ] **Step 2: Verify** all commands consistent with README and Task 2; no key values.
- [ ] **Step 3: Commit** — `docs: detailed Russian guide with scenarios`.

---

### Task 5: Publish and verify (controller, not a subagent)

- [ ] Create public repo `Vento741/jev-search-mcp` via GitHub REST `POST /user/repos` using the Git Credential Manager token (passed via stdin header, never printed), description = README pitch, homepage empty, topics later optional.
- [ ] Commit `uv.lock` before pushing.
- [ ] `git remote add origin https://github.com/Vento741/jev-search-mcp.git && git push -u origin main`; verify remote HEAD equals local; wait for CI green on all 4 jobs; then tag `v0.1.0` and push the tag.
- [ ] `python -m uv tool install git+https://github.com/Vento741/jev-search-mcp@v0.1.0` -> `jev-search-mcp --version` prints `0.1.0`.
- [ ] Register for this user's Claude Code: `claude mcp add --scope user jev-search -- "C:\Users\Bear Soul\.local\bin\jev-search-mcp.exe"`; `claude mcp list` shows it connected.
- [ ] If `%APPDATA%\Claude\claude_desktop_config.json` exists: back it up, add the `jev-search` entry (full path to `jev-search-mcp.exe`, `env.JEV_SEARCH_API_KEY` copied from the user env var without printing it), keep all other entries; tell the user to fully restart Claude Desktop.
- [ ] One live smoke search through a real stdio MCP client against the installed executable on the synthetic fixture (budget authorized, ≈$0.00002); report result and cost.
- [ ] Update memory file `jev-search-setup.md` with the MCP facts.

---

*Amended 2026-09-30 after independent expert review (see spec, "Review amendments").*
