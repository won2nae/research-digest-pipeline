"""개인 투자 신호 생성 (로컬 전용 — run_daily.sh/사이트 어디에도 연결 안 됨).

output/<date>/dart_analysis.md가 오늘 분석한 기업 목록을 재사용해서, 각 기업의
최근 30일 공시를 대량보유(지분)·설비투자(CAPEX) 관련으로만 다시 걸러보고,
리포트 분석과 대조한 신호(관찰 후보/주의 필요/특이사항 없음)를 만든다.
결과는 output/과 같은 위치(동등한 레벨)의 investment_output/<date>/에 저장 —
기존 리포트 산출물(output/)과 섞이지 않게 분리.

반자동 전제: 여기서 나오는 건 참고 신호일 뿐이다. 실제 매수·매도 주문은
본인이 직접 판단해서 넣고, 이 스크립트는 어떤 주문도 대신 넣지 않는다.
처음엔 수동으로만 실행(`python scripts/investment_signals.py <date>`) —
자동 편입은 몇 번 써보고 신호가 쓸만한지 확인한 뒤에 따로 결정.
"""
import re
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dart_client import search_disclosures

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_BIN = shutil.which("claude") or "/usr/local/bin/claude"

DISCLAIMER = (
    "> **이 신호는 본인 참고용입니다. 투자 자문이 아니며, 실제 매수·매도 판단과 "
    "책임은 전적으로 본인에게 있습니다. 이 스크립트는 어떤 주문도 대신 넣지 않습니다.**"
)

CAPEX_KEYWORDS = ("신규시설투자", "유형자산", "타법인", "증설", "시설투자", "출자")
HOLDING_KEYWORDS = ("대량보유", "주요주주", "자기주식", "소각", "전환청구권", "불성실공시")

SIGNAL_PROMPT = """아래는 {company}에 대해 오늘({today}) DART에서 확인된 자료다.

[오늘 리포트 기반 기존 DART 분석]
{dart_note}

[최근 30일 공시 중 지분/설비투자 관련만 필터링]
{filtered_disclosures}

위 정보만 가지고:
1. "관찰 후보" / "주의 필요" / "특이사항 없음" 중 하나로 분류해라.
   - 관찰 후보: 긍정적일 수 있는 신규 신호(대규모 증설, 지분 증가 등)가 있을 때
   - 주의 필요: 리스크 신호(지분 매도, 불성실공시, 소각 등 기존 분석에 없던 부정적 공시)가 있을 때
   - 특이사항 없음: 새로 특별한 신호가 없을 때
2. 왜 그렇게 분류했는지 공시 근거만 2~3줄로 짧게 적어라.

투자 판단·목표가·전망은 쓰지 마라. 공시 사실과 분류만 제시해라.
서론 없이 바로 "분류: ..." 형식으로 시작해라.
"""


def extract_companies(dart_md: str) -> list[str]:
    return [m.strip() for m in re.findall(r"^### (.+?)(?:\s*\(\d+\))?\s*$", dart_md, re.MULTILINE)]


def get_note_for(company: str, dart_md: str) -> str:
    m = re.search(
        rf"^### {re.escape(company)}.*?\n(.*?)(?=^### |\Z)", dart_md, re.MULTILINE | re.DOTALL
    )
    return m.group(1).strip() if m else "(기존 분석 없음)"


def filter_signal_disclosures(company: str, today: str) -> str:
    end = date.fromisoformat(today)
    begin = end - timedelta(days=30)
    rows = search_disclosures(company, begin.strftime("%Y%m%d"), end.strftime("%Y%m%d"))
    keywords = CAPEX_KEYWORDS + HOLDING_KEYWORDS
    hits = [r for r in rows if any(k in r.get("report_nm", "") for k in keywords)]
    if not hits:
        return "(관련 공시 없음)"
    return "\n".join(f"- [{r.get('rcept_dt')}] {r.get('report_nm')} ({r.get('flr_nm')})" for r in hits)


def generate_signal(company: str, today: str, dart_note: str, filtered: str) -> str:
    prompt = SIGNAL_PROMPT.format(company=company, today=today, dart_note=dart_note, filtered_disclosures=filtered)
    try:
        result = subprocess.run(
            [CLAUDE_BIN, "-p"], input=prompt, capture_output=True, text=True, timeout=120, cwd=str(ROOT),
        )
        if result.returncode != 0 or not result.stdout.strip():
            print(f"[investment_signals] {company} 생성 실패: {result.stderr[:200]}", file=sys.stderr)
            return "분류: 생성 실패"
        return result.stdout.strip()
    except Exception as e:
        print(f"[investment_signals] {company} 예외: {e}", file=sys.stderr)
        return "분류: 생성 실패"


def main():
    today = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    report_dir = ROOT / "output" / today
    dart_path = report_dir / "dart_analysis.md"
    if not dart_path.exists():
        print(f"[investment_signals] {dart_path} 없음 — 먼저 그 날짜의 run_daily.sh가 끝나야 함")
        return

    dart_md = dart_path.read_text(encoding="utf-8")
    companies = extract_companies(dart_md)
    if not companies:
        print("[investment_signals] 오늘 분석된 기업 없음")
        return

    print(f"[investment_signals] {len(companies)}개 기업: {', '.join(companies)}")
    sections = [f"# {today} 투자 신호 (개인 참고용, 비공개)\n\n{DISCLAIMER}"]
    for company in companies:
        print(f"  - {company} 확인 중...")
        filtered = filter_signal_disclosures(company, today)
        note = get_note_for(company, dart_md)
        signal = generate_signal(company, today, note, filtered)
        sections.append(f"## {company}\n\n{signal}\n\n**최근 30일 지분/설비투자 공시:**\n{filtered}")

    out_dir = ROOT / "investment_output" / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "investment_signals.md"
    out_path.write_text("\n\n---\n\n".join(sections), encoding="utf-8")
    print(f"[investment_signals] 완료: {out_path}")


if __name__ == "__main__":
    main()
