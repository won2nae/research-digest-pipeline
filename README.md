# 리서치 AI

한국 증권사 리서치 리포트를 매일 수집·요약하는 자동화 브리핑 시스템. 매일 아침(07:00 KST, cron) 네이버 파이낸셜·미래에셋 리포트를 모아 매크로/채권/섹터/투자전략 4개 카테고리로 요약하고, DART 전자공시로 기업 분석을 교차검증한 뒤, 정적 사이트로 배포한다.

## 핵심 원칙

1. **AI는 사실 정리자다, 판단자가 아니다.** 투자 판단·전망·추천을 제시하지 않는다 — 리포트 간 근거를 대조해서 보여주기만 한다. 이 원칙은 코드(디스클레이머)에 고정돼 있다.
2. **로컬 모델을 기본으로, Claude는 꼭 필요한 곳에만.** 매일 반복되는 대량 요약은 로컬 Qwen3-14B(+LoRA)로 API 비용 없이 처리하고, 도구 호출이 필요한 서브에이전트(DART 기업분석, 뉴스 요약)에만 Claude를 쓴다.
3. **새 기능은 기존 구조를 건드리지 않는다.** 지식그래프, 개인 투자 신호 같은 추가 기능은 기존 파일을 읽기만 하는 분리된 레이어로 만든다.

## 매일 하는 일 (`scripts/run_daily.sh`, cron 07:00 KST)

```
수집 → 매크로 충격 탐지 → 전날 뉴스 요약 → 벡터DB 적재
  → 요약 생성(+DART 기업분석) → 최종 점검(반복/언어드리프트)
  → 정적 사이트 재생성 + 배포
```

## 디렉터리 구조

```
scripts/        파이프라인 전체 코드
output/<date>/  카테고리별 요약·DART 분석·digest (git 비공개)
investment_output/<date>/  개인 투자 신호 (output과 동급 위치, git 비공개, 사이트에 안 올라감)
data/<date>/    원문 리포트·매크로 지표·뉴스 요약 (git 비공개)
DART/<회사명>/  DART 재무제표 캐시
for_tuning/     LoRA 파인튜닝 학습·평가 스크립트
site/           정적 사이트 — 별도 git repo(research-digest-site)로 관리, Vercel 배포
paperwork/      운영 기록·평가 노트·아키텍처 문서
```

## 더 보기

- **전체 아키텍처**: [`paperwork/2026-11-14_architecture.md`](paperwork/2026-11-14_architecture.md)
- **변경 이력**: [`RELEASE_NOTES.md`](RELEASE_NOTES.md)
- **문제·수정 기록**: [`paperwork/2026-10-31_issues_and_fixes_log.md`](paperwork/2026-10-31_issues_and_fixes_log.md)
- **모델/평가 노트**: [`paperwork/2026-09-14_model_comparison.md`](paperwork/2026-09-14_model_comparison.md), [`paperwork/2026-10-31_finetuning_rubric_eval.md`](paperwork/2026-10-31_finetuning_rubric_eval.md)
