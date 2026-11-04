"""지식그래프 빌더.

data/, output/, DART/ 는 읽기만 한다 - 기존 파이프라인 파일은 전혀 건드리지
않는 순수 파생 레이어. vectorstore.py가 리포트를 읽어 벡터 인덱스를 따로
만드는 것과 같은 패턴이다.

노드: Company(DART corp_code 기준) / FinancialPeriod / Report / Broker / DailyBriefing
엣지: HAS_PERIOD, PUBLISHED_BY, MENTIONS(기업명 사전 매칭, LLM 호출 없음),
      VERIFIED(dart_analysis.md 헤딩에서 파싱), INCLUDES

회사명 매칭은 LLM이나 임베딩 없이, 이미 가진 corp_code 사전(3,979개)으로
단순 부분일치만 쓴다. 2글자 이하 회사명(SK, LG, CJ 등)은 오탐이 너무 많아
제외한다.
"""
import json
import re
import sys
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"
DART_DIR = ROOT / "DART"
GRAPH_DIR = ROOT / "graph"
CORP_CODE_CACHE = DATA_DIR / "dart_corp_codes.json"

CATEGORY_LABELS = ["macro", "bond", "sector", "strategy"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MIN_NAME_LEN = 3  # 2글자 이하(SK, LG, CJ...)는 오탐이 너무 많아 매칭에서 제외


def safe_name(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_.-]", "_", name)


def load_corp_dict() -> dict[str, dict]:
    if not CORP_CODE_CACHE.exists():
        return {}
    return json.loads(CORP_CODE_CACHE.read_text(encoding="utf-8"))


def add_company_nodes(g: nx.MultiDiGraph, corp_dict: dict) -> dict[str, str]:
    """corp_code -> node_id 맵을 반환."""
    code_to_node = {}
    for name, info in corp_dict.items():
        code = info["corp_code"]
        node_id = f"company:{code}"
        code_to_node[code] = node_id
        if not g.has_node(node_id):
            g.add_node(node_id, kind="Company", name=name, corp_code=code, stock_code=info.get("stock_code", ""))
    return code_to_node


def add_financial_periods(g: nx.MultiDiGraph, corp_dict: dict) -> None:
    name_to_code = {name: info["corp_code"] for name, info in corp_dict.items()}
    if not DART_DIR.exists():
        return
    key_accounts = {"자산총계", "부채총계", "자본총계", "매출액", "영업이익"}
    net_income_names = {"당기순이익", "반기순이익", "분기순이익"}
    reprt_order = {"11013": 0, "11012": 1, "11014": 2, "11011": 3}

    for company_dir in DART_DIR.iterdir():
        if not company_dir.is_dir():
            continue
        corp_code = name_to_code.get(company_dir.name)
        if not corp_code:
            continue
        company_node = f"company:{corp_code}"
        for f in sorted(company_dir.glob("financials_*.json")):
            m = re.match(r"financials_(\d{4})_(\d{5})\.json", f.name)
            if not m:
                continue
            year, reprt_code = m.groups()
            try:
                rows = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            amounts = {}
            for r in rows:
                nm, sj = r.get("account_nm", ""), r.get("sj_div", "")
                if sj == "BS" and nm in key_accounts:
                    amounts[nm] = r.get("thstrm_amount")
                elif sj in ("IS", "CIS") and (nm in key_accounts or nm in net_income_names):
                    amounts["당기순이익" if nm in net_income_names else nm] = r.get("thstrm_amount")
            period_node = f"period:{corp_code}:{year}:{reprt_code}"
            g.add_node(
                period_node, kind="FinancialPeriod", year=year, reprt_code=reprt_code,
                order=reprt_order.get(reprt_code, 9), **amounts,
            )
            g.add_edge(company_node, period_node, kind="HAS_PERIOD")


def build_name_matcher(corp_dict: dict) -> list[tuple[str, str]]:
    """(기업명, corp_code) 중 매칭에 쓸만한 것만. 긴 이름부터 정렬해서
    짧은 이름이 긴 이름의 부분집합으로 중복 매칭되는 걸 호출부에서 줄일 수 있게."""
    pairs = [
        (name, info["corp_code"]) for name, info in corp_dict.items()
        if len(name) >= MIN_NAME_LEN
    ]
    pairs.sort(key=lambda p: -len(p[0]))
    return pairs


def add_reports_and_mentions(g: nx.MultiDiGraph, code_to_node: dict, name_matcher: list, dates: list[str]) -> None:
    for date in dates:
        date_dir = DATA_DIR / date
        briefing_node = f"briefing:{date}"
        has_any = False
        for label in CATEGORY_LABELS:
            f = date_dir / f"naver_{label}.json"
            if not f.exists():
                continue
            try:
                items = json.loads(f.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            for i, item in enumerate(items):
                has_any = True
                report_node = f"report:{date}:{label}:{i}"
                broker = item.get("broker", "")
                g.add_node(
                    report_node, kind="Report", date=date, category=label,
                    broker=broker, title=item.get("title", ""),
                )
                if broker:
                    broker_node = f"broker:{broker}"
                    if not g.has_node(broker_node):
                        g.add_node(broker_node, kind="Broker", name=broker)
                    g.add_edge(report_node, broker_node, kind="PUBLISHED_BY")
                g.add_edge(briefing_node, report_node, kind="INCLUDES")

                text = item.get("title", "") + " " + item.get("content", "")
                for name, code in name_matcher:
                    if name in text:
                        node_id = code_to_node.get(code)
                        if node_id:
                            g.add_edge(report_node, node_id, kind="MENTIONS")
        if has_any:
            # add_edge가 이미 이 노드를 attribute 없이 만들어놨을 수 있어서, update로 덮어씀
            g.add_node(briefing_node, kind="DailyBriefing", date=date)


def add_dart_verifications(g: nx.MultiDiGraph, corp_dict: dict, dates: list[str]) -> None:
    name_to_code = {name: info["corp_code"] for name, info in corp_dict.items()}
    for date in dates:
        f = OUTPUT_DIR / date / "dart_analysis.md"
        if not f.exists():
            continue
        briefing_node = f"briefing:{date}"
        if not g.has_node(briefing_node):
            g.add_node(briefing_node, kind="DailyBriefing", date=date)
        text = f.read_text(encoding="utf-8")
        for m in re.finditer(r"^## (.+)$", text, re.MULTILINE):
            heading = re.sub(r"\(.*?\)", "", m.group(1)).strip()  # "삼성전자 (005930)" -> "삼성전자"
            code = name_to_code.get(heading)
            if not code:
                # 포함검색 fallback (약칭 등)
                candidates = [c for n, c in name_to_code.items() if heading and (heading in n or n in heading)]
                code = candidates[0] if len(candidates) == 1 else None
            if code:
                g.add_edge(briefing_node, f"company:{code}", kind="VERIFIED")


def _arg_value(flag: str, default: str) -> str:
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    all_history = "--all" in sys.argv
    days = int(_arg_value("--days", "60"))
    out_path = Path(_arg_value("--out", str(GRAPH_DIR / "kg.json")))

    corp_dict = load_corp_dict()
    if not corp_dict:
        print("회사 사전(data/dart_corp_codes.json)이 없음 - dart_client 먼저 실행 필요", file=sys.stderr)
        sys.exit(1)

    dates = sorted(p.name for p in DATA_DIR.iterdir() if p.is_dir() and DATE_RE.match(p.name))
    if not all_history:
        dates = dates[-days:]  # 기본은 최근 N일만 (전체 돌리려면 --all, 기간은 --days)

    print(f"대상 날짜 {len(dates)}개 ({dates[0]} ~ {dates[-1]})" if dates else "대상 날짜 없음")

    g = nx.MultiDiGraph()
    code_to_node = add_company_nodes(g, corp_dict)
    add_financial_periods(g, corp_dict)
    name_matcher = build_name_matcher(corp_dict)
    print(f"기업명 매칭 사전 {len(name_matcher)}개 (3글자 미만 제외)")
    add_reports_and_mentions(g, code_to_node, name_matcher, dates)
    add_dart_verifications(g, corp_dict, dates)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = nx.node_link_data(g, edges="edges")
    out_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    print(f"노드 {g.number_of_nodes()}개, 엣지 {g.number_of_edges()}개 -> {out_path}")


if __name__ == "__main__":
    main()
