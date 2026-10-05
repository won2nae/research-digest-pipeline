#!/bin/bash
# 매일 실행되는 전체 파이프라인: 수집 -> 충격 탐지 -> 벡터DB 적재 -> 과거 맥락 포함 요약
# cron은 기본 환경변수가 최소라서 PATH를 명시적으로 지정한다.
export PATH="/home/kjw/miniconda3/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
set -e
cd "$(dirname "$0")/.."

DATE_ARG="${1:-$(date +%F)}"
if [ "$DATE_ARG" = "yesterday" ]; then
    DATE="$(date -d yesterday +%F)"
else
    DATE="$DATE_ARG"
fi

if [ "$(date -d "$DATE" +%u)" -ge 6 ]; then
    echo "=== [$DATE] 주말이라 수집·요약을 건너뜁니다 ==="
    exit 0
fi

echo "=== [$DATE] 1. 리포트 수집 (전체 증권사) ==="
python3 scripts/collect.py "$DATE"

echo "=== [$DATE] 2. 매크로 충격 지표 탐지 ==="
python3 scripts/macro_shock.py "$DATE"

echo "=== [$DATE] 3. 벡터DB 적재 ==="
python3 scripts/vectorstore.py "$DATE"

echo "=== [$DATE] 4. 요약 생성 ==="
python3 scripts/summarize.py "$DATE"

echo "=== [$DATE] 5. 정적 사이트 재생성 + 배포 ==="
python3 scripts/build_site.py
cd site
git add -A
if ! git diff --cached --quiet; then
    git commit -q -m "Update digest site: $DATE"
    git push -q origin main
    echo "사이트 배포 완료 (push -> Vercel 자동 빌드)"
else
    echo "사이트 변경 없음 (push 생략)"
fi
cd ..

echo "=== [$DATE] 완료: output/$DATE/digest_$DATE.md ==="
