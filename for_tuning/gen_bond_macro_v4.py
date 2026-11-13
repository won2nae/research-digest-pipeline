"""채권·매크로 정답을 v3 때보다 더 다양한 문체로 다시 생성한다.

v3에서 넣은 인과 검증 규칙 자체는 좋았지만("경로", "전제" 같은 단어를 쓰라고 한 게
아니라 "방향+전제조건을 같이 써라"는 요구였는데), 모델이 거기 수렴해서 "이 경로가
작동하기 위한 전제 조건은..." 같은 고정 문구를 반복했다 (49건 중 다수).

이번엔 두 가지를 바꾼다.
1. 인과 규칙에서 "경로/전제" 같은 특정 단어 사용을 요구하지 않고, 요구사항(방향+전제조건
   +반대방향 가능성)만 서술한다 - 단어 자체를 금지 목록에도 넣는다.
2. 예시마다 서로 다른 "글쓰기 틀"을 코드로 배정한다. 같은 호출이라도 모델이 과거에
   뭘 썼는지 알 수 없으니, "다양하게 써라"라고만 하면 결국 자기만의 새 상투 표현으로
   수렴한다. 그래서 예시 인덱스 기준으로 4가지 문체 중 하나를 고정 배정해서 애초에
   문체가 겹치지 않게 만든다.

학습 입력(user 메시지)은 기존 all_examples.jsonl의 것을 그대로 쓰고, 정답(assistant)만
새로 만든다. 결과는 gold_bond_macro_v4.jsonl에 저장하며, 이미 만든 (날짜, 카테고리)는
건너뛴다.
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
OUT = HERE / "gold_bond_macro_v4.jsonl"
TARGET_CATEGORIES = {"bond", "macro"}
CATEGORY_LABELS = {"macro": "매크로(경제)", "bond": "채권"}
CLAUDE_BIN = shutil.which("claude") or "/usr/local/bin/claude"

CAUSAL_RULE = """
**추가 제약 3 — 인과 방향 검증 (채권·매크로 필수)**:
금리·환율·물가·성장과 관련된 인과 주장을 쓸 때는 다음을 지켜라.
- 인과 주장을 할 때는 방향(오른다/내린다 등)과, 그 방향이 성립하려면 어떤 상황이
  맞아떨어져야 하는지를 함께 밝혀라. 단, 이를 표현하는 고정된 틀이나 반복되는 단어를
  쓰지 마라 — 아래 "이번 글의 문체" 지시를 따라 매번 다르게 풀어써라.
- 같은 원인이 반대 방향으로도 작용할 수 있으면(예: 국채 발행 감소는 공급 측면에서는
  금리 하락 압력이지만, 재정 건전성 개선 신호로는 금리 상승 요인이 될 수 있음) 두
  가능성을 모두 짚고 어느 쪽이 우세한지 근거와 함께 판단해라.
- 리포트가 주장하는 인과의 방향이 기본 원리(수급, 기준금리 경로 기대, 기간 프리미엄,
  물가 기대 등)와 어긋나면, 어긋나는 지점과 빠진 전제를 짚어라.
- 채권 가격과 금리는 역의 관계이고, 국고채 금리는 기준금리 경로에 대한 기대에 크게
  좌우된다는 걸 판단의 기본 틀로 쓰되, 모든 상황에 자동 적용하지 말고 원문 근거와
  함께 써라. 발행 규모(공급) 변화의 금리 효과는 실증적으로 작고 조건부라는 점도
  고려해 단정하지 마라.
- **절대 쓰면 안 되는 표현**: "이 경로가 작동하기 위한", "작동하기 위한 전제 조건은",
  "전제 조건은", "인과 경로:", "(방향: +)", "방향: -". 그리고 "경로"·"전제"라는
  단어 자체도 문단마다 반복해서 쓰지 마라.
"""

VOICE_PRESETS = [
    {
        "name": "질문-답변형",
        "instruction": (
            "이번 글은 핵심 의문을 먼저 던지고 그에 답하는 방식으로 전개해라. "
            "예: '그렇다면 왜 이런 일이 벌어졌는가' 같은 질문을 던진 뒤, 데이터와 "
            "논리로 단계적으로 풀어가라. 결론을 먼저 말하고 설명하는 방식은 피해라."
        ),
    },
    {
        "name": "데이터 연쇄형",
        "instruction": (
            "이번 글은 짧고 단정적인 문장으로, 수치를 연쇄적으로 제시하며 그 사이의 "
            "인과만 간결하게 붙여가는 방식으로 써라. 긴 복문보다는 짧은 문장을 여러 개 "
            "이어 붙이는 리듬을 써라."
        ),
    },
    {
        "name": "비교대조형",
        "instruction": (
            "이번 글은 두 개 이상의 시각이나 수치를 먼저 나란히 제시한 뒤, 그 차이를 "
            "비교하면서 종합하는 방식으로 써라. 한쪽을 먼저 설명하고 다른 쪽을 "
            "나중에 반박하는 식이 아니라, 처음부터 병렬로 놓고 대조해라."
        ),
    },
    {
        "name": "내러티브형",
        "instruction": (
            "이번 글은 사건이 벌어진 시간 순서를 따라가며 서술해라 (예: 주 초반에는 "
            "~했고, 중반 들어 ~로 바뀌었다). 전개 과정 자체를 보여주면서 그 안에서 "
            "인과를 짚어라."
        ),
    },
]


def load_teacher_template() -> str:
    text = (HERE / "_run_generation.py").read_text(encoding="utf-8")
    m = re.search(r'TEACHER_PROMPT = """(.*?)"""', text, re.S)
    if not m:
        raise RuntimeError("TEACHER_PROMPT를 _run_generation.py에서 찾지 못함")
    template = m.group(1)
    marker = "--- 리포트 원문 ---"
    if marker not in template:
        raise RuntimeError("프롬프트 구분자를 찾지 못함")
    return template, marker


def build_prompt(template: str, marker: str, voice: dict) -> str:
    voice_block = f"\n**이번 글의 문체 ({voice['name']})**:\n{voice['instruction']}\n"
    return template.replace(marker, CAUSAL_RULE + voice_block + "\n" + marker, 1)


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
    template, marker = load_teacher_template()
    rows = [json.loads(l) for l in open(SRC, encoding="utf-8")]
    targets = [r for r in rows if r["category"] in TARGET_CATEGORIES]
    done = load_done()
    print(f"대상 {len(targets)}건, 이미 완료 {len(done)}건", flush=True)

    for i, row in enumerate(targets, 1):
        key = (row["date"], row["category"])
        if key in done:
            continue
        date, cat = row["date"], row["category"]
        voice = VOICE_PRESETS[i % len(VOICE_PRESETS)]
        reports = load_reports(ROOT / "data" / date, cat)
        history = historical_context(reports, cat, date)
        teacher = build_prompt(template, marker, voice).format(
            today=date, label=CATEGORY_LABELS[cat],
            content=format_reports(reports), history=history,
        )
        if dry_run:
            print(f"[dry] {i}/{len(targets)} {key} voice={voice['name']} prompt_chars={len(teacher)}", flush=True)
            if i >= 4:
                break
            continue
        print(f"[{i}/{len(targets)}] {key} voice={voice['name']} 생성 중", flush=True)
        gold = call_claude(teacher)
        record = {
            "date": date,
            "category": cat,
            "num_reports": row.get("num_reports"),
            "voice": voice["name"],
            "messages": [row["messages"][0], {"role": "assistant", "content": gold}],
        }
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print("완료", flush=True)


if __name__ == "__main__":
    main(dry_run="--dry" in sys.argv)
