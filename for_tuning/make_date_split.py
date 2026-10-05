"""all_examples.jsonl을 날짜 단위로 나눠 train_v3/test_v3를 만든다.

같은 날짜의 예시(매크로·채권·섹터·투자전략)는 전부 학습 또는 전부 테스트에만 들어가도록 한다.
기존 train.jsonl/test.jsonl은 건드리지 않는다.
"""
import json
import random
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEST_RATIO = 0.2


def main():
    rows = [json.loads(l) for l in open(HERE / "all_examples.jsonl", encoding="utf-8")]
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["date"]].append(r)

    dates = sorted(by_date)
    random.Random(42).shuffle(dates)
    target = int(len(rows) * TEST_RATIO)

    test_dates, test_count = set(), 0
    for d in dates:
        if test_count >= target:
            break
        test_dates.add(d)
        test_count += len(by_date[d])

    train_rows = [r for d in dates if d not in test_dates for r in by_date[d]]
    test_rows = [r for d in dates if d in test_dates for r in by_date[d]]

    with open(HERE / "train_v3.jsonl", "w", encoding="utf-8") as f:
        for r in train_rows:
            f.write(json.dumps({"messages": r["messages"]}, ensure_ascii=False) + "\n")
    with open(HERE / "test_v3.jsonl", "w", encoding="utf-8") as f:
        for r in test_rows:
            f.write(json.dumps({"messages": r["messages"]}, ensure_ascii=False) + "\n")

    overlap = {r["date"] for r in train_rows} & {r["date"] for r in test_rows}
    print(f"train={len(train_rows)} test={len(test_rows)} test_dates={len(test_dates)} overlap_dates={len(overlap)}")


if __name__ == "__main__":
    main()
