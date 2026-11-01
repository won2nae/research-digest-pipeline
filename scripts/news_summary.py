"""전날 시장에 영향을 준 주요 뉴스를 미국 메인 + 한국 서브로 요약.

macro_shock.py의 get_news_context와 달리 충격 지표 발생 여부와 무관하게
매일 무조건 실행된다 (사이트 홈페이지 상단에 늘 보여줄 뉴스 요약용).
"""
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

CLAUDE_BIN = shutil.which("claude") or "/usr/local/bin/claude"
NEWS_TOOLS = (
    "mcp__claude_ai_NewsMCP_without_a_key__news,"
    "mcp__claude_ai_NewsMCP_without_a_key__check_coverage"
)
DENIED_MARKERS = ("허용되지 않", "도구 권한", "권한 프롬프트")

ROOT = Path(__file__).resolve().parent.parent

PROMPT = """오늘({today}) 기준 전날 시장에 영향을 준 주요 뉴스를 뉴스 검색 도구로 찾아
아래 형식의 한국어 마크다운으로 요약해라.

1. 미국발 뉴스를 메인으로 다뤄라: 글로벌 증시·금리·환율·원자재에 영향을 준
   미국 중심 뉴스 3~5개.
2. 한국 뉴스를 서브로 다뤄라: 국내 증시·경제에 영향을 준 한국 뉴스 2~3개.
3. 각 뉴스는 1~2줄로 간결하게, 어느 언론사/매체인지 짧게 밝혀라.
4. 보도된 사실만 써라. 전망이나 투자 판단은 쓰지 마라.
5. 뉴스를 못 찾으면 해당 섹션에 "특별한 뉴스 없음"이라고만 써라.

다음 형식을 반드시 지켜라 (서론 없이 바로 시작):

## 미국 뉴스
- ...

## 한국 뉴스
- ...
"""


def get_news_summary(today: str) -> str:
    prompt = PROMPT.format(today=today)
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "--allowedTools", NEWS_TOOLS],
            input=prompt, capture_output=True, text=True, timeout=120,
        )
        text = result.stdout.strip()
        if result.returncode != 0 or not text:
            print(f"[news_summary] 실패: {result.stderr[:300]}", file=sys.stderr)
            return ""
        if any(marker in text for marker in DENIED_MARKERS):
            print("[news_summary] 뉴스 도구 권한 오류 응답이라 생략함", file=sys.stderr)
            return ""
        # "검색 결과를 정리합니다" 같은 서론이 가끔 붙어서, 첫 '## ' 제목부터만 남긴다.
        idx = text.find("## ")
        return text[idx:].strip() if idx != -1 else text
    except Exception as e:
        print(f"[news_summary] 예외: {e}", file=sys.stderr)
        return ""


def main():
    today = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    out_dir = ROOT / "data" / today
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = get_news_summary(today)
    (out_dir / "news_summary.md").write_text(summary, encoding="utf-8")
    print(summary if summary else "(뉴스 요약 없음)")


if __name__ == "__main__":
    main()
