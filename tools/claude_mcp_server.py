#!/usr/bin/env python3
"""MCP (stdio) server that calls the Anthropic Claude API."""

from __future__ import annotations

import os

import anthropic
from mcp.server.mcpserver import MCPServer

DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")

mcp = MCPServer("claude-api")


def _get_client() -> anthropic.Anthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "The ANTHROPIC_API_KEY environment variable is not set. "
            "Check the env entry in ~/.gemini/config/mcp_config.json."
        )
    return anthropic.Anthropic(api_key=api_key)


@mcp.tool()
def ask_claude(
    prompt: str,
    model: str = DEFAULT_MODEL,
    system: str | None = None,
    max_tokens: int = 2048,
) -> str:
    """Send a prompt to the Claude API and return the reply text.

    Args:
        prompt: The user prompt to send to Claude.
        model: The Claude model ID (default: the CLAUDE_MODEL environment variable, or claude-sonnet-5-5).
        system: An optional system prompt.
        max_tokens: The maximum number of reply tokens (default: 2048).
    """
    client = _get_client()
    kwargs: dict[str, object] = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system

    response = client.messages.create(**kwargs)
    parts = [block.text for block in response.content if block.type == "text"]
    text = "\n".join(parts)
    usage = response.usage
    return (
        f"{text}\n\n"
        f"[model={model} | input_tokens={usage.input_tokens}, output_tokens={usage.output_tokens}]"
    )


@mcp.tool()
def list_claude_models(limit: int = 20) -> str:
    """List the Claude models available to the current API key.

    Args:
        limit: The maximum number of models to list (default: 20).
    """
    client = _get_client()
    page = client.models.list(limit=limit)
    lines = [f"- {m.id}" + (f" ({m.display_name})" if getattr(m, "display_name", None) else "") for m in page.data]
    return "\n".join(lines) if lines else "No models found."


if __name__ == "__main__":
    mcp.run(transport="stdio")
