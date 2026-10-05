"""v3 평가 결과(루브릭 총점 + 중복 문장 수 + 길이)를 모델별로 요약한다."""
import json
import re
import collections
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = [
    ("튜닝 전(base)", "eval_v3_base.jsonl"),
    ("v1b (3ep, lr 2e-4)", "eval_v3_v1b.jsonl"),
    ("v2b (2ep, lr 1e-4)", "eval_v3_v2b.jsonl"),
]


def dup_count(text: str) -> int:
    sents = [s.strip() for s in re.split(r"(?<=[.다])\s+", text) if len(s.strip()) > 25]
    return sum(v - 1 for v in collections.Counter(sents).values() if v > 1)


def main():
    lines = []
    for label, fname in RUNS:
        path = HERE / fname
        if not path.exists():
            lines.append(f"{label}: 결과 파일 없음 ({fname})")
            continue
        recs = [json.loads(l) for l in open(path, encoding="utf-8")]
        totals = [r["total"] for r in recs]
        dups = [dup_count(r["candidate"]) for r in recs]
        lens = [len(r["candidate"]) for r in recs]
        lines.append(
            f"{label}: n={len(recs)} 루브릭 평균={statistics.mean(totals):.2f}/25 "
            f"중복문장 평균={statistics.mean(dups):.1f} (최대 {max(dups)}) "
            f"길이 중앙값={int(statistics.median(lens))}자"
        )
    out = HERE.parent / "logs" / "v3_results.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
