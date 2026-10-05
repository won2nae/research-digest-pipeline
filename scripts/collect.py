"""전체 증권사 리서치 리포트 수집기 (소스별로 함수만 추가하면 됨).

현재 소스: 네이버 파이낸셜(API), 미래에셋증권(HTML+PDF Vision).
각 소스 함수는 {카테고리: [report, ...]} 형태로 반환하고,
main()이 data/<날짜>/<소스>_<카테고리>.json 으로 저장한다.
"""
import json
import re
import sys
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from pdf_ocr import extract_pdf_report

ROOT = Path(__file__).resolve().parent.parent
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


# ============================================================
# 네이버 파이낸셜 (stock.naver.com) - 공개 API, 로그인 불필요
# ============================================================
NAVER_CATEGORIES = {
    "macro": "economy",      # 매크로(경제)
    "bond": "debenture",     # 채권
    "sector": "industry",    # 산업 섹터별
    "strategy": "invest",    # 투자전략
}
NAVER_BASE_URL = "https://stock.naver.com/api/stockSecurity/researches/v2/{path}"
NAVER_PAGE_SIZE = 20
NAVER_MAX_PAGES = 10
TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    text = TAG_RE.sub("", html or "")
    return text.replace("&nbsp;", " ").replace("&amp;", "&").strip()


def _naver_fetch_today(path: str, today: str) -> list[dict]:
    items = []
    for page in range(NAVER_MAX_PAGES):
        url = NAVER_BASE_URL.format(path=path)
        resp = requests.get(url, headers=HEADERS, params={"index": page, "size": NAVER_PAGE_SIZE}, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        page_items = payload.get("items", [])
        if not page_items:
            break

        stop = False
        for item in page_items:
            if item.get("writeDate") == today:
                items.append({
                    "nid": item.get("nid"),
                    "title": item.get("title"),
                    "broker": item.get("brokerName"),
                    "date": item.get("writeDate"),
                    "content": _strip_html(item.get("content", "")),
                })
            elif item.get("writeDate", "9999-99-99") < today:
                stop = True  # 날짜 내림차순이므로 오늘보다 이전이 나오면 중단

        if stop or not payload.get("hasNext", False):
            break
    return items


def collect_naver(today: str) -> dict[str, list[dict]]:
    return {label: _naver_fetch_today(path, today) for label, path in NAVER_CATEGORIES.items()}


# ============================================================
# 미래에셋증권 (securities.miraeasset.com) - 정적 HTML + PDF Vision
# ============================================================
MIRAE_BROKER = "미래에셋증권"
MIRAE_LIST_URL = "https://securities.miraeasset.com/bbs/board/message/list.do"
# categoryId=1521은 확인된 게시판 하나. 카테고리별(매크로/채권/섹터/전략) 매핑은 추후 보강 필요.
MIRAE_CATEGORY_IDS = {"general": 1521}


def _mirae_fetch_list(category_id: int) -> list[dict]:
    resp = requests.get(MIRAE_LIST_URL, headers=HEADERS, params={"categoryId": category_id}, timeout=15)
    resp.encoding = "euc-kr"
    soup = BeautifulSoup(resp.text, "html.parser")

    items = []
    for row in soup.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        date_text = cells[0].get_text(strip=True)
        subject = cells[1].select_one(".subject a")
        if not subject:
            continue
        title = subject.get_text(" ", strip=True)
        pdf_link = cells[2].find("a", href=re.compile(r"downConfirm"))
        pdf_url = None
        if pdf_link:
            m = re.search(r"downConfirm\('([^']+)'", pdf_link["href"])
            if m:
                pdf_url = m.group(1)
        items.append({"date": date_text, "title": title, "pdf_url": pdf_url})
    return items


def collect_mirae(today: str) -> dict[str, list[dict]]:
    result = {}
    for label, category_id in MIRAE_CATEGORY_IDS.items():
        items = _mirae_fetch_list(category_id)
        today_items = [it for it in items if it["date"] == today and it["pdf_url"]]

        reports = []
        for it in today_items:
            try:
                report = extract_pdf_report(
                    it["pdf_url"], MIRAE_BROKER, fallback_title=it["title"], fallback_date=it["date"]
                )
                reports.append(report)
            except Exception as e:
                print(f"  [mirae-{label}] 실패 ({it['title'][:30]}): {e}")
        result[label] = reports
    return result


# ============================================================
# 오케스트레이션
# ============================================================
SOURCES = {
    "naver": collect_naver,
    "mirae": collect_mirae,
}


def main():
    today = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    out_dir = ROOT / "data" / today
    out_dir.mkdir(parents=True, exist_ok=True)

    for source_name, collect_fn in SOURCES.items():
        print(f"=== [{source_name}] 수집 시작 ===")
        categories = collect_fn(today)
        for label, items in categories.items():
            out_file = out_dir / f"{source_name}_{label}.json"
            out_file.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"[{source_name}-{label:8s}] {len(items):3d}건 -> {out_file}")


if __name__ == "__main__":
    main()
