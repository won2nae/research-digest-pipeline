"""네이버 파이낸셜 리서치 과거 데이터 전체 백필 (2008~현재).

기존 collect.py와 같은 파일 스키마(data/<날짜>/naver_<카테고리>.json)로 저장해서
vectorstore.py 등 나머지 파이프라인이 그대로 동작하게 한다.
공개 API를 대량 호출하므로 요청 사이에 짧은 대기를 둔다 (서버 부담 최소화).
"""
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
BASE_URL = "https://stock.naver.com/api/stockSecurity/researches/v2/{path}"
PAGE_SIZE = 20
SLEEP_SEC = 0.15  # 요청 간 대기 (공개 API에 대한 예의)

CATEGORIES = {
    "macro": "economy",
    "bond": "debenture",
    "sector": "industry",
    "strategy": "invest",
}
TAG_RE = re.compile(r"<[^>]+>")


def strip_html(html: str) -> str:
    text = TAG_RE.sub("", html or "")
    return text.replace("&nbsp;", " ").replace("&amp;", "&").strip()


def fetch_all(path: str, label: str, max_pages: int | None = None) -> list[dict]:
    """카테고리 전체를 페이지 끝까지 수집."""
    all_items = []
    page = 0
    while True:
        if max_pages is not None and page >= max_pages:
            break
        url = BASE_URL.format(path=path)
        resp = requests.get(url, headers=HEADERS, params={"index": page, "size": PAGE_SIZE}, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("items", [])
        if not items:
            break

        for item in items:
            all_items.append({
                "nid": item.get("nid"),
                "title": item.get("title"),
                "broker": item.get("brokerName"),
                "date": item.get("writeDate"),
                "content": strip_html(item.get("content", "")),
            })

        if page % 50 == 0:
            print(f"  [{label}] page {page} 완료, 누적 {len(all_items)}건 (마지막 날짜: {items[-1].get('writeDate')})")

        if not payload.get("hasNext", False):
            break
        page += 1
        time.sleep(SLEEP_SEC)
    return all_items


def save_by_date(label: str, items: list[dict]):
    by_date = defaultdict(list)
    for item in items:
        by_date[item["date"]].append(item)

    for date_str, day_items in by_date.items():
        out_dir = ROOT / "data" / date_str
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"naver_{label}.json"

        # 이미 파일이 있으면(당일 파이프라인이 먼저 만든 경우 등) nid 기준 병합
        existing = []
        if out_file.exists():
            try:
                existing = json.loads(out_file.read_text(encoding="utf-8"))
            except Exception:
                existing = []
        existing_ids = {e["nid"] for e in existing}
        merged = existing + [it for it in day_items if it["nid"] not in existing_ids]

        out_file.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    # 테스트용: 인자로 max_pages를 주면 카테고리당 그 페이지 수만큼만 수집
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else None

    for label, path in CATEGORIES.items():
        print(f"=== [{label}] 수집 시작 ===")
        items = fetch_all(path, label, max_pages=max_pages)
        print(f"[{label}] 총 {len(items)}건 수집, 날짜별로 저장 중...")
        save_by_date(label, items)
        dates = sorted({it["date"] for it in items})
        print(f"[{label}] 완료. 기간: {dates[0]} ~ {dates[-1]} ({len(dates)}일)\n")


if __name__ == "__main__":
    main()
