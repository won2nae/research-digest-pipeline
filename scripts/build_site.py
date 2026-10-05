"""output/ 폴더의 모든 digest_*.md를 읽어 site/ 에 정적 사이트를 생성한다.

output/ 은 건드리지 않는다 (읽기 전용). 생성 결과만 site/ 아래에 쓴다.
site/ 는 그대로 git repo로 push -> Vercel 등에서 자동 배포하면 된다.

콘텐츠는 passphrase로만 복호화되는 형태로 굽는다 (site_crypto.py 참고).
"""
import json
import re
from pathlib import Path

from site_crypto import encrypt_json

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = ROOT / "output"
DATA_DIR = ROOT / "data"
SITE_DIR = ROOT / "site"

# True면 passphrase 암호화 + 접근 게이트를 굽는다. False면 공개.
GATE_ENABLED = False

MARKET_CATEGORY_FILES = ("macro.md", "bond.md", "sector.md")


def is_business_day(date: str) -> bool:
    """주말·공휴일에는 시장 카테고리 리포트가 생성되지 않으므로 파일 유무로 판정."""
    folder = OUTPUT_DIR / date
    return any((folder / name).exists() for name in MARKET_CATEGORY_FILES)


def parse_categories(md_text: str) -> list[tuple[str, str]]:
    """'## ' 로 시작하는 최상위 섹션 단위로 쪼갠다 ('### '는 하위 이슈라 안 걸림)."""
    parts = md_text.split("\n## ")
    categories = []
    for part in parts[1:]:
        head, _, rest = part.partition("\n")
        title = head.strip()
        categories.append((title, f"## {title}\n{rest}"))
    return categories


def first_headline(md_text: str) -> str:
    m = re.search(r"^### (?:\d+\.\s*)?(.+)$", md_text, flags=re.MULTILINE)
    return re.sub(r"\*\*|`", "", m.group(1)).strip() if m else ""


def load_market(date: str) -> dict | None:
    path = DATA_DIR / date / "macro_shocks.json"
    if not path.exists():
        return None
    items = json.loads(path.read_text(encoding="utf-8"))
    return {
        it["code"]: {
            "label": it["label"],
            "value": it["current"],
            "change": it["magnitude"],
            "unit": it["unit"],
        }
        for it in items
    }


def synth_shock_block(market: dict) -> str:
    """충격 지표 섹션이 없는 날에도 상단 박스 자리를 같은 형식으로 채운다 (수치는 지표 데이터에서)."""
    lines = []
    for code in ("KOSPI", "KOSDAQ"):
        ind = market.get(code)
        if not ind:
            continue
        direction = "상승" if ind["change"] > 0 else "하락" if ind["change"] < 0 else "보합"
        lines.append(
            f"- **{ind['label']}** {direction} {ind['change']:+.2f}{ind['unit']} "
            f"(현재 {ind['value']:,}, 전일 대비)"
        )
    note = "오늘은 임계값을 넘는 매크로 충격 지표가 없었습니다."
    return "## 오늘의 매크로 충격 지표\n\n" + "\n".join(lines) + f"\n\n_{note}_"


def load_digest(date: str) -> dict | None:
    path = OUTPUT_DIR / date / f"digest_{date}.md"
    if not path.exists():
        return None
    categories = parse_categories(path.read_text(encoding="utf-8"))
    if not categories:
        return None
    shock_md = ""
    tab_blocks = []
    for title, md in categories:
        if "충격" in title and not shock_md and not tab_blocks:
            shock_md = md
        else:
            tab_blocks.append((title, md))
    tabs = [{"title": t, "md": m} for t, m in tab_blocks]
    headline = first_headline("\n".join(md for _, md in tab_blocks))
    market = load_market(date)
    if not shock_md and market:
        shock_md = synth_shock_block(market)
    return {
        "date": date,
        "headline": headline,
        "market": market,
        "shock_md": shock_md,
        "tabs": tabs,
    }


PAGE_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>{title}</title>
<link rel="stylesheet" href="{asset_prefix}assets/style.css">
</head>
<body>
{gate_html}
<main id="app" hidden></main>
<script id="__DATA__" type="application/json">{data_json}</script>
<script src="{asset_prefix}assets/marked.min.js"></script>
<script src="{asset_prefix}assets/chart.umd.js"></script>
<script src="{asset_prefix}assets/site.js"></script>
<script>Site.init({page_kind});</script>
</body>
</html>
"""

GATE_HTML = """<div id="gate" class="gate">
  <form id="gate-form">
    <h1>비공개 브리핑</h1>
    <p>접근 코드를 입력하세요.</p>
    <input id="gate-input" type="password" autocomplete="off" autofocus>
    <button type="submit">열기</button>
    <p id="gate-error" class="gate-error" hidden>코드가 올바르지 않습니다.</p>
  </form>
</div>"""


def render_page(title: str, asset_prefix: str, payload: dict, page_kind: str) -> str:
    data_json = json.dumps(
        encrypt_json(payload) if GATE_ENABLED else payload, ensure_ascii=False
    )
    return PAGE_TEMPLATE.format(
        title=title,
        asset_prefix=asset_prefix,
        gate_html=GATE_HTML if GATE_ENABLED else "",
        data_json=data_json,
        page_kind=f'"{page_kind}"',
    )


def render_day_page(digest: dict) -> str:
    return render_page(f"{digest['date']} 리서치 브리핑", "../../", digest, "day")


def render_index_page(days: list[dict]) -> str:
    return render_page("리서치 브리핑 아카이브", "", {"days": days}, "index")


def main():
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    dates = sorted(
        p.name
        for p in OUTPUT_DIR.iterdir()
        if p.is_dir() and date_re.match(p.name) and is_business_day(p.name)
    )

    (SITE_DIR / "assets").mkdir(parents=True, exist_ok=True)
    (SITE_DIR / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")

    days_root = SITE_DIR / "days"
    keep = set(dates)
    if days_root.exists():
        for stale in days_root.iterdir():
            if stale.is_dir() and stale.name not in keep:
                for f in stale.glob("*"):
                    f.unlink()
                stale.rmdir()

    days = []
    for date in dates:
        digest = load_digest(date)
        if digest is None:
            continue
        day_dir = SITE_DIR / "days" / date
        day_dir.mkdir(parents=True, exist_ok=True)
        (day_dir / "index.html").write_text(render_day_page(digest), encoding="utf-8")
        days.append({"date": date, "headline": digest["headline"], "market": digest["market"]})

    (SITE_DIR / "index.html").write_text(
        render_index_page(sorted(days, key=lambda d: d["date"], reverse=True)), encoding="utf-8"
    )

    print(f"완료: {len(days)}개 영업일 -> {SITE_DIR}")


if __name__ == "__main__":
    main()
