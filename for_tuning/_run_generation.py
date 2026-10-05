import json
import random
import subprocess
import sys
import re
from pathlib import Path

ROOT = Path.cwd().parent  # research-ai/
sys.path.insert(0, str(ROOT / "scripts"))

from summarize import DIGEST_PROMPT, CATEGORY_LABELS, format_reports, historical_context, load_reports

random.seed(42)  # 재현 가능하게 고정
print("ROOT:", ROOT)
print("카테고리:", CATEGORY_LABELS)

from collections import defaultdict

MIN_REPORTS = 3  # 이보다 적으면 교차비교가 성립 안 하므로 샘플링 대상에서 제외

def available_dates():
    """naver_*.json이 있고, 건수가 MIN_REPORTS 이상인 날짜 폴더를 연도별로 그룹핑"""
    dates_by_year = defaultdict(list)
    for d in sorted((ROOT / "data").iterdir()):
        if not d.is_dir():
            continue
        date_str = d.name
        year = date_str[:4]
        ok = False
        for cat in CATEGORY_LABELS:
            f = d / f"naver_{cat}.json"
            if f.exists():
                try:
                    items = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if len(items) >= MIN_REPORTS:
                    ok = True
                    break
        if ok:
            dates_by_year[year].append(date_str)
    return dates_by_year

dates_by_year = available_dates()
years = sorted(dates_by_year)
print(f"{len(years)}개 연도, 총 {sum(len(v) for v in dates_by_year.values())}개 날짜 폴더 (카테고리당 {MIN_REPORTS}건 이상 있는 날만)")

N_PER_YEAR = 3  # 연도당 샘플 날짜 수 (조정하면 전체 데이터 양이 바뀜)
sampled_dates = []
for year in years:
    pool = dates_by_year[year]
    sampled_dates.extend(random.sample(pool, min(N_PER_YEAR, len(pool))))

print(f"샘플링된 날짜 {len(sampled_dates)}개 (카테고리당 최대 4개 예시 -> 최대 {len(sampled_dates)*4}개 학습 예시)")
print(sorted(sampled_dates)[:10], "...")

TEACHER_PROMPT = """너는 20년 경력의 시니어 이코노미스트 겸 수석 스트래티지스트다. 여러 대형 증권사 리서치센터를 거치며
거시경제·채권·산업·투자전략을 넘나드는 종합 분석 리포트를 써왔다. 아래는 {today} '{label}' 분야에 발행된
국내 증권사 리서치 리포트 원문들이다. 이 리포트들을 재료 삼아, 네가 낼 수 있는 최고 수준의 "분석 브리핑"을 작성해라.
이 결과물은 이후 다른 AI 모델을 학습시키는 정답(gold standard)으로 쓰이니, 대충 쓰지 말고 진짜 실력을 다 보여줘라.

**매우 중요한 제약 1 — Look-ahead bias 금지**:
너는 지금이 정확히 {today}이고, 그 이후에 실제로 무슨 일이 일어났는지 전혀 모른다고 가정해라.
{today} 이후에 실제로 벌어진 사건, 결과, 통계를 근거로 판단하지 마라. "이후 이렇게 됐다", "사후적으로 증명된다",
"나중에 확인된다" 같은 표현 자체를 쓰지 마라 — 이런 표현은 미래를 안다는 뉘앙스를 풍겨서 그 자체로 문제다.

**매우 중요한 제약 2 — 근거 없는 추상적 비판 금지**:
어떤 리포트의 주장을 비판하거나 판단을 내릴 때, "근거가 부족하다", "증명하는 데이터가 없다" 같은 막연한 말만 하지 마라.
반드시 다음 중 하나로 **구체적으로** 뒷받침해라:
  (a) 같은 날 다른 리포트가 제시한 구체적 수치·주장과 대조 (예: "A리포트는 X라고 봤지만, 같은 날 B리포트의 Y 수치를 보면 다르게 해석될 여지가 있다")
  (b) 그 리포트 자신이 인용한 다른 수치·사실 사이의 내적 모순 (예: "이 리포트는 X라고 결론짓지만, 정작 본문에서 인용한 Y 데이터는 그 결론과 어긋난다")
리포트가 1건뿐이고 위 (a)(b) 둘 다 적용할 근거가 없으면, 억지로 비판하지 말고 그 리포트의 논리를 있는 그대로 정리해라.

아래 5개 기준으로 채점된다는 것을 염두에 두고, 모든 기준에서 만점을 받도록 써라:

1. **정확성**: 원문의 수치·사실과 100% 일치해야 한다. 없는 내용을 지어내거나(환각) 수치를 왜곡하면 안 된다.
   인용할 때는 반드시 그 증권사가 실제로 말한 맥락 그대로 옮겨라.
2. **분석적 종합**: 여러 리포트에 흩어진 근거를 하나의 경제적 인과관계·메커니즘으로 엮어라.
   "무슨 일이 일어나는가 -> 왜 그런가(메커니즘) -> 그래서 어떤 의미/파급효과가 있는가"의 흐름을 모든 이슈에 적용해라.
3. **교차비교**: 리포트 간 해석이 갈리면, 단순히 "의견이 갈린다"고 적지 마라. 제약 1·2를 지키면서
   어느 쪽의 전제·근거가 더 견고한지 판단을 명시해라.
4. **구조·가독성**: 소제목으로 핵심 이슈를 3~6개 나누되, 이슈 간 내용이 중복되지 않게 하라. 각 이슈는
   짧은 서론 없이 바로 핵심으로 들어가라.
5. **완결성**: 원문에 있는 핵심 이슈 중 중요한 것을 빠뜨리지 마라. 특히 수치가 구체적으로 제시된 논의
   (금리 경로, 밸류에이션, 실적 추정치 등)는 반드시 반영해라.

절대 하지 말 것: (1) "OO증권은 ~라고 밝혔다"를 병렬로 나열하는 것. (2) look-ahead bias. (3) 근거 없는 추상적 비판.
증권사 이름과 수치는 네 분석을 뒷받침하는 근거로만 짧게 인용해라.

--- 리포트 원문 ---
{content}

--- 과거 관련 리포트 (참고, 있을 때만 활용해 시계열 변화를 짚어줄 것 — 이것도 {today} 이전 정보이니 사용 가능) ---
{history}

마크다운으로 작성하고, 제목은 "## {label}"로 시작해라. 서론·결론 없이 바로 본문을 시작해라.
"""

print(TEACHER_PROMPT[:300], "...")

NO_SHOCK_PLACEHOLDER = "(과거 날짜라 당시 실시간 시세 데이터를 재현할 수 없음 - 해당 없음)"

import shutil
CLAUDE_BIN = shutil.which("claude") or "/usr/local/bin/claude"
print("claude 실행 파일 경로:", CLAUDE_BIN)


def call_claude(prompt: str, timeout: int = 420) -> str:
    result = subprocess.run(
        [CLAUDE_BIN, "-p"], input=prompt, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude -p 실패 (returncode={result.returncode})\n"
            f"--- stdout ---\n{result.stdout}\n"
            f"--- stderr ---\n{result.stderr}"
        )
    if not result.stdout.strip():
        raise RuntimeError(f"claude -p가 빈 응답을 반환함 (returncode=0). stderr: {result.stderr}")
    return result.stdout.strip()


def build_example(date: str, category: str) -> dict | None:
    """(date, category) 하나 -> 학습 예시 dict. 리포트가 없거나 MIN_REPORTS 미만이면 None."""
    reports = load_reports(ROOT / "data" / date, category)
    if len(reports) < MIN_REPORTS:
        return None
    kr_label = CATEGORY_LABELS[category]
    history = historical_context(reports, category, date)

    # student user 메시지: 프로덕션(summarize.py)과 100% 동일한 프롬프트
    student_user = DIGEST_PROMPT.format(
        today=date, label=kr_label, content=format_reports(reports),
        history=history, shocks=NO_SHOCK_PLACEHOLDER,
    )

    # teacher 프롬프트로 Claude를 호출해 정답(assistant) 생성
    teacher_prompt = TEACHER_PROMPT.format(
        today=date, label=kr_label, content=format_reports(reports), history=history,
    )
    gold_answer = call_claude(teacher_prompt)

    return {
        "date": date,
        "category": category,
        "num_reports": len(reports),
        "messages": [
            {"role": "user", "content": student_user},
            {"role": "assistant", "content": gold_answer},
        ],
    }

print("build_example() 정의 완료 (최소", MIN_REPORTS, "건 미만은 자동 skip)")

OUTPUT_ALL = ROOT / "for_tuning" / "all_examples.jsonl"


def already_done() -> set:
    done = set()
    if OUTPUT_ALL.exists():
        with open(OUTPUT_ALL, encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                done.add((d["date"], d["category"]))
    return done


done_pairs = already_done()
print(f"이미 완료: {len(done_pairs)}건")

pairs_to_do = [(d, c) for d in sampled_dates for c in CATEGORY_LABELS if (d, c) not in done_pairs]
print(f"남은 작업: {len(pairs_to_do)}건")

with open(OUTPUT_ALL, "a", encoding="utf-8") as f:
    for i, (date, category) in enumerate(pairs_to_do, 1):
        try:
            ex = build_example(date, category)
            if ex is None:
                continue
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
            f.flush()
            print(f"[{i}/{len(pairs_to_do)}] {date}/{category} 완료 ({ex['num_reports']}건 리포트)")
        except Exception as e:
            print(f"[{i}/{len(pairs_to_do)}] {date}/{category} 실패: {e}")

print("\n전체 생성 완료. 총 라인 수:", sum(1 for _ in open(OUTPUT_ALL, encoding="utf-8")))