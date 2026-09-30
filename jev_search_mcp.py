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
