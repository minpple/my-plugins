#!/usr/bin/env python3
"""Anthropic Claude API를 호출하는 MCP(stdio) 서버."""

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
            "ANTHROPIC_API_KEY 환경변수가 설정되어 있지 않습니다. "
            "~/.gemini/config/mcp_config.json의 env 항목을 확인하세요."
        )
    return anthropic.Anthropic(api_key=api_key)


@mcp.tool()
def ask_claude(
    prompt: str,
    model: str = DEFAULT_MODEL,
    system: str | None = None,
    max_tokens: int = 2048,
) -> str:
    """Claude API에 프롬프트를 보내고 응답 텍스트를 반환합니다.

    Args:
        prompt: Claude에게 전달할 사용자 프롬프트.
        model: 사용할 Claude 모델 ID (기본값: CLAUDE_MODEL 환경변수 또는 claude-sonnet-5-5).
        system: 선택적 시스템 프롬프트.
        max_tokens: 최대 응답 토큰 수 (기본값: 2048).
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
    """현재 API 키로 사용 가능한 Claude 모델 목록을 조회합니다.

    Args:
        limit: 조회할 최대 모델 수 (기본값: 20).
    """
    client = _get_client()
    page = client.models.list(limit=limit)
    lines = [f"- {m.id}" + (f" ({m.display_name})" if getattr(m, "display_name", None) else "") for m in page.data]
    return "\n".join(lines) if lines else "조회된 모델이 없습니다."


if __name__ == "__main__":
    mcp.run(transport="stdio")
