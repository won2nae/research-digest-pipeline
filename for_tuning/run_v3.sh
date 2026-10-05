#!/bin/bash
# 날짜 분할 기준으로 v1b/v2b를 재학습하고, 같은 테스트셋에서 base·v1b·v2b를 평가한다.
set -e
cd "$(dirname "$0")"
LOG=../logs/v3_pipeline.log
exec >> "$LOG" 2>&1

echo "=== $(date) 학습 v1b 시작 ==="
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True python3 train_lora_v1b.py > ../logs/train_v1b.log 2>&1

echo "=== $(date) 학습 v2b 시작 ==="
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True python3 train_lora_v2b.py > ../logs/train_v2b.log 2>&1

echo "=== $(date) 평가 base ==="
python3 eval_base_v3.py eval_v3_base.jsonl > ../logs/eval_v3_base.log 2>&1

echo "=== $(date) 평가 v1b ==="
ADAPTER_DIR="$PWD/qwen3_14b_lora_v1b" python3 eval_tuned_v3.py eval_v3_v1b.jsonl > ../logs/eval_v3_v1b.log 2>&1

echo "=== $(date) 평가 v2b ==="
ADAPTER_DIR="$PWD/qwen3_14b_lora_v2b" python3 eval_tuned_v3.py eval_v3_v2b.jsonl > ../logs/eval_v3_v2b.log 2>&1

echo "=== $(date) 요약 ==="
python3 summarize_v3.py
echo "=== $(date) 완료 ==="
