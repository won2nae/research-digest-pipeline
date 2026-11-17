"""임베딩 모델 3종 비교 실험 — BAAI/bge-m3(현재 프로덕션) vs Qwen3-Embedding-0.6B
vs dragonkue/BGE-m3-ko.

목적: vectorstore.py가 쓰는 임베딩 모델을 바꾸면 검색 품질이 어떻게 달라지는지
실험으로 확인한다. **실험 전용 — 프로덕션(vectorstore.py)은 건드리지 않는다.**
적용 여부는 이 결과를 보고 따로 결정.

방법:
1. 최근 2년치(2025-01-01~) 리포트를 검색 코퍼스로 쓴다.
2. 날짜 하반기(2025-07-01~)에서 쿼리를 샘플링 — 각자의 날짜를 look-ahead
   방지 컷오프로 써서, 실제 프로덕션(historical_context)과 같은 조건으로 검색.
3. 모델별로 코퍼스 전체를 임베딩하고, 쿼리당 top-5를 브루트포스 코사인
   유사도로 검색 (실험 규모라 Chroma 없이 numpy로 충분).
4. Claude를 심사자로 써서(이 프로젝트의 기존 모델비교 방법론과 동일) 검색된
   문서들의 관련도를 1~5점으로 채점.
5. 모델별 평균 관련도, Precision@5(3점 이상 비율), 임베딩 처리량을 비교.
"""
import glob
import json
import random
import shutil
import subprocess
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
import numpy as np
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent.parent
CLAUDE_BIN = shutil.which("claude") or "/usr/local/bin/claude"
CORPUS_START = "2025-01-01"
QUERY_START = "2025-07-01"
N_QUERIES = 30
TOP_K = 5

MODELS = {
    "bge-m3": "BAAI/bge-m3",
    "qwen3-embedding-0.6b": "Qwen/Qwen3-Embedding-0.6B",
    "bge-m3-ko": "dragonkue/BGE-m3-ko",
}

JUDGE_PROMPT = """너는 금융 리서치 검색 시스템의 검색 품질을 평가하는 심사자다.
아래 "오늘 리포트"와, 검색 시스템이 과거 리포트 중에서 "관련 있다"고 찾아낸
후보 5개가 있다. 각 후보가 오늘 리포트를 분석할 때 실제로 참고할 만한 가치가
있는지 1~5점으로 채점해라.

5점: 같은 이슈/종목/이벤트를 다뤄서 직접 비교·참고 가치가 큼
3점: 같은 산업/주제 영역이라 배경 참고는 되지만 직접적 연결은 약함
1점: 주제가 전혀 달라 참고 가치 없음

--- 오늘 리포트 ---
{query}

--- 후보 1 ({date1}) ---
{doc1}

--- 후보 2 ({date2}) ---
{doc2}

--- 후보 3 ({date3}) ---
{doc3}

--- 후보 4 ({date4}) ---
{doc4}

--- 후보 5 ({date5}) ---
{doc5}

아래 형식으로만 답해라 (설명 없이 점수만):
1: [점수]
2: [점수]
3: [점수]
4: [점수]
5: [점수]
"""


def load_corpus(start_date: str) -> list[dict]:
    docs = []
    for path in sorted(glob.glob("data/*/naver_*.json", root_dir=ROOT)):
        date = path.split("/")[1]
        if date < start_date:
            continue
        category = Path(path).stem.replace("naver_", "")
        try:
            items = json.loads((ROOT / path).read_text(encoding="utf-8"))
        except Exception:
            continue
        for it in items:
            if not it.get("content"):
                continue
            docs.append({
                "id": f"naver:{category}:{it['nid']}", "date": date,
                "text": f"{it['title']}\n{it['content']}", "title": it["title"],
            })
    return docs


def embed_texts(model: SentenceTransformer, texts: list[str], batch_size: int = 64) -> np.ndarray:
    return model.encode(texts, batch_size=batch_size, normalize_embeddings=True, show_progress_bar=False)


def judge_batch(query_text: str, docs: list[dict]) -> list[int]:
    kwargs = {}
    for i, d in enumerate(docs, start=1):
        kwargs[f"doc{i}"] = d["text"][:1500]
        kwargs[f"date{i}"] = d["date"]
    prompt = JUDGE_PROMPT.format(query=query_text[:1500], **kwargs)
    try:
        result = subprocess.run([CLAUDE_BIN, "-p"], input=prompt, capture_output=True, text=True, timeout=90)
        scores = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            for i in range(1, 6):
                if line.startswith(f"{i}:"):
                    try:
                        scores.append(int(line.split(":")[1].strip()[0]))
                    except (ValueError, IndexError):
                        scores.append(0)
        while len(scores) < len(docs):
            scores.append(0)
        return scores[:len(docs)]
    except Exception as e:
        print(f"  [judge] 실패: {e}", file=sys.stderr)
        return [0] * len(docs)


def build_queries_and_corpus():
    random.seed(42)
    corpus = load_corpus(CORPUS_START)
    candidates = [d for d in corpus if d["date"] >= QUERY_START]
    queries = random.sample(candidates, min(N_QUERIES, len(candidates)))
    return corpus, queries


def run_one_model(key: str) -> None:
    """한 모델만 별도 프로세스에서 임베딩·검색하고 결과를 캐시 파일로 저장한다.
    모델마다 완전히 새 프로세스로 띄워서, 이전 모델이 GPU 메모리를 깨끗이
    못 비우는 문제(실제로 2026-11-17에 OOM으로 한 번 터짐)를 원천적으로 막는다."""
    model_name = MODELS[key]
    corpus, queries = build_queries_and_corpus()
    print(f"[{key}] 코퍼스 {len(corpus)}건, 쿼리 {len(queries)}건")

    corpus_dates = np.array([d["date"] for d in corpus])
    corpus_texts = [d["text"] for d in corpus]

    t0 = time.time()
    model = SentenceTransformer(model_name, device="cuda:1", trust_remote_code=True)
    load_time = time.time() - t0

    t0 = time.time()
    corpus_emb = embed_texts(model, corpus_texts)
    embed_time = time.time() - t0
    throughput = len(corpus) / embed_time
    print(f"[{key}] 로드 {load_time:.1f}s, 코퍼스 임베딩 {embed_time:.1f}s ({throughput:.0f}건/s)")

    query_emb = embed_texts(model, [q["text"] for q in queries])

    retrievals = []
    for q, qemb in zip(queries, query_emb):
        mask = corpus_dates < q["date"]
        sims = corpus_emb[mask] @ qemb
        idx = np.argsort(-sims)[:TOP_K]
        masked_corpus = [d for d, m in zip(corpus, mask) if m]
        top_docs = [masked_corpus[i] for i in idx]
        retrievals.append({"query": q, "docs": top_docs})

    cache = {
        "load_time": load_time, "embed_time": embed_time, "throughput": throughput,
        "retrievals": [
            {"query": r["query"], "docs": r["docs"]} for r in retrievals
        ],
    }
    cache_path = ROOT / "paperwork" / f"embedding_cache_{key}.json"
    cache_path.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    print(f"[{key}] 완료: {cache_path}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--model":
        run_one_model(sys.argv[2])
        return

    print(f"[compare_embeddings] 모델별로 독립 프로세스 실행...")
    for key in MODELS:
        print(f"\n=== {key} ({MODELS[key]}) 서브프로세스 시작 ===")
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--model", key])
        if result.returncode != 0:
            print(f"[compare_embeddings] {key} 실패 (returncode={result.returncode}), 건너뛰고 계속", file=sys.stderr)

    results = {}
    for key in MODELS:
        cache_path = ROOT / "paperwork" / f"embedding_cache_{key}.json"
        if not cache_path.exists():
            print(f"[compare_embeddings] {key} 캐시 없음, 스킵", file=sys.stderr)
            continue
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        results[key] = {
            "load_time": cache["load_time"], "embed_time": cache["embed_time"],
            "throughput": cache["throughput"],
            "retrievals": [{"query": r["query"], "docs": r["docs"]} for r in cache["retrievals"]],
        }

    print("\n=== LLM 심사 시작 (Claude) ===")
    for key in results:
        scores_all = []
        for i, r in enumerate(results[key]["retrievals"]):
            scores = judge_batch(r["query"]["text"], r["docs"])
            scores_all.append(scores)
            if (i + 1) % 10 == 0:
                print(f"  [{key}] {i + 1}/{len(results[key]['retrievals'])} 채점")
        results[key]["scores"] = scores_all

    print("\n=== 요약 ===")
    summary_lines = []
    for key in results:
        flat = [s for row in results[key]["scores"] for s in row]
        avg = sum(flat) / len(flat) if flat else 0
        p_at_5 = sum(1 for s in flat if s >= 3) / len(flat) if flat else 0
        line = (f"{key}: 평균 관련도 {avg:.2f}/5, Precision@5(3점 이상) {p_at_5 * 100:.1f}%, "
                f"처리량 {results[key]['throughput']:.0f}건/s")
        print(line)
        summary_lines.append(line)

    out_path = ROOT / "paperwork" / "embedding_comparison_raw.json"
    serializable = {
        key: {
            "load_time": v["load_time"], "embed_time": v["embed_time"], "throughput": v["throughput"],
            "scores": v["scores"],
            "retrievals": [
                {"query_title": r["query"]["title"], "query_date": r["query"]["date"],
                 "docs": [{"title": d["title"], "date": d["date"]} for d in r["docs"]]}
                for r in v["retrievals"]
            ],
        }
        for key, v in results.items()
    }
    out_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n원본 데이터 저장: {out_path}")


if __name__ == "__main__":
    main()
