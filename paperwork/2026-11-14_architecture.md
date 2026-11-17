# 리서치 AI 구조 — 전체 아키텍처 정리

- **작성일**: 2026-11-14
- **목적**: 지금까지 쌓인 파이프라인 전체 구조를 한 눈에 볼 수 있게 정리. 세부 문제/수정 히스토리는 `2026-10-31_issues_and_fixes_log.md` 참고.
- **핵심 설계 철학**:
  1. **AI는 사실 정리자, 판단자가 아니다** — 투자 판단·전망을 내리지 않고, 리포트 간 근거를 대조해서 제시만 함(`STRATEGY_DISCLAIMER`/`DART_DISCLAIMER`).
  2. **로컬 모델을 기본으로, Claude는 꼭 필요한 곳에만** — 매일 반복되는 대량 요약(매크로/채권/섹터/투자전략)은 로컬 Qwen3-14B(+LoRA)로 API 비용 없이 처리. Claude는 DART 기업분석·뉴스 요약·PDF Vision처럼 도구 호출이 필요한 서브 에이전트에만 씀.
  3. **파생 레이어는 기존 구조를 건드리지 않는다** — 지식그래프(`build_graph.py`)처럼 나중에 추가된 기능은 `data/`·`output/`·`DART/`를 읽기만 하고, 쓰지 않음.

## 1. 전체 파이프라인 (매일 07:00 KST, cron)

```
0 7 * * * scripts/run_daily.sh yesterday >> logs/run_daily.log
```

주말·공휴일이면 즉시 종료(`holidays.KR()`). 영업일이면 아래 순서로 실행:

| 단계 | 스크립트 | 역할 |
|---|---|---|
| 1 | `collect.py` | 네이버 파이낸셜 API + 미래에셋 HTML/PDF(Vision OCR) 리포트 수집 → `data/<date>/naver_*.json`, `mirae_*.json` |
| 2 | `macro_shock.py` | 네이버 지표 API로 17개 매크로 지표(지수·환율·원자재·국채금리) 조회, 임계값 초과 여부 판단 → `data/<date>/macro_shocks.{json,md}` |
| 2.5 | `news_summary.py` | NewsMCP로 전날 미국발 메인 + 한국 서브 뉴스 요약 → `data/<date>/news_summary.md` |
| 3 | `vectorstore.py` | 오늘 수집된 리포트를 로컬 벡터DB(Chroma)에 적재(과거 맥락 검색용) |
| 4 | `summarize.py` | 로컬 Qwen3-14B로 카테고리별 요약 생성 + DART 기업분석 서브에이전트 호출 → `output/<date>/*.md` |
| 4.5 | `final_check.py` | 반복 루프·언어 드리프트 최종 점검/수정, 필요하면 digest 재조립 |
| 5 | `build_site.py` + git push | 정적 사이트 재생성, `site/` 별도 git repo에 커밋·push (Vercel 자동 배포) |

## 2. 디렉터리 구조

```
research-ai/
├── data/<date>/          # 원문 리포트(JSON), 매크로 지표, 뉴스 요약
├── output/<date>/        # 카테고리별 요약(.md), dart_analysis.md, digest_<date>.md
├── DART/<회사명>/        # DART 재무제표 캐시 (실제 분석된 기업만, 전체 상장사 아님)
├── vectordb/             # Chroma 벡터DB (리포트 아카이브, 18년치 10만+ 건)
├── graph/kg.json         # 지식그래프 전체 이력본 (로컬 전용, 사이트엔 최근 120일만)
├── logs/                 # run_daily.log 등
├── scripts/              # 파이프라인 전체 코드
├── for_tuning/           # LoRA 파인튜닝 학습/평가 스크립트, 어댑터 가중치
├── site/                 # 정적 사이트 — **별도 git repo** (research-digest-site)
├── paperwork/            # 이 문서 포함, 운영 기록·평가 노트
├── .mcp.json             # research-archive, dart-disclosures MCP 서버 등록
├── mcp_server.py         # research-archive MCP (리포트 아카이브 자연어 검색)
└── dart_mcp_server.py    # dart-disclosures MCP (DART 공시·재무 조회)
```

## 3. 데이터 수집 (`collect.py`)

소스별 함수가 `{카테고리: [report, ...]}`를 반환하는 구조라 소스 추가가 쉬움.

- **네이버 파이낸셜**: API 직접 호출, 텍스트 바로 추출.
- **미래에셋증권**: HTML 목록 + PDF는 이미지 기반이라 텍스트 추출이 안 됨 → `pdf_ocr.py`가 PDF를 이미지로 렌더링 후 **Claude Vision**(`claude -p`, Pro 구독 사용량으로 처리, API 과금 없음)으로 텍스트/수치 추출.
- 과거 데이터 백필은 별도 스크립트(`backfill_naver.py`, 2008~현재)로 1회성 처리, 같은 파일 스키마를 써서 나머지 파이프라인이 그대로 동작.

## 4. 매크로 지표 (`macro_shock.py`)

네이버 지표 API(`stock.naver.com/.../indicators`)에서 17개 지표를 매일 조회:

- **지수**: 코스피·코스닥·다우존스·S&P500·나스닥
- **국채 10년물**: 미국·한국·독일·일본·영국·중국 (독·일·영 과거 차트는 FRED 월별 데이터로 보강, 중국은 FRED가 접근을 막아서 히스토리 없음 — 홈페이지 "금리 추이" 차트에서만 제외, 당일 지표/일별 페이지에는 계속 표시)
- **원자재**: WTI 유가, 국제 금·은, 구리, 천연가스
- **환율**: 원/달러

지표별 임계값(%, 또는 금리는 bp)을 넘으면 "오늘의 매크로 충격 지표"로 표시되고, Claude(NewsMCP 도구 권한만 줌)가 원인 뉴스를 검색해서 붙여줌. 전체 17개 지표 값은 임계값과 무관하게 `macro_shocks.json`에 다 저장돼서, 사이트 홈페이지 상단 지표 카드/차트에 항상 노출됨.

## 5. 과거 맥락 — 벡터DB (`vectorstore.py`)

- 로컬 임베딩 모델(BAAI/bge-m3) + Chroma, **API 비용 0원**.
- 18년치, 10만+ 건의 리포트 아카이브를 적재. 오늘 리포트 제목을 쿼리로 과거 유사 리포트를 검색해서(`historical_context()`), 요약 프롬프트에 "과거 관련 리포트" 섹션으로 참고시킴 (look-ahead bias 방지를 위해 `before_date` 필터링).
- `mcp_server.py`(research-archive MCP)가 같은 아카이브를 자연어 질의용으로도 노출.

## 6. 요약 생성 (`summarize.py` + `local_llm.py`)

- **모델**: Qwen/Qwen3-14B, 로컬 GPU(bf16), `transformers.generate()`.
- **LoRA 어댑터 2그룹**: `macro_bond`, `sector_strategy` — 채권 하나 고치려다 섹터·전략까지 흔들리는 교차 간섭을 막으려고 둘로 분리해서 각각 학습(어댑터는 같은 베이스 모델에 둘 다 로드해두고 `set_adapter()`로 전환만 함, 재로딩 없음).
- **카테고리별 temperature**: 매크로/채권 0.5(지표·수치 중심, 일관성 우선), 섹터/투자전략 0.65(여러 리포트 해석·종합 비중 높음).
- **생성 원칙**: "OO증권은 ~라고 밝혔다" 식 나열 금지, "무슨 일 → 왜(경제적 메커니즘) → 그래서 어떤 의미" 3단 구조 강제.
- **투자전략 전용 추가 섹션**: 매크로/채권/섹터 요약을 입력으로 "오늘의 핵심 쟁점 정리"를 짧게 생성(어댑터 끄고 base 모델 사용 — 짧은 과제라 어댑터가 오히려 장문 편향을 유발).

### 반복/언어 드리프트 방지 (`local_llm.trim_runaway_repetition`)

`repetition_penalty=1.2, top_p=0.9`로 생성하지만 가끔 디코딩이 degenerate loop에 빠짐. `no_repeat_ngram_size`는 반복보다 더 나쁜 실패(가비지 출력)를 유발해서 폐기, **생성 후 탐지해서 잘라내는 방식**으로 해결. 세 가지 탐지기를 같이 돌려서 가장 먼저 반복이 시작되는 지점을 기준으로 자름:

1. `_sentence_loop_cutoff` — 마침표 단위 근접중복 문장 반복.
2. `_heading_loop_cutoff` — 마침표 없는 불릿 목록이 헤딩 단위로 통째로 재생성되는 경우.
3. `_language_drift_cutoff` — repetition_penalty를 피하려 같은 내용을 중국어/영어로 다시 쓰는 경우(토큰이 다르면 패널티도 다름). 표·출처 인용·혼용 제목은 오탐 방지로 제외.

이 검사는 `ask_local()` 안에서 카테고리 생성 직후 자동으로 걸림(같은 실행 중 "핵심 쟁점 정리" 프롬프트가 깨끗한 입력을 받아야 하기 때문).

## 7. 최종 점검 (`final_check.py`, 4.5단계)

위 inline 검사는 로컬 모델 산출물만 봄 — DART 기업분석과 뉴스 요약은 둘 다 Claude API 결과라 한 번도 검사 안 됨. `final_check.py`가 같은 `trim_runaway_repetition()`을 재사용해서 **카테고리 4개 + dart_analysis.md + news_summary.md**까지 전부 마지막으로 한 번 더 점검하고, 카테고리가 고쳐지면 digest를 재조립. 빌드/배포 직전 마지막 안전망.

## 8. DART 기업분석 서브에이전트 (내부 전용)

- `dart_client.py`: DART Open API 클라이언트 (`corp_code` 매핑 3,979개 상장사 사전, 공시검색, 재무제표+비율 계산).
- `dart_mcp_server.py`: MCP로 노출 — 공시검색/재무요약(비율 계산 포함)/재무추이(다기간, 누적분기 주의 경고 포함).
- `dart_agent.py`: 별도 `claude -p` 서브프로세스가 그날 섹터+투자전략 리포트를 읽고, **비중 있게 다뤄진(단순 언급 아닌) 국내 상장기업 최대 4곳**을 스스로 골라 공시·재무제표로 교차검증. 투자 판단/전망 금지, look-ahead bias 방지(`as_of_date`=오늘).
- **`DART/<회사명>/`**: 재무제표만 캐시(공시 검색은 캐시 안 함 — 매일 안 바뀌어서 일별 캐시 가치가 적음). 전체 상장사를 미리 받아두지 않고, 에이전트가 실제로 고른 기업만 누적(현재 31개 기업).
- **산출물**: `output/<date>/dart_analysis.md`로만 저장됨 — **더 이상 strategy.md에 붙이지 않음**(2026-11-13 변경). 사이트에는 전혀 노출 안 되는 내부 전용 자료. "DART는 내부적으로만 쓴다"는 원래 의도를 코드 구조로 확정.

## 9. 지식그래프 (`build_graph.py`)

- 기존 파일 구조를 건드리지 않는 **읽기 전용 파생 레이어**. `data/`, `output/`, `DART/`만 읽음.
- 노드: Company(3,979개 상장사 사전), FinancialPeriod, DailyBriefing/Report, DartVerification.
- 엣지: MENTIONS(리포트 텍스트 substring 매칭, 임베딩/LLM 없이 순수 문자열 매칭 — 금융 수치는 정확 조회가 필요해서 벡터 RAG 대신 선택), HAS_PERIOD, VERIFIED(DART 교차검증 이력).
- `networkx.MultiDiGraph` → `node_link_data`로 JSON 직렬화.
- 전체 이력은 `graph/kg.json`(로컬 전용), 사이트에 공개하는 건 `build_site.py`가 매 배포마다 최근 120일만 뽑아 구운 `site/data/graph.json` — 공개 채팅의 `company_lookup` 도구가 이걸 읽음.

## 10. 뉴스 요약 (`news_summary.py`)

NewsMCP(`claude -p` 서브프로세스)로 전날 미국발 메인 + 한국 서브 뉴스를 요약. 응답에 섞여 나오는 자체 마크다운 헤딩은 전부 굵은 글씨로 낮춰서(`demote_headings`), `build_site.py`가 카테고리로 잘못 쪼개는 사고를 방지(2026-10-06에 실제로 겪은 문제).

## 11. 정적 사이트 (`site/` — 별도 git repo, Vercel 배포)

- `build_site.py`가 `output/`을 읽기 전용으로 읽어서 `site/`에만 씀. `site/`는 `research-digest-site` 저장소로 별도 관리, push하면 Vercel이 자동 빌드.
- **구조**: 홈(최신 영업일 시장 지표 카드 + 전날 뉴스 + Reports 카드 + 지수/금리 차트) → Reports(월별 날짜 그리드) → 날짜별 페이지(탭: 매크로/채권/섹터/투자전략) → 채팅.
- **콘텐츠는 평문**(`GATE_ENABLED=False`) — 암호화 게이트 기능(`site_crypto.py`, passphrase 기반 AES-GCM)은 코드에 남아있지만 지금은 꺼져 있음.
- **차트**: Chart.js, 지수는 레벨/연초대비 토글, 금리는 5개국(미/한/독/일/영) 동시 표시, 과거분은 `fetch_history.py`가 FRED/Yahoo/네이버 차트 API로 미리 구워둔 `assets/history.json` + 최근 일별 수집분을 이어붙임.

## 12. 공개 채팅 (`site/api/chat.py`)

- Vercel Python 서버리스 함수. Claude API(`claude-sonnet-5-5`) + 도구 호출 루프(`get_daily_briefing`, `search_briefings`, `company_lookup`).
- 참고 데이터는 `site/data/digests.json`(공개된 브리핑 본문 그대로)과 `site/data/graph.json`(최근 120일 지식그래프) — 둘 다 공개 스냅샷이라 비공개 데이터 접근 없음.
- Upstash Redis REST API로 **IP당 하루 5건** 제한, Upstash 미설정 시 fail-open(제한 없이 통과 — 로컬 테스트용).
- 투자 판단 금지, 날짜 인용 의무화를 시스템 프롬프트로 강제.

## 13. 파인튜닝 (`for_tuning/`)

- Qwen3-14B에 LoRA로 "4종 문체 순환 배정" 등 스타일을 학습. 교차 간섭 문제로 `macro_bond`/`sector_strategy` 그룹별 어댑터 분리(`qwen3_14b_lora_macro_bond`, `qwen3_14b_lora_sector_strategy` — 현재 프로덕션 채택).
- 평가: Claude를 LLM-as-judge로 쓴 5기준 25점 루브릭(정확성/분석적 종합/교차비교/구조·가독성/완결성), 자체 설계(외부 벤치마크 아님). base vs 여러 튜닝 버전(v1/v1b/v2/v2b/그룹분리) 비교 — 상세 수치는 `2026-10-31_finetuning_rubric_eval.md`, `2026-09-14_model_comparison.md` 참고.

## 14. 알려진 미해결 이슈

`2026-10-31_issues_and_fixes_log.md`의 "지금 열려 있는 항목"에 최신 상태로 정리돼 있음 (현재: "OO증권에 따르면" 카탈로그 문체 잔존, 미·한 지표 기준일 분리 표기 미구현, 경미한 영어/한자 code-switching, 공개 채팅 수동 설정 항목 등).
