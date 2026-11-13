"""카테고리 그룹 분리 학습 결과(루브릭 + 반복 문장 수)를 요약한다."""
import json
import re
import collections
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = [
    ("macro_bond", "base", "eval_group_base_macro_bond.jsonl"),
    ("macro_bond", "tuned", "eval_group_tuned_macro_bond.jsonl"),
    ("sector_strategy", "base", "eval_group_base_sector_strategy.jsonl"),
    ("sector_strategy", "tuned", "eval_group_tuned_sector_strategy.jsonl"),
]


def dup_count(text: str) -> int:
    sents = [s.strip() for s in re.split(r"(?<=[.다])\s+", text) if len(s.strip()) > 25]
    return sum(v - 1 for v in collections.Counter(sents).values() if v > 1)


def main():
    lines = []
    for group, tag, fname in RUNS:
        path = HERE / fname
        if not path.exists():
            lines.append(f"{group}/{tag}: 결과 파일 없음 ({fname})")
            continue
        recs = [json.loads(l) for l in open(path, encoding="utf-8")]
        totals = [r["total"] for r in recs]
        dups = [dup_count(r["candidate"]) for r in recs]
        lines.append(
            f"{group:16s} {tag:6s}: n={len(recs)} 루브릭 평균={statistics.mean(totals):.2f}/25 "
            f"중복문장 평균={statistics.mean(dups):.1f}(최대 {max(dups)})"
        )
    out = HERE.parent / "logs" / "group_eval_results.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
