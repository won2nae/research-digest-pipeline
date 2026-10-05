"""튜닝 후(LoRA adapter 적용) Qwen3-14B 평가.

eval_baseline.py와 동일한 test.jsonl(32건)·동일 루브릭으로 채점하되, 모델만
local_llm_tuned.py(LoRA adapter 적용판)로 교체해서 튜닝 전/후를 공정 비교한다.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_llm_tuned import ask_tuned as ask_local

TEST_FILE = Path(__file__).resolve().parent / "test.jsonl"
MODEL_NAME = "Qwen/Qwen3-14B+LoRA"  # 표기용, 실제 로드는 local_llm_tuned.py가 처리
CLAUDE_BIN = shutil.which("claude") or "/usr/local/bin/claude"

RUBRIC = {
    "정확성": "원문 리포트의 수치·사실과 일치하는가. 없는 내용을 지어내거나(환각) 수치를 잘못 옮기지 않았는가.",
    "분석적_종합": "단순히 '증권사가 이렇게 말했다'는 나열이 아니라, 여러 리포트의 근거를 하나의 경제적 논리(인과관계·메커니즘)로 엮어냈는가.",
    "교차비교": "증권사 간 시각/해석 차이가 있을 때 이를 실제로 포착하고, 왜 다른지 설명했는가. (근거 없는 추상적 비판이 아니라 구체적 대조인가)",
    "구조_가독성": "소제목 구성, 문단 흐름, 마크다운 구조가 읽기 좋은가. 불필요한 반복이나 어색한 문장은 없는가.",
    "완결성": "원문에 있는 핵심 이슈를 빠짐없이 다뤘는가. 중요한 내용이 누락되지 않았는가.",
}

JUDGE_PROMPT = """너는 금융 리서치 요약의 품질을 평가하는 채점자다.
아래 "원본 프롬프트"(리포트 원문 포함)를 바탕으로 "평가 대상 요약"이 얼마나 잘 작성됐는지, 주어진 루브릭에 따라 채점해라.

--- 원본 프롬프트(리포트 원문 포함) ---
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


def build_rubric_text() -> str:
    return "\n".join(f"- {k}: {v}" for k, v in RUBRIC.items())


def judge(reference: str, candidate: str) -> str:
    prompt = JUDGE_PROMPT.format(reference=reference, candidate=candidate, rubric_text=build_rubric_text())
    result = subprocess.run([CLAUDE_BIN, "-p"], input=prompt, capture_output=True, text=True, timeout=180)
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
    out_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "tuned_eval.jsonl"
    examples = [json.loads(l) for l in open(TEST_FILE, encoding="utf-8")]

    done_idx = set()
    if out_file.exists():
        for line in open(out_file, encoding="utf-8"):
            done_idx.add(json.loads(line)["index"])
    print(f"이미 완료: {len(done_idx)}/{len(examples)}")

    with open(out_file, "a", encoding="utf-8") as f:
        for i, ex in enumerate(examples):
            if i in done_idx:
                continue
            student_prompt = ex["messages"][0]["content"]
            print(f"[{i + 1}/{len(examples)}] 생성 중...")
            try:
                candidate = ask_local(student_prompt, max_new_tokens=3000)
                judge_output = judge(student_prompt, candidate)
                parsed = parse_scores(judge_output)
                total = sum(v["score"] for v in parsed["scores"].values())
                record = {"index": i, "candidate": candidate, "judge": parsed, "total": total}
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                print(f"  총점: {total}/25")
            except Exception as e:
                print(f"  실패: {e}")

    # 요약 통계
    all_records = [json.loads(l) for l in open(out_file, encoding="utf-8")]
    totals = [r["total"] for r in all_records]
    if totals:
        print(f"\n=== 튜닝 후 평가 요약 ({len(totals)}건) ===")
        print(f"평균: {sum(totals) / len(totals):.2f}/25")
        print(f"최고/최저: {max(totals)}/{min(totals)}")


if __name__ == "__main__":
    main()
