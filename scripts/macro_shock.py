"""네이버 마켓 지표 API로 매크로 충격/정책 변화 시그널을 탐지.

API 비용 없음, 로그인 불필요. 등락률은 네이버가 이미 계산해서 내려주므로
우리는 임계값과만 비교하면 된다.
"""
import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import requests

CLAUDE_BIN = shutil.which("claude") or "/usr/local/bin/claude"
NEWS_TOOLS = (
    "mcp__claude_ai_NewsMCP_without_a_key__news,"
    "mcp__claude_ai_NewsMCP_without_a_key__check_coverage"
)

ROOT = Path(__file__).resolve().parent.parent

INDICATOR_CODES = [
    "KOSPI", "KOSDAQ", "FX_USDKRW", "CLcv1", "GCcv1",
    "US10YT=RR", "KR10YT=RR", ".DJI", ".INX", ".IXIC",
]

# 임계값: 일반적으로 시장에서 "의미있는 하루 변동"으로 보는 수준.
# 지수/환율/유가는 %변동, 국채금리는 bp(절대) 변동 기준.
THRESHOLDS = {
    "KOSPI":      {"label": "코스피",        "type": "pct", "value": 1.5},
    "KOSDAQ":     {"label": "코스닥",        "type": "pct", "value": 2.0},
    "FX_USDKRW":  {"label": "원/달러 환율",   "type": "pct", "value": 1.0},
    "CLcv1":      {"label": "WTI 유가",      "type": "pct", "value": 3.0},
    "GCcv1":      {"label": "국제 금",       "type": "pct", "value": 2.5},
    "US10YT=RR":  {"label": "미국 10년 국채금리", "type": "bp",  "value": 10.0},
    "KR10YT=RR":  {"label": "한국 10년 국채금리", "type": "bp",  "value": 8.0},
    ".DJI":       {"label": "다우존스",      "type": "pct", "value": 1.5},
    ".INX":       {"label": "S&P 500",      "type": "pct", "value": 1.5},
    ".IXIC":      {"label": "나스닥",        "type": "pct", "value": 2.0},
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
URL = "https://stock.naver.com/api/securityService/integration/indicators"


def fetch_indicators() -> list[dict]:
    resp = requests.get(URL, headers=HEADERS, params={"indicatorCodes": ",".join(INDICATOR_CODES)}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def check_shocks(items: list[dict]) -> list[dict]:
    results = []
    for item in items:
        code = item.get("itemCode")
        rule = THRESHOLDS.get(code)
        if not rule:
            continue
        current = float(item["currentPrice"])
        change = float(item["fluctuations"])  # 네이버가 이미 계산해둔 전일 대비 변동폭
        pct = float(item.get("fluctuationsRatio", 0.0))
        if item.get("fluctuationsType") == "FALLING":
            change, pct = -abs(change), -abs(pct)
        last_close = current - change
        bp = change * 100  # 국채금리는 %단위이므로 *100 하면 bp

        if rule["type"] == "pct":
            magnitude, unit = pct, "%"
        else:
            magnitude, unit = bp, "bp"

        triggered = abs(magnitude) >= rule["value"]
        results.append({
            "code": code,
            "label": rule["label"],
            "current": current,
            "last_close": round(last_close, 4),
            "change": round(change, 4),
            "magnitude": round(magnitude, 2),
            "unit": unit,
            "threshold": rule["value"],
            "triggered": triggered,
            "direction": "상승" if change > 0 else "하락",
        })
    return results


def format_summary(results: list[dict]) -> str:
    shocks = [r for r in results if r["triggered"]]
    if not shocks:
        return "오늘 임계값을 넘는 매크로 충격 지표는 없었습니다."
    lines = ["## 오늘의 매크로 충격 지표\n"]
    for s in shocks:
        lines.append(
            f"- **{s['label']}** {s['direction']} {s['magnitude']:+.2f}{s['unit']} "
            f"(현재 {s['current']}, 전일 {s['last_close']}, 임계값 {s['threshold']}{s['unit']} 초과)"
        )
    return "\n".join(lines)


def get_news_context(results: list[dict]) -> str:
    """충격 지표가 있으면 뉴스 검색 도구로 원인 맥락을 찾아 붙인다. 없으면 빈 문자열."""
    shocks = [r for r in results if r["triggered"]]
    if not shocks:
        return ""

    shock_lines = "\n".join(
        f"- {s['label']} {s['direction']} {s['magnitude']:+.2f}{s['unit']}" for s in shocks
    )
    prompt = f"""아래는 오늘 감지된 매크로 충격 지표다. 뉴스 검색 도구를 반드시 사용해서
이런 변동의 원인이 될 만한 실제 뉴스를 찾아라. 지표별로 관련 뉴스를 1~2줄로 요약하고,
찾았으면 어느 언론사인지도 짧게 밝혀라. 관련 뉴스를 못 찾은 지표는 생략해라.

{shock_lines}

마크다운으로, 불필요한 서론 없이 바로 답해라.
"""
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p", "--allowedTools", NEWS_TOOLS],
            input=prompt, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return ""
        return result.stdout.strip()
    except Exception:
        return ""


def main():
    today = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    out_dir = ROOT / "data" / today
    out_dir.mkdir(parents=True, exist_ok=True)

    items = fetch_indicators()
    results = check_shocks(items)
    summary = format_summary(results)

    news_context = get_news_context(results)
    if news_context:
        summary = summary + "\n\n### 관련 뉴스\n\n" + news_context

    (out_dir / "macro_shocks.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "macro_shocks.md").write_text(summary, encoding="utf-8")

    print(summary)
    triggered_count = sum(1 for r in results if r["triggered"])
    print(f"\n({triggered_count}/{len(results)}개 지표 임계값 초과)")


if __name__ == "__main__":
    main()
