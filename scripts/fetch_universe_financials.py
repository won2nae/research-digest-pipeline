"""유니버스(data/universe.json) 종목들의 DART 재무데이터를 대량 수집.

get_financial_summary()는 이미 회사별로 DART/<회사명>/financials_<year>_<reprt_code>.json
에 자동 캐시한다 (기존 DART 에이전트가 쓰는 것과 동일한 캐시). 여기서는 그
캐시가 없는 (년도, 분기) 조합만 새로 호출해서 재시도 가능하게 한다.

분기보고서를 아직 안 낸 회사·기간은 조회 결과가 비어있을 수 있다 (정상).
"""
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dart_client import get_financial_summary, _safe_name, DART_ARCHIVE

ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_PATH = ROOT / "data" / "universe.json"
REPRT_CODES = ("11013", "11012", "11014", "11011")  # 1분기/반기/3분기/연간


def main():
    import json
    market = sys.argv[1] if len(sys.argv) > 1 else "KOSPI"
    years_back = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    universe = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    targets = [c for c in universe if c["market"] == market]
    this_year = date.today().year
    years = [str(y) for y in range(this_year - years_back, this_year + 1)]
    print(f"[fetch_financials] {market} {len(targets)}개 종목 x {len(years)}개 연도 x {len(REPRT_CODES)}개 기간")

    done, skipped, empty, failed = 0, 0, 0, 0
    for i, c in enumerate(targets):
        for year in years:
            for reprt_code in REPRT_CODES:
                cache_path = DART_ARCHIVE / _safe_name(c["name"]) / f"financials_{year}_{reprt_code}.json"
                if cache_path.exists():
                    skipped += 1
                    continue
                try:
                    rows = get_financial_summary(c["name"], year, reprt_code)
                    if rows:
                        done += 1
                    else:
                        empty += 1
                except Exception as e:
                    print(f"  [{c['name']} {year} {reprt_code}] 실패: {e}", file=sys.stderr)
                    failed += 1
                time.sleep(0.1)
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(targets)}개 기업 (신규 {done}, 스킵 {skipped}, 데이터없음 {empty}, 실패 {failed})")

    print(f"[fetch_financials] 완료: 신규 {done}, 스킵 {skipped}, 데이터없음 {empty}, 실패 {failed}")


if __name__ == "__main__":
    main()
