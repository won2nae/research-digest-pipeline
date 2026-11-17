"""유니버스(data/universe.json) 종목들의 과거 일별 가격(OHLCV)을 pykrx로 수집.

pykrx의 "일괄 조회" 함수(시가총액 순위, 인덱스 구성종목 등)는 최근 KRX
로그인이 있어야만 되게 막혔지만(2026-11-14 확인), "특정 종목의 기간별
시세"(get_market_ohlcv_by_date)는 로그인 없이도 정상 동작한다 — 이 스크립트는
그 방식만 쓴다.

종목당 1건 저장: data/prices/<stock_code>.json (날짜별 OHLCV 리스트).
오래 걸려서(수백 종목) 중간 저장하며 이어서 돌 수 있게 이미 받은 종목은
건너뛴다 (재실행 안전).
"""
import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
from pykrx import stock

ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_PATH = ROOT / "data" / "universe.json"
PRICE_DIR = ROOT / "data" / "prices"


def main():
    market = sys.argv[1] if len(sys.argv) > 1 else "KOSPI"
    years_back = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    universe = json.loads(UNIVERSE_PATH.read_text(encoding="utf-8"))
    targets = [c for c in universe if c["market"] == market]
    print(f"[fetch_prices] {market} {len(targets)}개 종목, 최근 {years_back}년")

    from datetime import date
    end = date.today()
    begin = date(end.year - years_back, end.month, end.day)
    fromdate, todate = begin.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    done, skipped, failed = 0, 0, 0
    for i, c in enumerate(targets):
        out_path = PRICE_DIR / f"{c['stock_code']}.json"
        if out_path.exists():
            skipped += 1
            continue
        try:
            df = stock.get_market_ohlcv_by_date(fromdate, todate, c["stock_code"])
            if df.empty:
                failed += 1
                continue
            rows = [
                {"date": idx.strftime("%Y-%m-%d"), "open": int(r["시가"]), "high": int(r["고가"]),
                 "low": int(r["저가"]), "close": int(r["종가"]), "volume": int(r["거래량"])}
                for idx, r in df.iterrows()
            ]
            out_path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            done += 1
        except Exception as e:
            print(f"  [{c['name']}] 실패: {e}", file=sys.stderr)
            failed += 1
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(targets)} (완료 {done}, 스킵 {skipped}, 실패 {failed})")
        time.sleep(0.15)

    print(f"[fetch_prices] 완료: 신규 {done}, 기존 스킵 {skipped}, 실패 {failed} -> {PRICE_DIR}")


if __name__ == "__main__":
    main()
