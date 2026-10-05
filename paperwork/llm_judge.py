"""LLM-as-a-judge: 로컬 모델 요약 품질을 루브릭 기반으로 Claude가 채점.

같은 매크로 리포트 원문(2026-09-14)을 넣고 각 모델이 만든 요약을,
5개 기준(정확성/분석적 종합/교차비교/구조/완결성)으로 1~5점 채점한다.
"""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL_TEST_DIR = ROOT / "output" / "model_test"
REFERENCE_DATA = ROOT / "data" / "2026-09-14" / "naver_macro.json"

RUBRIC = {
    "정확성": "원문 리포트의 수치·사실과 일치하는가. 없는 내용을 지어내거나(환각) 수치를 잘못 옮기지 않았는가.",
    "분석적_종합": "단순히 '증권사가 이렇게 말했다'는 나열이 아니라, 여러 리포트의 근거를 하나의 경제적 논리(인과관계·메커니즘)로 엮어냈는가.",
    "교차비교": "증권사 간 시각/해석 차이가 있을 때 이를 실제로 포착하고, 왜 다른지 설명했는가.",
    "구조_가독성": "소제목 구성, 문단 흐름, 마크다운 구조가 읽기 좋은가. 불필요한 반복이나 어색한 문장은 없는가.",
    "완결성": "원문에 있는 핵심 이슈를 빠짐없이 다뤘는가. 중요한 내용이 누락되지 않았는가.",
}

JUDGE_PROMPT = """너는 금융 리서치 요약의 품질을 평가하는 채점자다.
아래 "원문 리포트"를 바탕으로 "평가 대상 요약"이 얼마나 잘 작성됐는지, 주어진 루브릭에 따라 채점해라.

--- 원문 리포트 ---
{reference}

--- 평가 대상 요약 ---
{candidate}

--- 채점 기준 (각 1~5점, 5점이 최고) ---
{rubric_text}

반드시 아래 형식 그대로 출력해라 (다른 설명 없이):

===정확성===
점수: (1~5)
이유: (한 문장)
===분석적_종합===
점수: (1~5)
이유: (한 문장)
===교차비교===
점수: (1~5)
이유: (한 문장)
===구조_가독성===
점수: (1~5)
이유: (한 문장)
===완결성===
점수: (1~5)
이유: (한 문장)
===총평===
(두세 문장으로 종합 코멘트)
"""


def format_reference(items: list[dict]) -> str:
    blocks = []
    for r in items:
        blocks.append(f"[{r['broker']}] {r['title']}\n{r['content']}")
    return "\n\n---\n\n".join(blocks)


def build_rubric_text() -> str:
    return "\n".join(f"- {k}: {v}" for k, v in RUBRIC.items())


def judge(reference: str, candidate: str) -> str:
    prompt = JUDGE_PROMPT.format(reference=reference, candidate=candidate, rubric_text=build_rubric_text())
    result = subprocess.run(
        ["claude", "-p"], input=prompt, capture_output=True, text=True, timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def parse_scores(judge_output: str) -> dict:
    scores = {}
    for key in RUBRIC:
        m = re.search(rf"==={key}===\s*점수:\s*(\d)\s*\n이유:\s*(.+)", judge_output)
        if m:
            scores[key] = {"score": int(m.group(1)), "reason": m.group(2).strip()}
    overall_m = re.search(r"===총평===\s*(.+)", judge_output, re.DOTALL)
    overall = overall_m.group(1).strip() if overall_m else ""
    return {"scores": scores, "overall_comment": overall, "raw": judge_output}


def main():
    reference_items = json.loads(REFERENCE_DATA.read_text(encoding="utf-8"))
    reference_text = format_reference(reference_items)

    model_files = sorted(MODEL_TEST_DIR.glob("*.md"))
    all_results = {}
    for f in model_files:
        model_name = f.stem
        print(f"=== {model_name} 채점 중... ===")
        candidate = f.read_text(encoding="utf-8")
        try:
            judge_output = judge(reference_text, candidate)
            parsed = parse_scores(judge_output)
            total = sum(v["score"] for v in parsed["scores"].values())
            parsed["total"] = total
            all_results[model_name] = parsed
            print(f"  총점: {total}/25")
        except Exception as e:
            print(f"  실패: {e}")
            all_results[model_name] = {"error": str(e)}

    out_path = ROOT / "paperwork" / "judge_results.json"
    out_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n완료: {out_path}")


if __name__ == "__main__":
    main()
