"""DART 기업분석 에이전트.

오늘의 투자전략/산업섹터 리포트에서 실제로 비중 있게 다뤄진 기업을 추려서,
DART 공시·재무제표로 사실을 검증·보강한 참고자료를 만든다. 투자전략 생성
프롬프트에 이 결과를 끼워 넣어, 모델이 증권사 주장과 실제 공시 수치를
대조할 수 있게 한다.
"""
import shutil
import subprocess
import sys
from pathlib import Path

CLAUDE_BIN = shutil.which("claude") or "/usr/local/bin/claude"
ROOT = Path(__file__).resolve().parent.parent  # .mcp.json이 여기 있음 - claude -p가 찾으려면 cwd가 이거여야 함
DART_TOOLS = "mcp__dart-disclosures__dart_search_disclosures,mcp__dart-disclosures__dart_financial_summary"

AGENT_PROMPT = """아래는 오늘({today}) 투자전략/산업섹터 리포트에서 다룬 내용이다.

여기서 **비중 있게(단순 언급이 아니라 실적·실적전망·주가 논리가 구체적으로 나온) 다뤄진
국내 상장기업을 최대 4곳**만 골라라. 각 기업에 대해:

1. dart_search_disclosures로 최근 30일 공시를 확인해라. as_of_date는 반드시 {today}로 줘라
   ({today} 이후 공시는 존재할 수 없으니 조회하지 마라 — look-ahead bias 방지).
2. dart_financial_summary로 가장 최근 분기 재무정보를 확인해라.
3. 리포트의 주장(실적, 성장률 등)이 실제 공시·재무제표 수치와 일치하는지 짧게 대조해라.
   일치하면 "공시 기준과 일치"라고만 쓰고 길게 설명하지 마라. 불일치하거나 공시에서
   추가로 확인되는 중요 사실이 있을 때만 구체적으로 짚어라.

**절대 하지 말 것**: 투자 판단·전망 제시, 공시에 없는 내용 추정, 모르는 기업 지어내기.
리포트에 뚜렷한 기업 분석이 없으면 "오늘은 공시로 검증할 만큼 구체적으로 다뤄진 기업 없음"이라고만 써라.

마크다운으로, 기업당 2~4줄 이내로 간결하게. 서론 없이 바로 시작해라.

--- 오늘의 투자전략/산업섹터 리포트 ---
{content}
"""


def get_company_analysis(today: str, content: str) -> str:
    if not content.strip():
        return ""
    prompt = AGENT_PROMPT.format(today=today, content=content[:12000])
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "--allowedTools", DART_TOOLS],
            input=prompt, capture_output=True, text=True, timeout=300, cwd=str(ROOT),
        )
        if result.returncode != 0 or not result.stdout.strip():
            print(f"[dart_agent] 실패: {result.stderr[:300]}", file=sys.stderr)
            return ""
        return result.stdout.strip()
    except Exception as e:
        print(f"[dart_agent] 예외: {e}", file=sys.stderr)
        return ""


if __name__ == "__main__":
    import json
    from pathlib import Path

    today = sys.argv[1] if len(sys.argv) > 1 else "2026-10-30"
    root = Path(__file__).resolve().parent.parent
    content_parts = []
    for label in ("strategy", "sector"):
        f = root / "data" / today / f"naver_{label}.json"
        if f.exists():
            items = json.loads(f.read_text(encoding="utf-8"))
            for it in items:
                content_parts.append(f"[{it['broker']}] {it['title']}\n{it['content']}")
    content = "\n\n---\n\n".join(content_parts)
    print(f"입력 리포트 {len(content_parts)}건, {len(content)}자")
    print(get_company_analysis(today, content))
