"""유명/우등생 투자자 추적 — 대량보유(지분) 공시를 투자자 이름으로 추적.

토스피드 글의 아이디어(DART 대량보유 공시로 유명 투자자가 어디 투자하는지
본다)를 자동화한 것. corp_code 없이 market-wide로 pblntf_ty=D(지분공시)를
날짜 범위로 받아서, 관심 투자자 명단(WATCHLIST)과 대조한다.

주의: "누가 언제 어느 회사에 공시를 냈다"는 사실만 보여준다. 증가/감소
방향이나 투자 판단은 제시하지 않음 — report_nm·날짜 비교로 어느 정도
추정 가능하지만, 정확한 지분율 변화는 공시 원문(PDF)을 봐야 함.
"""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dart_client import _get

ROOT = Path(__file__).resolve().parent.parent

# 관심 투자자/펀드 명단 (토스피드 글 예시 기반) — 자유롭게 추가/삭제
WATCHLIST = [
    "박영옥", "강방천", "최준철",
    "브이아이피자산운용", "에셋플러스자산운용", "VIP자산운용",
]


def fetch_holding_disclosures(bgn_de: str, end_de: str) -> list[dict]:
    """market-wide 지분공시(D) 전체를 페이지네이션해서 받아온다."""
    rows = []
    page = 1
    while True:
        data = _get("list.json", bgn_de=bgn_de, end_de=end_de, pblntf_ty="D", page_no=page, page_count=100)
        if data.get("status") != "000":
            break
        rows.extend(data.get("list", []))
        total_page = data.get("total_page", 1)
        if page >= total_page:
            break
        page += 1
    return rows


def main():
    days_back = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    end = date.today()
    begin = end - timedelta(days=days_back)
    rows = fetch_holding_disclosures(begin.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    print(f"[track_investors] 전체 지분공시 {len(rows)}건 ({begin}~{end})")

    hits = [r for r in rows if any(w in r.get("flr_nm", "") for w in WATCHLIST)]
    if not hits:
        print("관심 투자자 명단과 일치하는 공시 없음")
        return

    print(f"\n관심 투자자 공시 {len(hits)}건:")
    for r in sorted(hits, key=lambda r: r.get("rcept_dt", ""), reverse=True):
        print(f"- [{r.get('rcept_dt')}] {r.get('flr_nm')} -> {r.get('corp_name')}: {r.get('report_nm')}")


if __name__ == "__main__":
    main()
