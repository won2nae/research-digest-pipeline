"""카테고리 그룹(macro_bond / sector_strategy)별로 날짜 단위 train/test 분할을 만든다.

macro_bond는 gold_bond_macro_v4.jsonl(49건, 문체 다양화 적용판)을 쓰고,
sector_strategy는 all_examples.jsonl에서 그대로 가져온다(품질 문제 없었음).
같은 날짜의 예시가 train/test 양쪽에 섞이지 않도록 날짜 단위로 나눈다.
"""
import json
import random
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEST_RATIO = 0.2


def split_and_write(rows: list[dict], name: str, seed: int = 42):
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["date"]].append(r)

    dates = sorted(by_date)
    random.Random(seed).shuffle(dates)
    target = int(len(rows) * TEST_RATIO)

    test_dates, test_count = set(), 0
    for d in dates:
        if test_count >= target:
            break
        test_dates.add(d)
        test_count += len(by_date[d])

    train_rows = [r for d in dates if d not in test_dates for r in by_date[d]]
    test_rows = [r for d in dates if d in test_dates for r in by_date[d]]

    (HERE / f"train_{name}.jsonl").write_text(
        "\n".join(json.dumps({"messages": r["messages"]}, ensure_ascii=False) for r in train_rows) + "\n",
        encoding="utf-8",
    )
    (HERE / f"test_{name}.jsonl").write_text(
        "\n".join(json.dumps({"messages": r["messages"]}, ensure_ascii=False) for r in test_rows) + "\n",
        encoding="utf-8",
    )
    overlap = {r["date"] for r in train_rows} & {r["date"] for r in test_rows}
    print(f"[{name}] train={len(train_rows)} test={len(test_rows)} test_dates={len(test_dates)} overlap={len(overlap)}")


def main():
    macro_bond = [json.loads(l) for l in open(HERE / "gold_bond_macro_v4.jsonl", encoding="utf-8")]
    all_ex = [json.loads(l) for l in open(HERE / "all_examples.jsonl", encoding="utf-8")]
    sector_strategy = [r for r in all_ex if r["category"] in ("sector", "strategy")]

    split_and_write(macro_bond, "macro_bond")
    split_and_write(sector_strategy, "sector_strategy")


if __name__ == "__main__":
    main()
