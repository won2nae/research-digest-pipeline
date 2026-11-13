#!/bin/bash
# 카테고리 그룹별(macro_bond / sector_strategy) 어댑터를 따로 학습하고,
# 각자의 테스트셋에서 base와 비교 평가한다.
set -e
cd "$(dirname "$0")"
export PATH="/home/kjw/miniconda3/bin:$PATH"
LOG=../logs/group_training.log
exec >> "$LOG" 2>&1

echo "=== $(date) 학습 macro_bond (40건) ==="
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True python3 train_lora_macro_bond.py

echo "=== $(date) 학습 sector_strategy (87건) ==="
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True python3 train_lora_sector_strategy.py

echo "=== $(date) 평가 base (macro_bond 테스트셋) ==="
python3 eval_base_macro_bond.py eval_group_base_macro_bond.jsonl

echo "=== $(date) 평가 macro_bond 어댑터 ==="
ADAPTER_DIR="$PWD/qwen3_14b_lora_macro_bond" python3 eval_tuned_macro_bond.py eval_group_tuned_macro_bond.jsonl

echo "=== $(date) 평가 base (sector_strategy 테스트셋) ==="
python3 eval_base_sector_strategy.py eval_group_base_sector_strategy.jsonl

echo "=== $(date) 평가 sector_strategy 어댑터 ==="
ADAPTER_DIR="$PWD/qwen3_14b_lora_sector_strategy" python3 eval_tuned_sector_strategy.py eval_group_tuned_sector_strategy.jsonl

echo "=== $(date) 요약 ==="
python3 summarize_group_eval.py

echo "=== $(date) 완료 ==="
