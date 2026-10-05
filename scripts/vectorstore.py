"""로컬 무료 벡터DB(Chroma) + 로컬 임베딩 모델(BAAI/bge-m3)로 리포트 아카이브 관리.

API 비용 없이 전부 로컬에서 처리된다.
"""
import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "vectordb"
COLLECTION_NAME = "research_reports"
MODEL_NAME = "BAAI/bge-m3"
DEVICE = "cuda:1"  # GPU 0은 다른 작업이 점유 중이라 회피

_model = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME, device=DEVICE)
    return _model


def get_collection():
    client = chromadb.PersistentClient(path=str(DB_DIR))
    return client.get_or_create_collection(COLLECTION_NAME)


def embed(texts: list[str]) -> list[list[float]]:
    model = get_model()
    # bge 계열은 문서 임베딩 시 접두어 없이, 쿼리 임베딩 시 "query: " 접두어 권장
    return model.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()


def ingest_day(date: str, source: str = "naver"):
    """data/<date>/<source>_<category>.json 파일들을 벡터DB에 적재. 이미 있는 문서는 skip."""
    data_dir = ROOT / "data" / date
    collection = get_collection()

    docs, metadatas, ids = [], [], []
    for path in sorted(data_dir.glob(f"{source}_*.json")):
        category = path.stem.replace(f"{source}_", "")
        items = json.loads(path.read_text(encoding="utf-8"))
        for item in items:
            doc_id = f"{source}:{category}:{item['nid']}"
            docs.append(f"{item['title']}\n{item['content']}")
            metadatas.append({
                "source": source,
                "category": category,
                "broker": item.get("broker", ""),
                "title": item.get("title", ""),
                "date": item.get("date", date),
            })
            ids.append(doc_id)

    if not docs:
        print(f"[{date}] 적재할 문서 없음")
        return

    # 이미 적재된 id는 제외
    existing = set()
    try:
        found = collection.get(ids=ids)
        existing = set(found["ids"])
    except Exception:
        pass

    new_docs, new_meta, new_ids = [], [], []
    for d, m, i in zip(docs, metadatas, ids):
        if i not in existing:
            new_docs.append(d)
            new_meta.append(m)
            new_ids.append(i)

    if not new_docs:
        print(f"[{date}] 이미 전부 적재됨 ({len(ids)}건)")
        return

    embeddings = embed(new_docs)
    collection.add(documents=new_docs, embeddings=embeddings, metadatas=new_meta, ids=new_ids)
    print(f"[{date}] {len(new_docs)}건 신규 적재 (전체 {collection.count()}건)")


def ingest_all(source: str = "naver", batch_size: int = 512):
    """data/*/<source>_*.json 전체를 배치로 적재 (대량 백필용). 중단돼도 재실행하면 이어서 진행됨."""
    collection = get_collection()
    paths = sorted(ROOT.glob(f"data/*/{source}_*.json"))
    print(f"대상 파일 {len(paths)}개")

    batch_docs, batch_meta, batch_ids = [], [], []
    total_new = 0
    total_seen = 0

    def flush():
        nonlocal batch_docs, batch_meta, batch_ids, total_new
        if not batch_ids:
            return
        # 배치 내 중복 id 방어 (혹시 모를 재실행/데이터 이상 대비)
        seen, dedup_docs, dedup_meta, dedup_ids = set(), [], [], []
        for d, m, i in zip(batch_docs, batch_meta, batch_ids):
            if i not in seen:
                seen.add(i)
                dedup_docs.append(d)
                dedup_meta.append(m)
                dedup_ids.append(i)
        batch_docs, batch_meta, batch_ids = dedup_docs, dedup_meta, dedup_ids

        existing = set(collection.get(ids=batch_ids)["ids"])
        new_docs = [d for d, i in zip(batch_docs, batch_ids) if i not in existing]
        new_meta = [m for m, i in zip(batch_meta, batch_ids) if i not in existing]
        new_ids = [i for i in batch_ids if i not in existing]
        if new_ids:
            embeddings = embed(new_docs)
            collection.add(documents=new_docs, embeddings=embeddings, metadatas=new_meta, ids=new_ids)
            total_new += len(new_ids)
        batch_docs, batch_meta, batch_ids = [], [], []

    for path in paths:
        date = path.parent.name
        category = path.stem.replace(f"{source}_", "")
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in items:
            if not item.get("content"):
                continue
            batch_ids.append(f"{source}:{category}:{item['nid']}")
            batch_docs.append(f"{item['title']}\n{item['content']}")
            batch_meta.append({
                "source": source,
                "category": category,
                "broker": item.get("broker", ""),
                "title": item.get("title", ""),
                "date": item.get("date", date),
            })
            total_seen += 1
            if len(batch_ids) >= batch_size:
                flush()
                print(f"진행: {total_seen}건 확인, {total_new}건 신규 적재 (전체 {collection.count()}건)")
    flush()
    print(f"\n완료: {total_seen}건 확인, {total_new}건 신규 적재. DB 전체 {collection.count()}건")


def search(query: str, category: str | None = None, before_date: str | None = None, top_k: int = 5) -> list[dict]:
    """유사 과거 리포트 검색. before_date를 주면 그 날짜 이전 문서만."""
    collection = get_collection()
    where = {}
    if category:
        where["category"] = category

    query_emb = embed([f"query: {query}"])[0]
    result = collection.query(
        query_embeddings=[query_emb],
        n_results=top_k * 3 if before_date else top_k,  # 날짜 필터링 여유분
        where=where or None,
    )

    hits = []
    for doc, meta, dist in zip(result["documents"][0], result["metadatas"][0], result["distances"][0]):
        if before_date and meta.get("date", "") >= before_date:
            continue
        hits.append({"document": doc, "metadata": meta, "distance": dist})
        if len(hits) >= top_k:
            break
    return hits


if __name__ == "__main__":
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else __import__("datetime").date.today().isoformat()
    ingest_day(date)
