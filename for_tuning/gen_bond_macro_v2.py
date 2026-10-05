"""채권·매크로 정답을 인과 검증 규칙을 넣은 교사 프롬프트로 다시 생성한다.

학습 입력(user 메시지)은 기존 all_examples.jsonl의 것을 그대로 쓰고, 정답(assistant)만 새로 만든다.
결과는 gold_bond_macro_v2.jsonl에 한 줄씩 저장하며, 이미 만든 (날짜, 카테고리)는 건너뛴다.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

from summarize import historical_context, format_reports, load_reports  # noqa: E402

SRC = HERE / "all_examples.jsonl"
OUT = HERE / "gold_bond_macro_v2.jsonl"
TARGET_CATEGORIES = {"bond", "macro"}
CATEGORY_LABELS = {"macro": "매크로(경제)", "bond": "채권"}
CLAUDE_BIN = shutil.which("claude") or "/usr/local/bin/claude"

CAUSAL_RULE = """
**추가 제약 3 — 인과 방향 검증 (채권·매크로 필수)**:
금리·환율·물가·성장과 관련된 인과 주장을 쓸 때는 다음을 지켜라.
- 각 인과 주장은 (원인 → 전달 경로 → 결과)와 **방향(부호)**을 명시하고, 그 경로가 작동하기 위한 **전제 조건**을 함께 써라.
- 같은 원인이 반대 방향의 경로도 가질 수 있으면(예: 국채 발행 감소는 공급 측면에서는 금리 하락 압력이지만, 재정 건전성 개선 신호로는 금리 상승 요인이 될 수 있음) 두 경로를 모두 쓰고, 어느 쪽이 우세한지 근거와 함께 판단해라.
- 리포트가 주장하는 인과의 방향이 기본 원리(수급, 기준금리 경로 기대, 기간 프리미엄, 물가 기대 등)와 어긋나면, 어긋나는 지점을 명시하고 빠진 전제가 무엇인지 짚어라.
- 채권 가격과 금리는 역의 관계이고, 국고채 금리는 기준금리 경로에 대한 기대에 크게 좌우된다. 이것을 판단의 기본 틀로 쓰되, 모든 상황에 자동으로 적용하지 말고 원문 근거와 함께 써라.
- 발행 규모(공급) 변화가 금리에 미치는 효과는 실증적으로 크기가 작고 조건에 따라 달라진다. 이 점을 고려해 단정하지 마라.
"""


def load_teacher_template() -> str:
    text = (HERE / "_run_generation.py").read_text(encoding="utf-8")
    m = re.search(r'TEACHER_PROMPT = """(.*?)"""', text, re.S)
    if not m:
        raise RuntimeError("TEACHER_PROMPT를 _run_generation.py에서 찾지 못함")
    template = m.group(1)
    marker = "--- 리포트 원문 ---"
    if marker not in template:
        raise RuntimeError("프롬프트 구분자를 찾지 못함")
    return template.replace(marker, CAUSAL_RULE + "\n" + marker, 1)


def call_claude(prompt: str) -> str:
    result = subprocess.run([CLAUDE_BIN, "-p"], input=prompt, capture_output=True, text=True, timeout=600)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"claude -p 실패 (rc={result.returncode}): {result.stderr[:300]}")
    return result.stdout.strip()


def load_done() -> set:
    if not OUT.exists():
        return set()
    return {(json.loads(l)["date"], json.loads(l)["category"]) for l in open(OUT, encoding="utf-8")}


def main(dry_run: bool = False):
    template = load_teacher_template()
    rows = [json.loads(l) for l in open(SRC, encoding="utf-8")]
    targets = [r for r in rows if r["category"] in TARGET_CATEGORIES]
    done = load_done()
    print(f"대상 {len(targets)}건, 이미 완료 {len(done)}건", flush=True)

    for i, row in enumerate(targets, 1):
        key = (row["date"], row["category"])
        if key in done:
            continue
        date, cat = row["date"], row["category"]
        reports = load_reports(ROOT / "data" / date, cat)
        history = historical_context(reports, cat, date)
        teacher = template.format(
            today=date, label=CATEGORY_LABELS[cat],
            content=format_reports(reports), history=history,
        )
        if dry_run:
            print(f"[dry] {i}/{len(targets)} {key} prompt_chars={len(teacher)}", flush=True)
            if i >= 2:
                break
            continue
        print(f"[{i}/{len(targets)}] {key} 생성 중", flush=True)
        gold = call_claude(teacher)
        record = {
            "date": date,
            "category": cat,
            "num_reports": row.get("num_reports"),
            "messages": [row["messages"][0], {"role": "assistant", "content": gold}],
        }
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print("완료", flush=True)


if __name__ == "__main__":
    main(dry_run="--dry" in sys.argv)
