"""로컬 모델 여러 개를 같은 프롬프트(매크로 카테고리)로 돌려서 품질/속도 비교.

이미 저장된 output/<date>/macro.md (Claude 결과)를 베이스라인으로 같이 둔다.
"""
import json
import sys
import time
from datetime import date
from pathlib import Path

from local_llm import ask_local, unload_model

ROOT = Path(__file__).resolve().parent.parent

MODELS = [
    "Qwen/Qwen3-0.6B",
    "meta-llama/Llama-3.1-8B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "Qwen/Qwen3-8B",
]

PROMPT_TEMPLATE = """아래는 오늘({today}) 국내 증권사들이 발행한 '매크로(경제)' 분야 리서치 리포트 원문들이다.
이 리포트들을 종합해서 한국어 마크다운으로 데일리 브리핑을 작성해라.

요구사항:
- 오늘 나온 핵심 이슈 3~6개를 뽑아서 소제목으로 정리
- 각 이슈마다 어떤 증권사가 어떤 근거로 그렇게 봤는지 1~3줄로 요약 (증권사 이름 명시)
- 리포트들 사이에 의견이 갈리면 그 차이도 짚어줄 것
- 불필요한 서론/결론 없이 바로 본문 시작
- 제목은 "## 매크로(경제)"로 시작

--- 리포트 원문 ---
{content}
"""


def format_reports(reports):
    return "\n\n---\n\n".join(f"[{r['broker']}] {r['title']}\n{r['content']}" for r in reports)


def main():
    today = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    data_path = ROOT / "data" / today / "naver_macro.json"
    reports = json.loads(data_path.read_text(encoding="utf-8"))
    prompt = PROMPT_TEMPLATE.format(today=today, content=format_reports(reports))

    out_dir = ROOT / "output" / "model_test"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"입력: 매크로 리포트 {len(reports)}건, 프롬프트 길이 {len(prompt)}자\n")

    results = []
    for model_name in MODELS:
        print(f"=== {model_name} 실행 중... ===")
        start = time.time()
        try:
            output = ask_local(prompt, model_name=model_name, max_new_tokens=2000)
            elapsed = time.time() - start
            safe_name = model_name.replace("/", "_")
            out_path = out_dir / f"{safe_name}.md"
            out_path.write_text(output, encoding="utf-8")
            results.append((model_name, elapsed, len(output), str(out_path)))
            print(f"완료: {elapsed:.1f}초, {len(output)}자 -> {out_path}\n")
        except Exception as e:
            print(f"실패: {e}\n")
            results.append((model_name, None, None, f"ERROR: {e}"))
        finally:
            unload_model(model_name)  # 다음 모델 위해 GPU 메모리 회수

    print("\n=== 요약 ===")
    for name, elapsed, length, path in results:
        if elapsed is not None:
            print(f"{name:35s} {elapsed:6.1f}초  {length:5d}자  -> {path}")
        else:
            print(f"{name:35s} {path}")


if __name__ == "__main__":
    main()
