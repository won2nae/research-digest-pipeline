"""상장사 유니버스(코스피/코스닥 구분) 구축.

pykrx의 KOSPI200 구성종목·시가총액 일괄조회 함수가 최근 KRX 로그인
(KRX_ID/KRX_PW)이 있어야만 되게 막혀서(2026-11-14 확인, 로그인 정보 없음),
대신 이미 쓰고 있는 DART API(company.json)의 corp_cls 필드로 코스피/코스닥을
직접 분류한다. data/dart_corp_codes.json(상장사 3,979개) 전체를 순회 — 시간이
오래 걸려서 백그라운드로 돌린다.

corp_cls: Y=코스피(유가증권), K=코스닥, N=코넥스, E=기타
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dart_client import _get, load_corp_codes

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "universe.json"


def main():
    codes = load_corp_codes()
    names = sorted(codes.keys())
    total = len(names)
    print(f"[build_universe] 전체 {total}개 기업 분류 시작")

    universe = []
    counts = {"Y": 0, "K": 0, "N": 0, "E": 0, "실패": 0}
    for i, name in enumerate(names):
        info = codes[name]
        try:
            data = _get("company.json", corp_code=info["corp_code"])
            cls = data.get("corp_cls", "") if data.get("status") == "000" else ""
        except Exception:
            cls = ""
        if cls in counts:
            counts[cls] += 1
        else:
            counts["실패"] += 1
        universe.append({
            "name": name, "corp_code": info["corp_code"], "stock_code": info["stock_code"],
            "market": {"Y": "KOSPI", "K": "KOSDAQ", "N": "KONEX", "E": "기타"}.get(cls, "미확인"),
        })
        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{total} 처리 (KOSPI {counts['Y']}, KOSDAQ {counts['K']})")
            OUT_PATH.write_text(json.dumps(universe, ensure_ascii=False, indent=2), encoding="utf-8")
        time.sleep(0.05)

    OUT_PATH.write_text(json.dumps(universe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build_universe] 완료: {OUT_PATH}")
    print(f"  KOSPI {counts['Y']}개, KOSDAQ {counts['K']}개, KONEX {counts['N']}개, 기타 {counts['E']}개, 분류실패 {counts['실패']}개")


if __name__ == "__main__":
    main()
