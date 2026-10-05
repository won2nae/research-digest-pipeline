"""수집된 리포트(JSON)를 로컬 Qwen3-14B로 요약해 md로 저장.
"""
import json
import sys
from datetime import date
from pathlib import Path

from local_llm import ask_local
from macro_shock import format_summary as format_shock_summary, fetch_indicators, check_shocks
from vectorstore import search as vector_search

LOCAL_MODEL = "Qwen/Qwen3-14B"

ROOT = Path(__file__).resolve().parent.parent

CATEGORY_LABELS = {
    "macro": "매크로(경제)",
    "bond": "채권",
    "sector": "산업 섹터별",
    "strategy": "투자전략",
}

DIGEST_PROMPT = """너는 거시경제·금융시장을 오래 분석해온 시니어 애널리스트다.
아래는 오늘({today}) 국내 증권사들이 발행한 '{label}' 분야 리서치 리포트 원문들이다.
이 리포트들을 재료 삼아, 한국어 마크다운으로 "분석 브리핑"을 작성해라.

절대 하지 말 것:
- "OO증권은 ~라고 밝혔다" 식으로 리포트를 하나씩 나열/번역하는 것. 이건 요약이 아니라 카탈로그다.

반드시 할 것:
- 오늘 시장에서 벌어지는 핵심 현상 3~6개를 뽑아, 각각에 대해 "무슨 일이 일어나고 있는가 -> 왜 그런가(경제적 메커니즘) -> 그래서 어떤 의미/파급효과가 있는가"의 흐름으로 서술
- 여러 리포트의 근거를 하나의 논리로 엮어라. 금리-환율-자본흐름, 유가-인플레이션-통화정책처럼 실제 인과관계를 짚어가며 설명
- 증권사 이름과 수치는 네 분석을 뒷받침하는 근거로만 짧게 인용 (예: "~한 점은 A증권의 B라는 데이터로도 확인된다")
- 리포트들 사이에 해석이 갈리면, 단순히 "의견이 갈린다"고 적지 말고 어느 쪽 논리가 왜 더 설득력 있는지 네 판단을 붙여라
- 아래 "과거 관련 리포트"가 있으면, 그때와 지금을 비교해 흐름이 어떻게 바뀌었는지 분석에 녹여라 (관련 없으면 생략)
- 불필요한 서론/결론 없이 바로 본문 시작
- 제목은 "## {label}"로 시작

--- 리포트 원문 ---
{content}

--- 과거 관련 리포트 (참고, 있을 때만 활용) ---
{history}

--- 오늘의 매크로 충격 지표 (참고, 관련 있으면 이슈 설명에 자연스럽게 반영) ---
{shocks}
"""


def historical_context(reports: list[dict], category: str, today: str, top_k: int = 5) -> str:
    """오늘 리포트 제목들을 쿼리로 과거(오늘 이전) 유사 리포트를 검색."""
    if not reports:
        return "(없음)"
    query = " / ".join(r["title"] for r in reports[:10])
    try:
        hits = vector_search(query, category=category, before_date=today, top_k=top_k)
    except Exception as e:
        return f"(검색 실패: {e})"
    if not hits:
        return "(과거 데이터 없음 - 아카이브 초기 단계)"
    lines = []
    for h in hits:
        m = h["metadata"]
        lines.append(f"[{m['date']} {m['broker']}] {m['title']}")
    return "\n".join(lines)

STRATEGY_EXTRA_PROMPT = """아래는 오늘 매크로/채권/산업섹터 분야에서 정리된 요약이다.
이 내용을 종합했을 때 오늘의 시장 상황에 대해 가질 수 있는 시각을 3~5줄로 작성해라.
단정적 투자 조언이 아니라 "~한 점에서 ~한 시각도 가능하다" 같은 참고용 톤으로 작성해라.
바로 본문 내용만 써라. 제목이나 안내 문구, 메타 설명은 쓰지 마라.

--- 매크로 요약 ---
{macro}

--- 채권 요약 ---
{bond}

--- 산업섹터 요약 ---
{sector}
"""

STRATEGY_DISCLAIMER = (
    "> **이 의견은 AI가 위 증권사 리포트들을 종합해 참고용으로 제시하는 것으로, "
    "특정 증권사의 투자 조언이 아닙니다.**"
)


def load_reports(data_dir: Path, label: str) -> list[dict]:
    path = data_dir / f"naver_{label}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def format_reports(reports: list[dict]) -> str:
    blocks = []
    for r in reports:
        blocks.append(f"[{r['broker']}] {r['title']}\n{r['content']}")
    return "\n\n---\n\n".join(blocks)


def generate(prompt: str) -> str:
    return ask_local(prompt, model_name=LOCAL_MODEL, max_new_tokens=8192, repetition_penalty=1.2)


def generate_short(prompt: str) -> str:
    """튜닝 데이터에 없던 짧은 과제(예: AI 종합의견)용. adapter가 장문 스타일로 편향돼 있어
    base 모델(adapter 끔)로 생성한다."""
    return ask_local(prompt, model_name=LOCAL_MODEL, max_new_tokens=800, use_adapter=False)


def load_shock_summary(data_dir: Path) -> str:
    """오늘 매크로 충격 지표를 불러온다. 이미 계산돼 있으면 파일에서, 없으면 즉석에서 계산."""
    shock_file = data_dir / "macro_shocks.md"
    if shock_file.exists():
        return shock_file.read_text(encoding="utf-8")
    try:
        items = fetch_indicators()
        results = check_shocks(items)
        return format_shock_summary(results)
    except Exception as e:
        return f"(충격 지표 조회 실패: {e})"


def main():
    today = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    data_dir = ROOT / "data" / today
    out_dir = ROOT / "output" / today
    out_dir.mkdir(parents=True, exist_ok=True)

    shock_summary = load_shock_summary(data_dir)
    print(f"[shock] {shock_summary.splitlines()[0]}")

    digests = {}
    for label, kr_label in CATEGORY_LABELS.items():
        reports = load_reports(data_dir, label)
        if not reports:
            digests[label] = f"## {kr_label}\n\n오늘 수집된 리포트가 없습니다."
            continue
        history = historical_context(reports, label, today)
        has_history = history not in ("(없음)",) and not history.startswith("(과거 데이터 없음") and not history.startswith("(검색 실패")
        history_count = history.count(chr(10)) + 1 if has_history else 0
        prompt = DIGEST_PROMPT.format(
            today=today, label=kr_label, content=format_reports(reports), history=history,
            shocks=shock_summary,
        )
        print(f"[{label}] {len(reports)}건 요약 중... (과거 참고 {history_count}건)")
        digests[label] = generate(prompt)
        (out_dir / f"{label}.md").write_text(digests[label], encoding="utf-8")

    # 투자전략에 AI 종합의견 추가 (안내문구는 코드로 고정, 모델은 본문만 생성)
    print("[strategy] AI 종합의견 생성 중...")
    extra_prompt = STRATEGY_EXTRA_PROMPT.format(
        macro=digests["macro"], bond=digests["bond"], sector=digests["sector"]
    )
    opinion = generate_short(extra_prompt).strip()
    extra_section = f"## AI 종합의견 (참고용)\n\n{STRATEGY_DISCLAIMER}\n\n{opinion}"
    digests["strategy"] = digests["strategy"] + "\n\n" + extra_section
    (out_dir / "strategy.md").write_text(digests["strategy"], encoding="utf-8")

    # 전체 다이제스트 합치기 (충격 지표는 항상 맨 위에 고정 노출)
    full = (
        f"# {today} 데일리 리서치 브리핑\n\n"
        + shock_summary + "\n\n---\n\n"
        + "\n\n---\n\n".join(digests[label] for label in CATEGORY_LABELS)
    )
    digest_path = out_dir / f"digest_{today}.md"
    digest_path.write_text(full, encoding="utf-8")
    print(f"\n완료: {digest_path}")


if __name__ == "__main__":
    main()
