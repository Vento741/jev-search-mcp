# jev-search-mcp — design

Date: 2026-09-30 · Status: approved; amended after expert review (see "Review amendments")

## Goal

Expose the reviewed `jev-search` CLI (larguesa/jev-search, `main` @ `8aa403554d7904d3c14224cfda02a4e2144c0ccd`, v0.2.0) as a local **stdio MCP server**, so that Claude Code (Windows and Linux VPS), Claude Desktop and any other MCP client or orchestrator can run complementary semantic line search as a first-class tool.

A colleague must be able to connect it from a short message: install `uv`, set their own OpenRouter key, add one MCP entry.

## Non-goals (v1)

- Remote/HTTP MCP. The server must run on the machine that holds the files; a shared remote server cannot read a client's local files.
- Automatic splitting of large files, recursive directory scanning, indexing, caching.
- Changing the upstream project. Upstream stays untouched; this is a separate repository.
- Re-implementing any search, validation or file-safety logic.

## Architecture

```
MCP client (Claude Code / Desktop / other)
   │ stdio (JSON-RPC, spawned child process)
   ▼
jev-search-mcp  (MCPServer, one tool)
   │ subprocess: [sys.executable, "-m", "jev_search", ...]
   ▼
jev-search CLI (pinned dependency, same venv) ── HTTPS ──► OpenRouter / TypeSafe
```

- Implementation: official MCP Python SDK v2 (`mcp>=2.2,<2.3`), `from mcp.server import MCPServer`, `mcp.run()` on stdio.
- The CLI is invoked with the interpreter of the server's own environment (`sys.executable -I -m jev_search`; `-I` keeps the working directory and `PYTHON*` variables off `sys.path`, so a `jev_search.py` in the user's project can never shadow the pinned CLI), so it works when installed via `uvx`/`uv tool install` even though the `jev-search` executable of a dependency is not on PATH.
- The CLI is the only source of truth for file checks, limits, request building, response validation and all-or-nothing error semantics. The server only maps arguments and trims output.

## Tool: `jev_search`

| Parameter | Type | Rules |
|---|---|---|
| `query` | `str` | Required. Passed as `--query`. The CLI enforces ≤512 bytes and safety checks. |
| `files` | `list[str]` | Required, 1–8 items, **absolute paths only** (relative → `ToolError`; the server's working directory is arbitrary, e.g. under Claude Desktop). Passed as positional args after `--`. |
| `top_k` | `int \| None` | Optional, 1–64. Passed as `--top-k` (implies ranking). |
| `dry_run` | `bool` | Default `false`. Passes `--dry-run` (offline, no key read, free). |

Not exposed to the agent: provider, model, key, `--send`, `--max-requests`. Provider/model come only from `JEV_SEARCH_PROVIDER` / `JEV_SEARCH_MODEL` in the server's environment, so the agent cannot change the authorized provider.

Tool description (visible to the model) states: complementary to exact search; 1–8 UTF-8 `.txt/.md/.csv/.jsonl/.log` files; ≤16 KB and ≤64 lines combined; all selected nonblank lines are sent to the provider; real search costs money; use `dry_run` to preview.

### Output

On success, return a JSON object:

- dry run: the CLI output unchanged except `request` is dropped (it repeats every line plus boilerplate); keep `mode`, `payload_bytes`, `rows`, `unjudged`, and add `provider`/`model` from the request.
- real search: `mode`, `latency_seconds`, `results` (unchanged: `file`, `line`, `original`, `probability`, `match`), `ranked_results` when present, and `meta` = `{model, generation_id, cost, input_tokens, output_tokens}` extracted from `raw_response` (missing fields → `null`, never `0`). `raw_response` itself is dropped.

### Errors

- Non-zero CLI exit → raise `ToolError` with the `error` field of the CLI's stderr JSON. If stderr is not that JSON (e.g. an interpreter crash), use its first 500 characters, prefixed with `jev-search failed:`.
- Missing key → the CLI's own message (`set JEV_SEARCH_API_KEY ...`), surfaced as-is.
- Subprocess timeout 330 s (CLI socket timeout is 300 s) → `ToolError("timed out; not retried; a charge may have occurred")`.
- `ValueError` from spawning (e.g. NUL byte in the query) or from parsing CLI stdout → `ToolError("jev-search: invalid input or output (<ExceptionType>)")`.
- No retries anywhere. No partial results.
- The key is only inherited through the environment; it never appears in arguments, output or error text.

### Server instructions

`MCPServer("jev-search", instructions=..., version=<package version>)`; the tool carries `ToolAnnotations(title="Semantic line search", readOnlyHint=True, destructiveHint=False, openWorldHint=True)` (no `idempotentHint`: every call costs money) carries a ~10-line usage policy: use alongside exact/lexical search, select small bounded passages, read original context before answering, cite sources not scores, limits, privacy (all selected lines leave the machine), cost, ask the user before bulk use.

## Packaging and distribution

Repository: `github.com/Vento741/jev-search-mcp`, **public**, MIT (own copyright), README credits upstream.

```
jev_search_mcp.py      server (single module)
pyproject.toml         deps: mcp>=2.2,<3 ; jev-search @ git+https://github.com/larguesa/jev-search@8aa403554d7904d3c14224cfda02a4e2144c0ccd
                       script: jev-search-mcp = "jev_search_mcp:main"
README.md              English, custom-designed, short quick start first
README.ru.md           Russian translation, same structure; language switcher at top of both
docs/GUIDE.md          Detailed guide (Russian) with scenarios
tests/                 offline tests
LICENSE
```

Run modes documented:

Requirements for users: `uv` and `git` on PATH.

1. **Persistent (primary):** `uv tool install git+https://github.com/Vento741/jev-search-mcp@v0.1.0` → `jev-search-mcp` on PATH. Fast client start, works offline after install. Clients point at the executable (full path in Claude Desktop).
2. **Zero-install (alternative):** `uvx --from git+https://github.com/Vento741/jev-search-mcp@v0.1.0 jev-search-mcp` — slower first start, may contact GitHub on client start.
3. Releases are git tags (`v0.1.0`, ...); docs always show the pinned tag.

## Key handling

Each user uses their **own** OpenRouter inference key with a provider-side spending limit. How the key reaches the server depends on the client:

- **Claude Code:** inherits its own process environment → user environment variable `JEV_SEARCH_API_KEY` (Windows user env with a full client restart; Linux `~/.bashrc` or a `chmod 600` env file sourced from it — `~/.profile` alone misses non-login shells). Verified live in Task 5.
- **Claude Desktop and other SDK-based clients:** pass only a small default set of variables (APPDATA, PATH, USERPROFILE, …) plus the config `env` block → the key **must** go in the `env` block (plaintext in a user-private file; never commit or share it). `JEV_SEARCH_PROVIDER`/`JEV_SEARCH_MODEL` likewise. Never commit keys; never paste them into chats.

## Documentation

**README.md / README.ru.md** — polished GitHub landing: title + one-line pitch, badges (license, Python, MCP), language switcher, "what it does" in 3 bullets, **Quick start in 3 steps** (install uv → set key → add to client) with copy-paste blocks for Claude Code (`claude mcp add -s user ...`), Claude Desktop (`claude_desktop_config.json` snippet) and generic MCP stdio JSON, the tool contract table, limits, privacy/cost, link to GUIDE, credits and license. The Quick start must fit in one messenger message.

**docs/GUIDE.md** (Russian) — how it works and what is sent; install on Windows / Linux / VPS; uvx vs persistent install; updating and pinning; client setup (Claude Code user vs project `.mcp.json`, Claude Desktop, Claude Agent SDK Python example, generic stdio); key management and budgets; **usage scenarios**: project docs and ADRs, Obsidian / second-brain notes, VPS log triage, support tickets in CSV, grep + semantic combined workflow, working around the 16 KB/64-line limit with reviewed excerpts; note that a client-side request timeout (often ~60 s) does not cancel a charge; limits and error reference; troubleshooting (key not visible → restart the client's main process; `uvx` not found → PATH; limit errors); a ready snippet for a project's `CLAUDE.md` / `AGENTS.md`.

## Testing

Offline, no key, no network to providers:

0. `tests/__init__.py` deletes every `JEV_SEARCH_*` variable at import, so no test can ever reach a provider or depend on local provider settings.
1. Tool function `dry_run=True` on a fixture → `mode == "dry-run"`, rows match, no `request` key.
2. Error path: disallowed file (e.g. `.py`) → `ToolError` with the CLI message.
3. Missing key with `dry_run=False` and `JEV_SEARCH_API_KEY` unset → `ToolError` mentioning `JEV_SEARCH_API_KEY`, no network call.
4. Output shaping: feed a canned CLI success JSON through the trimming function → `raw_response` gone, `meta` filled, `results` unchanged.
5. Schema bounds: `files=[]` / `top_k=65` with `dry_run=True` fail with a pydantic `validation error`; `list_tools` schema has `minItems 1`, `maxItems 8`, `maximum 64`.
6. Security: a fake `jev_search.py` in the working directory does not shadow the CLI; relative paths are rejected; child gets `stdin=DEVNULL` and `CREATE_NO_WINDOW` on Windows.
7. End-to-end stdio (with `anyio.fail_after(60)`): `Client(StdioServerParameters(command=sys.executable, args=["-m","jev_search_mcp"]))` → `list_tools` contains `jev_search`; `call_tool` with `dry_run=True` succeeds; initialize result carries instructions.

CI: ubuntu + windows × Python 3.11 + 3.13, `uv sync --locked`, committed `uv.lock`.

Then manual: install via `uv tool install` from the published tag, register in Claude Code, one live search on a synthetic file (~$0.00002, authorized budget).

## Open decisions

None blocking. Detailed English guide deferred until requested.

## Review amendments (2026-09-30)

An independent reviewer executed the plan's code (all tests passed) and found: CLI shadowing via `-m` from the working directory (reproduced; fixed with `-I`), Claude Desktop not inheriting user env (key goes in the `env` block), a schema test that passed without the schema, relative-path trap, opaque errors on NUL bytes/non-JSON output, missing tool annotations/version, and distribution pitfalls (git requirement, uvx on every start, VPS non-login shells). All are incorporated above.
