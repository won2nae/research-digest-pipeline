"""일별 파이프라인의 마지막 안전망. 반복 루프(문장/헤딩 수십 번 반복)와 언어
드리프트(한국어 대신 중국어/영어로 같은 내용을 다시 씀)를 오늘 만들어진 모든
최종 md에서 한 번 더 점검하고, 남아있으면 잘라서 다시 쓴다.

summarize.py의 ask_local()이 카테고리 생성 직후 이미 한 번 이 검사를 거는데(같은
실행 안에서 "오늘의 핵심 쟁점 정리" 프롬프트에 깨끗한 입력을 넘겨주려고 필요함),
그건 로컬 모델(Qwen3-14B)이 생성한 macro/bond/sector/strategy.md만 본다.
DART 기업분석(dart_agent.py)과 전날 뉴스 요약(news_summary.py)은 둘 다 Claude API
서브프로세스 결과라 그 검사를 한 번도 안 거친 채 최종 산출물에 들어간다.
여기서는 같은 검사 로직(local_llm.trim_runaway_repetition)을 재사용해서, 이
둘까지 포함한 "오늘의 완성본 전체"를 build_site.py 직전에 마지막으로 점검한다.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_llm import trim_runaway_repetition
from summarize import CATEGORY_LABELS

ROOT = Path(__file__).resolve().parent.parent


def check_and_fix(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    fixed = trim_runaway_repetition(text)
    if fixed == text:
        return False
    path.write_text(fixed, encoding="utf-8")
    print(f"[final_check] {path.name}: {len(text)} -> {len(fixed)}자 (문제 발견, 수정함)")
    return True


def rebuild_digest(today: str, out_dir: Path) -> None:
    """카테고리 .md 중 하나라도 고쳐졌으면, summarize.py와 같은 템플릿으로
    digest_{today}.md를 다시 조립한다 (digest 자체를 따로 자르면 문제와 무관한
    뒤쪽 카테고리까지 같이 날아가니, 항상 카테고리 파일에서 재조립)."""
    shock_path = out_dir / "macro_shocks.md"
    shock_summary = shock_path.read_text(encoding="utf-8") if shock_path.exists() else ""
    parts = [
        (out_dir / f"{label}.md").read_text(encoding="utf-8")
        for label in CATEGORY_LABELS
        if (out_dir / f"{label}.md").exists()
    ]
    full = (
        f"# {today} 데일리 리서치 브리핑\n\n"
        + shock_summary + "\n\n---\n\n"
        + "\n\n---\n\n".join(parts)
    )
    (out_dir / f"digest_{today}.md").write_text(full, encoding="utf-8")
    print(f"[final_check] digest_{today}.md 재조립")


def main():
    today = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    out_dir = ROOT / "output" / today
    if not out_dir.exists():
        print(f"[final_check] {out_dir} 없음, 건너뜀")
        return

    print(f"=== [{today}] 최종 점검 (반복 루프 / 언어 드리프트) ===")
    category_changed = False
    for label in CATEGORY_LABELS:
        if check_and_fix(out_dir / f"{label}.md"):
            category_changed = True
    check_and_fix(out_dir / "dart_analysis.md")
    check_and_fix(ROOT / "data" / today / "news_summary.md")

    if category_changed:
        rebuild_digest(today, out_dir)
    else:
        print("[final_check] 문제 없음")


if __name__ == "__main__":
    main()
