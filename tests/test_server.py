import json
import logging
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
logging.getLogger("mcp").setLevel(logging.CRITICAL)  # the SDK logs expected tool errors at INFO; keep test output clean
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
