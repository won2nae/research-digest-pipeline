#!/usr/bin/env python3
"""DART(전자공시시스템) 공시·재무정보를 조회하는 MCP 서버.

투자전략 리포트에 언급된 기업을 실제 공시·재무제표로 검증·보강하는
'기업분석 에이전트'가 쓰는 도구 모음이다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
from dart_client import search_disclosures, get_financial_summary

from mcp.server.mcpserver import MCPServer

mcp = MCPServer(name="dart-disclosures")


@mcp.tool()
def dart_search_disclosures(company_name: str, as_of_date: str, days_back: int = 30) -> str:
    """특정 기업의 DART 공시 목록을 조회한다.

    Args:
        company_name: 정식 상호명 또는 약칭 (예: "삼성전자", "SK하이닉스")
        as_of_date: 기준일 YYYY-MM-DD. 이 날짜 이후 공시는 조회하지 않는다 (미래 정보 누출 방지).
        days_back: 기준일로부터 며칠 전까지 조회할지 (기본 30일)
    """
    from datetime import date, timedelta
    end = date.fromisoformat(as_of_date)
    begin = end - timedelta(days=days_back)
    rows = search_disclosures(company_name, begin.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    if not rows:
        return f"'{company_name}' 관련 공시를 찾지 못함 (최근 {days_back}일)"
    lines = [f"- [{r.get('rcept_dt')}] {r.get('report_nm')} ({r.get('flr_nm')})" for r in rows]
    return "\n".join(lines)


@mcp.tool()
def dart_financial_summary(company_name: str, year: str, quarter: str = "3") -> str:
    """특정 기업의 분기 재무제표 주요 계정을 조회한다.

    Args:
        company_name: 정식 상호명 또는 약칭
        year: 사업연도 (예: "2026")
        quarter: "1"(1분기) / "2"(반기) / "3"(3분기) / "annual"(사업보고서)
    """
    reprt_map = {"1": "11013", "2": "11012", "3": "11014", "annual": "11011"}
    reprt_code = reprt_map.get(quarter, "11014")
    rows = get_financial_summary(company_name, year, reprt_code)
    if not rows:
        return f"'{company_name}' {year}년 {quarter}분기 재무정보를 찾지 못함"

    def _num(s):
        try:
            return float(str(s).replace(",", ""))
        except (TypeError, ValueError):
            return None

    # 재무상태표(BS) 계정은 이름이 고정이지만, 손익 계정은 보고서 기간에 따라
    # 이름이 다르다 (분기=분기순이익, 반기=반기순이익, 연간=당기순이익).
    # 자본변동표(SCE) 등 다른 명세서에도 같은 이름의 계정이 중복으로 나와서
    # sj_div로 재무상태표/손익계산서만 걸러야 정확한 값을 얻는다.
    bs_accounts = {"자산총계", "부채총계", "자본총계"}
    is_accounts = {"매출액", "영업이익"}
    net_income_names = {"당기순이익", "반기순이익", "분기순이익"}

    amounts = {}  # 표시용 이름 -> (thstrm, frmtrm)
    lines = []
    seen = set()
    for r in rows:
        name = r.get("account_nm", "")
        sj = r.get("sj_div", "")
        is_bs = sj == "BS" and name in bs_accounts
        is_is = sj in ("IS", "CIS") and (name in is_accounts or name in net_income_names)
        if not (is_bs or is_is):
            continue
        key = "당기순이익" if name in net_income_names else name
        if key in seen:
            continue
        seen.add(key)
        thstrm, frmtrm = _num(r.get("thstrm_amount")), _num(r.get("frmtrm_amount"))
        amounts[key] = (thstrm, frmtrm)
        lines.append(f"- {key}: 당기 {r.get('thstrm_amount')} / 전기 {r.get('frmtrm_amount') or '(비교 데이터 없음)'}")
    if not lines:
        return "핵심 계정을 찾지 못함 (전체 계정 수: " + str(len(rows)) + ")"

    def _pct(n, d):
        if n is None or d is None or d == 0:
            return None
        return n / d * 100

    revenue = amounts.get("매출액", (None, None))
    op = amounts.get("영업이익", (None, None))
    net = amounts.get("당기순이익", (None, None))
    equity = amounts.get("자본총계", (None, None))

    ratio_lines = []
    op_margin = _pct(op[0], revenue[0])
    if op_margin is not None:
        ratio_lines.append(f"- 영업이익률: {op_margin:.1f}%")
    net_margin = _pct(net[0], revenue[0])
    if net_margin is not None:
        ratio_lines.append(f"- 순이익률: {net_margin:.1f}%")
    roe = _pct(net[0], equity[0])
    if roe is not None:
        ratio_lines.append(f"- ROE(당기 자본 기준, 단순 계산): {roe:.1f}%")
    for label, (cur, prev) in (("매출액", revenue), ("영업이익", op), ("당기순이익", net)):
        if cur is not None and prev is not None and prev != 0:
            yoy = (cur - prev) / abs(prev) * 100
            ratio_lines.append(f"- {label} YoY: {yoy:+.1f}%")

    if ratio_lines:
        lines.append("")
        lines.append("[계산된 비율 - 전기 대비, 단순 계산치]")
        lines.extend(ratio_lines)
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
