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
    except (ValueError, OSError) as e:  # e.g. NUL byte or oversized argv
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
