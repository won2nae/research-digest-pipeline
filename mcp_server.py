#!/usr/bin/env python3
"""증권사 리서치 아카이브(18년치, 10만+ 건)를 검색하는 MCP 서버.

대화형 claude 세션에서 이 도구를 자동으로 호출해서, 자연어 질문에
과거 리포트를 검색해서 답할 수 있게 한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from vectorstore import search as vector_search

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(name="research-archive")


@mcp.tool()
def search_historical_reports(
    query: str, category: str = "", before_date: str = "", top_k: int = 5
) -> str:
    """18년치(2007~2026) 국내 증권사 리서치 리포트 아카이브를 의미 기반으로 검색한다.

    Args:
        query: 검색할 주제/키워드 (자연어, 예: "코로나19 유가 급락", "반도체 업황")
        category: macro(매크로) / bond(채권) / sector(산업섹터) / strategy(투자전략) 중 하나.
            비워두면 전체 카테고리에서 검색한다.
        before_date: YYYY-MM-DD 형식. 이 날짜 이전 리포트만 검색한다. 비워두면 제한 없음.
        top_k: 반환할 결과 개수 (기본 5)
    """
    hits = vector_search(
        query,
        category=category or None,
        before_date=before_date or None,
        top_k=top_k,
    )
    if not hits:
        return "검색 결과 없음"

    blocks = []
    for h in hits:
        m = h["metadata"]
        blocks.append(
            f"[{m['date']} {m['broker']} / {m['category']}] {m['title']}\n{h['document'][:500]}"
        )
    return "\n\n---\n\n".join(blocks)


if __name__ == "__main__":
    mcp.run()
