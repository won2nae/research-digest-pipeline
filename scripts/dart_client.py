"""DART(전자공시시스템) Open API 클라이언트.

기업명 -> corp_code 매핑, 공시검색, 재무정보 조회를 제공한다.
API 키는 /home/kjw/kjw/.env 의 DART_API_KEY에서 읽는다 (git에 안 올라가는 파일).
"""
import io
import json
import re
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = Path("/home/kjw/kjw/.env")
CORP_CODE_CACHE = ROOT / "data" / "dart_corp_codes.json"
DART_ARCHIVE = ROOT / "DART"  # 회사별로 조회한 원본 공시·재무정보를 그대로 쌓아두는 아카이브
BASE_URL = "https://opendart.fss.or.kr/api"


def _safe_name(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_.-]", "_", name)


def _archive_write(corp_name: str, filename: str, data) -> None:
    """DART API에서 조회한 원본 응답을 회사별 폴더에 그대로 저장한다.
    같은 조건으로 다시 조회하면 덮어쓰기만 하고, 조건(기간/연도 등)이 다르면
    파일명이 달라서 계속 쌓인다."""
    d = DART_ARCHIVE / _safe_name(corp_name)
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_api_key() -> str:
    text = ENV_FILE.read_text(encoding="utf-8")
    m = re.search(r"^DART_API_KEY\s*=\s*(\S+)", text, re.MULTILINE)
    if not m:
        raise RuntimeError(f"{ENV_FILE}에서 DART_API_KEY를 찾지 못함")
    return m.group(1).strip("'\"")


API_KEY = _load_api_key()


def _get(path: str, **params) -> dict:
    params["crtfc_key"] = API_KEY
    resp = requests.get(f"{BASE_URL}/{path}", params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _build_corp_code_cache() -> dict[str, dict]:
    """corpCode.xml(전체 상장사 매핑, zip)을 받아 기업명 -> {corp_code, stock_code} 캐시로 저장."""
    resp = requests.get(f"{BASE_URL}/corpCode.xml", params={"crtfc_key": API_KEY}, timeout=30)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        xml_text = zf.read("CORPCODE.xml").decode("utf-8")

    mapping = {}
    for block in re.findall(r"<list>(.*?)</list>", xml_text, re.S):
        def field(tag):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", block)
            return m.group(1).strip() if m else ""
        name = field("corp_name")
        stock_code = field("stock_code")
        corp_code = field("corp_code")
        if name and stock_code:  # 상장사만 (비상장은 stock_code가 빔)
            mapping[name] = {"corp_code": corp_code, "stock_code": stock_code}

    CORP_CODE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    CORP_CODE_CACHE.write_text(json.dumps(mapping, ensure_ascii=False), encoding="utf-8")
    return mapping


def load_corp_codes() -> dict[str, dict]:
    if CORP_CODE_CACHE.exists():
        return json.loads(CORP_CODE_CACHE.read_text(encoding="utf-8"))
    return _build_corp_code_cache()


def find_corp(company_name: str) -> dict | None:
    """기업명으로 corp_code를 찾는다. 정확히 일치하는 게 없으면 포함 검색으로 재시도."""
    codes = load_corp_codes()
    if company_name in codes:
        return {"name": company_name, **codes[company_name]}
    candidates = [n for n in codes if company_name in n or n in company_name]
    if len(candidates) == 1:
        return {"name": candidates[0], **codes[candidates[0]]}
    if candidates:
        # 가장 이름이 짧은 걸 우선 (정식 상호명일 가능성이 높음)
        best = min(candidates, key=len)
        return {"name": best, **codes[best]}
    return None


def search_disclosures(company_name: str, bgn_de: str, end_de: str, page_count: int = 20) -> list[dict]:
    """최근 공시 목록. bgn_de/end_de는 YYYYMMDD.

    매일 겹치는 30일 롤링 윈도우라 쌓아둬도 누적 가치가 없어서 아카이브에는
    저장하지 않는다 (재무정보와 달리 매번 거의 같은 내용이 다시 조회됨)."""
    corp = find_corp(company_name)
    if not corp:
        return []
    data = _get("list.json", corp_code=corp["corp_code"], bgn_de=bgn_de, end_de=end_de, page_count=page_count)
    if data.get("status") != "000":
        return []
    return data.get("list", [])


REPRT_LABELS = {"11013": "1분기(1~3월 누적)", "11012": "반기(1~6월 누적)", "11014": "3분기(1~9월 누적)", "11011": "연간"}


def list_cached_financials(company_name: str) -> list[dict]:
    """이 회사에 대해 지금까지 조회해서 쌓인 재무정보 전체를 기간순으로 반환한다.
    DART_ARCHIVE에 회사를 조회할 때마다 자동으로 쌓이므로(get_financial_summary),
    파이프라인이 매일 돌수록 같은 회사의 여러 분기가 자연스럽게 모인다.
    각 보고서는 당기 하나의 스냅샷이고 분기값이 '해당 분기까지 누적'이라 결과에
    reprt_code 라벨을 그대로 남겨 호출하는 쪽이 누적 여부를 헷갈리지 않게 한다."""
    corp = find_corp(company_name)
    if not corp:
        return []
    d = DART_ARCHIVE / _safe_name(corp["name"])
    if not d.exists():
        return []
    key_accounts = {"자산총계", "부채총계", "자본총계", "매출액", "영업이익"}
    net_income_names = {"당기순이익", "반기순이익", "분기순이익"}
    periods = []
    for f in sorted(d.glob("financials_*.json")):
        m = re.match(r"financials_(\d{4})_(\d{5})\.json", f.name)
        if not m:
            continue
        year, reprt_code = m.groups()
        rows = json.loads(f.read_text(encoding="utf-8"))
        amounts = {}
        for r in rows:
            name = r.get("account_nm", "")
            sj = r.get("sj_div", "")
            if sj == "BS" and name in key_accounts:
                amounts[name] = r.get("thstrm_amount")
            elif sj in ("IS", "CIS") and (name in key_accounts or name in net_income_names):
                amounts["당기순이익" if name in net_income_names else name] = r.get("thstrm_amount")
        if amounts:
            periods.append({
                "year": year, "reprt_code": reprt_code,
                "label": f"{year} {REPRT_LABELS.get(reprt_code, reprt_code)}",
                **amounts,
            })
    # reprt_code는 숫자 순서가 분기 순서와 다름 (11013=1분기, 11012=반기, 11014=3분기, 11011=연간)
    reprt_order = {"11013": 0, "11012": 1, "11014": 2, "11011": 3}
    periods.sort(key=lambda p: (p["year"], reprt_order.get(p["reprt_code"], 9)))
    return periods


def get_financial_summary(company_name: str, year: str, reprt_code: str = "11013") -> list[dict]:
    """주요계정 재무정보. reprt_code: 11013=1분기, 11012=반기, 11014=3분기, 11011=사업보고서(연간)."""
    corp = find_corp(company_name)
    if not corp:
        return []
    data = _get(
        "fnlttSinglAcntAll.json", corp_code=corp["corp_code"], bsns_year=year,
        reprt_code=reprt_code, fs_div="CFS",
    )
    if data.get("status") != "000":
        return []
    rows = data.get("list", [])
    _archive_write(corp["name"], f"financials_{year}_{reprt_code}.json", rows)
    return rows


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "삼성전자"
    corp = find_corp(name)
    print("corp:", corp)
    if corp:
        from datetime import date, timedelta
        end = date.today()
        begin = end - timedelta(days=30)
        disclosures = search_disclosures(name, begin.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
        print(f"최근 30일 공시 {len(disclosures)}건:")
        for d in disclosures[:5]:
            print(" -", d.get("rcept_dt"), d.get("report_nm"))
