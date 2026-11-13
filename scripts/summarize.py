"""수집된 리포트(JSON)를 로컬 Qwen3-14B로 요약해 md로 저장.
"""
import difflib
import json
import re
import sys
from datetime import date
from pathlib import Path

from dart_agent import get_company_analysis
from local_llm import ask_local, CATEGORY_TO_GROUP
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

# 매크로/채권은 지표·수치 중심이라 일관성이 중요해 temperature를 낮게,
# 섹터/투자전략은 여러 리포트를 엮어 해석하는 서술이라 조금 더 높게 둔다.
CATEGORY_TEMPERATURE = {
    "macro": 0.5,
    "bond": 0.5,
    "sector": 0.65,
    "strategy": 0.65,
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
- 리포트들 사이에 해석이 갈리면, 단순히 "의견이 갈린다"고 적지 말고 각 쪽이 근거로 삼는 수치·전제를 명확히 대조해서 독자가 직접 비교할 수 있게 써라. 어느 쪽이 맞다고 결론 내리거나 우열을 판단하지 마라 — 판단은 읽는 사람의 몫이다.
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
이 내용에서 오늘 반복적으로 등장하거나 서로 연결되는 핵심 쟁점을 3~5줄로 정리해라.
전망이나 투자 판단을 내리지 말고, 어떤 쟁점이 있고 그 쟁점의 근거(수치·전제)가 무엇인지만
사실 중심으로 정리해라. "~할 것이다", "~한 시각이 유효하다" 같은 전망성 표현은 쓰지 마라.
바로 본문 내용만 써라. 제목이나 안내 문구, 메타 설명은 쓰지 마라.

--- 매크로 요약 ---
{macro}

--- 채권 요약 ---
{bond}

--- 산업섹터 요약 ---
{sector}
"""

STRATEGY_DISCLAIMER = (
    "> **이 정리는 AI가 위 증권사 리포트들의 핵심 쟁점과 근거를 추출·정리한 것으로, "
    "투자 판단이나 시장 전망을 제시하지 않습니다. 판단은 읽는 사람의 몫입니다.**"
)

DART_DISCLAIMER = (
    "> **아래는 위 투자전략·섹터 리포트에서 비중 있게 다뤄진 기업을 DART 전자공시로 "
    "대조한 것입니다. 증권사 주장과 실제 공시·재무제표가 일치하는지만 확인하며, "
    "투자 판단을 제시하지 않습니다.**"
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


def enforce_structure(text: str, kr_label: str) -> str:
    """모델이 카테고리 제목(## {label})을 빼먹거나 오타 내고, 개별 이슈 제목에
    ###가 아닌 ##를 쓰는 경우가 있다 (예: 2026-10-06 채권/섹터/투자전략).
    카테고리 제목으로 보이는 줄은 버리고, 나머지 '## '는 전부 '### '로 낮춘 뒤
    정식 제목을 맨 위에 한 번만 붙여서 항상 같은 구조를 보장한다."""
    out = []
    for line in text.split("\n"):
        if line.startswith("## "):
            title = line[3:].strip()
            if difflib.SequenceMatcher(None, title, kr_label).ratio() > 0.5:
                continue
            line = "###" + line[2:]
        out.append(line)
    body = "\n".join(out).strip("\n")
    return f"## {kr_label}\n\n{body}"


def generate(prompt: str, category: str) -> str:
    # no_repeat_ngram_size=4를 시도했으나 반복 루프보다 더 나쁜 실패(한자 섞인 비문,
    # 가비지 출력)로 2연속 재현돼서 되돌림 - 2026-11-01 테스트로 확인.
    return ask_local(
        prompt, model_name=LOCAL_MODEL, max_new_tokens=8192, repetition_penalty=1.2,
        adapter_group=CATEGORY_TO_GROUP.get(category),
        temperature=CATEGORY_TEMPERATURE.get(category, 0.6),
    )


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
    sector_reports_text = ""
    company_analysis = ""
    for label, kr_label in CATEGORY_LABELS.items():
        reports = load_reports(data_dir, label)
        if not reports:
            digests[label] = f"## {kr_label}\n\n오늘 수집된 리포트가 없습니다."
            continue
        history = historical_context(reports, label, today)
        has_history = history not in ("(없음)",) and not history.startswith("(과거 데이터 없음") and not history.startswith("(검색 실패")
        history_count = history.count(chr(10)) + 1 if has_history else 0

        if label == "sector":
            sector_reports_text = format_reports(reports)
        elif label == "strategy":
            print(f"[{label}] DART 기업분석 에이전트 실행 중...")
            combined = sector_reports_text + "\n\n---\n\n" + format_reports(reports)
            company_analysis = get_company_analysis(today, combined)

        prompt = DIGEST_PROMPT.format(
            today=today, label=kr_label, content=format_reports(reports), history=history,
            shocks=shock_summary,
        )
        print(f"[{label}] {len(reports)}건 요약 중... (과거 참고 {history_count}건)")
        result = generate(prompt, label)
        digests[label] = enforce_structure(result, kr_label)
        (out_dir / f"{label}.md").write_text(digests[label], encoding="utf-8")

    # DART 기업분석 추가 (모델이 프롬프트에 끼워줘도 본문에 거의 반영 안 해서 - 4차례 실험으로 확인함 -
    # 별도 섹션으로 코드가 직접 붙인다. 내용 생성은 dart_agent가 이미 끝낸 상태)
    if company_analysis:
        # DART 에이전트가 기업마다 "## 회사명"을 쓰는데, build_site.py의 parse_categories가
        # "\n## "마다 최상위 탭으로 쪼개버려서 기업명이 매크로/채권급 탭으로 노출되는 버그가
        # 있었다 (2026-11-05). "### "로 한 단계 낮춰서 DART 탭 안의 하위 섹션으로만 보이게 한다.
        company_analysis = re.sub(r"^## ", "### ", company_analysis, flags=re.MULTILINE)
        dart_section = f"## 기업 공시 검증 (DART)\n\n{DART_DISCLAIMER}\n\n{company_analysis}"
        # 2026-11-13: 사이트에 "기업 공시 검증 (DART)" 탭이 노출되지 않도록 strategy.md에는
        # 더 이상 붙이지 않는다. dart_analysis.md로만 남긴다.
        # 다른 카테고리처럼 독립된 산출물로도 남긴다 (별도 에이전트의 결과물이라는 걸
        # output에서도 바로 확인할 수 있게)
        (out_dir / "dart_analysis.md").write_text(dart_section, encoding="utf-8")

    # 투자전략에 AI 종합의견 추가 (안내문구는 코드로 고정, 모델은 본문만 생성)
    print("[strategy] AI 종합의견 생성 중...")
    extra_prompt = STRATEGY_EXTRA_PROMPT.format(
        macro=digests["macro"], bond=digests["bond"], sector=digests["sector"]
    )
    opinion = generate_short(extra_prompt).strip()
    extra_section = f"## 오늘의 핵심 쟁점 정리\n\n{STRATEGY_DISCLAIMER}\n\n{opinion}"
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
