"""지수·환율·원자재·금리의 장기 과거 데이터를 받아 site/assets/history.json으로 굽는다.

한국 지수(코스피·코스닥)는 네이버 자체 차트 API, 나머지(미국 지수·환율·원자재·금리)는
Yahoo Finance 비공식 공개 API를 쓴다 (조사 결과 둘 다 이게 각 지표별 최대 과거 범위였음).
한국 10년물 금리는 무료로 과거 데이터를 주는 소스를 못 찾아서 제외한다 (현재값만 표시).

월별 데이터만 받는다 - 수십 년치를 일별로 받으면 사이트에 싣기엔 너무 크고,
장기 추이를 보는 용도에는 월별로 충분하다. 최근 구간(일별)은 기존 파이프라인이
매일 쌓는 데이터로 사이트에서 이어붙인다 (build_site.py 참고).

수동으로 가끔 재실행하면 된다 (cron에 넣지 않음 - 월별 데이터라 매일 바뀌지 않음).
"""
import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "site" / "assets" / "history.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Yahoo Finance 심볼 매핑 (조사 결과 확인된 최대 과거 범위는 각기 다름).
# 네이버 자체 차트 API도 시도해봤으나 메타데이터는 1990년부터라고 하면서
# 실제로는 최근 10년(120개월)만 내려줘서, 소스를 Yahoo 하나로 통일했다.
YAHOO_SYMBOLS = {
    "KOSPI": "%5EKS11",
    "KOSDAQ": "%5EKQ11",
    ".DJI": "%5EDJI",
    ".INX": "%5EGSPC",
    ".IXIC": "%5EIXIC",
    "US10YT=RR": "%5ETNX",
    "FX_USDKRW": "KRW=X",
    "GCcv1": "GC=F",
    "CLcv1": "CL=F",
}


def fetch_yahoo(symbol: str) -> list[tuple[str, float]]:
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    resp = requests.get(
        url, headers=HEADERS,
        params={"period1": 0, "period2": 2000000000, "interval": "1mo"},
        timeout=15,
    )
    data = resp.json()
    result = data["chart"]["result"][0]
    ts = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]
    points = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        from datetime import date as _date
        d = _date.fromtimestamp(t).isoformat()
        points.append((d, round(float(c), 4)))
    return points


def main():
    history = {}

    for code, symbol in YAHOO_SYMBOLS.items():
        print(f"[yahoo] {code} ({symbol}) 받는 중...")
        try:
            pts = fetch_yahoo(symbol)
            print(f"  -> {len(pts)}건, 첫 날짜 {pts[0][0] if pts else '-'}")
            history[code] = pts
        except Exception as e:
            print(f"  실패: {e}")
        time.sleep(0.5)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    print(f"\n완료: {OUT} ({OUT.stat().st_size / 1024:.0f}KB)")


if __name__ == "__main__":
    main()
