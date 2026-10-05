"""PDF 리포트를 이미지로 렌더링한 뒤 Claude Vision(claude -p)으로 텍스트/수치를 추출.

일반 텍스트 추출이 안 되는(이미지 기반) 증권사 PDF 전용 전처리 단계.
Claude Code Pro 구독 사용량으로 처리 (별도 API 과금 없음).
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import pdfplumber
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

VISION_PROMPT = """아래 이미지들은 증권사 리서치 리포트 PDF를 페이지별로 캡처한 것이다.
이 이미지를 순서대로 읽고, 표/차트에 있는 숫자는 최대한 정확하게 옮기고,
애널리스트의 핵심 투자의견/논리를 본문 텍스트로 요약해라.

반드시 아래 형식 그대로, 구분자를 정확히 지켜서 출력해라 (다른 설명·마크다운 코드블록 없이):

===TITLE===
(리포트 제목)
===DATE===
(YYYY-MM-DD)
===CONTENT===
(핵심 내용 요약: 투자의견, 목표주가, 핵심 논리, 주요 재무 수치 포함. 여러 줄 가능)
===END===

이미지 파일:
{image_paths}
"""


def download_pdf(url: str, dest: Path) -> Path:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def render_pages(pdf_path: Path, out_dir: Path, resolution: int = 150) -> list[Path]:
    paths = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            img_path = out_dir / f"page{i + 1}.png"
            page.to_image(resolution=resolution).save(str(img_path))
            paths.append(img_path)
    return paths


def parse_response(text: str) -> dict:
    def grab(tag_start: str, tag_end: str) -> str:
        m = re.search(re.escape(tag_start) + r"\s*(.*?)\s*" + re.escape(tag_end), text, re.DOTALL)
        return m.group(1).strip() if m else ""

    title = grab("===TITLE===", "===DATE===")
    date_ = grab("===DATE===", "===CONTENT===")
    content = grab("===CONTENT===", "===END===")
    if not content:
        # ===END=== 마커가 누락된 경우 CONTENT 이후 끝까지
        m = re.search(r"===CONTENT===\s*(.*)", text, re.DOTALL)
        content = m.group(1).strip() if m else ""
    if not (title or content):
        raise ValueError(f"파싱 실패, 원본 앞부분: {text[:200]}")
    return {"title": title, "date": date_, "content": content}


def vision_extract(image_paths: list[Path]) -> dict:
    image_list = "\n".join(str(p) for p in image_paths)
    prompt = VISION_PROMPT.format(image_paths=image_list)
    result = subprocess.run(
        ["claude", "-p", "--allowedTools", "Read"],
        input=prompt,
        capture_output=True,
        text=True,
        cwd=image_paths[0].parent,
        timeout=300,
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude -p 실패: {result.stderr}")
    return parse_response(result.stdout)


def extract_pdf_report(pdf_url: str, broker: str, fallback_title: str = "", fallback_date: str = "") -> dict:
    """PDF URL 하나를 받아서 naver_*.json과 같은 스키마({title, broker, date, content})로 반환."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        pdf_path = download_pdf(pdf_url, tmp_dir / "report.pdf")
        image_paths = render_pages(pdf_path, tmp_dir)
        extracted = vision_extract(image_paths)

    return {
        "title": extracted.get("title") or fallback_title,
        "broker": broker,
        "date": extracted.get("date") or fallback_date,
        "content": extracted.get("content", ""),
        "source_pdf": pdf_url,
    }


if __name__ == "__main__":
    import sys
    url = sys.argv[1]
    print(json.dumps(extract_pdf_report(url, "미래에셋증권"), ensure_ascii=False, indent=2))
