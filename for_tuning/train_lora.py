"""Qwen3-14B LoRA SFT 학습 (Claude gold label distillation).

train.jsonl(127건)로 학습. 원본 모델은 그대로 두고 LoRA adapter만 별도 저장하므로
언제든 떼어내면 원상복구 가능하다.
"""
import os

# GPU 0은 다른 프로세스가 점유 중이라, Accelerate가 내부적으로 기본 디바이스(cuda:0)에
# 연산을 흘리는 걸 막기 위해 아예 프로세스에서 안 보이게 마스킹한다 (torch import 전에 설정 필수).
os.environ["CUDA_VISIBLE_DEVICES"] = "1,2"
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import sys
from pathlib import Path

import torch
from datasets import load_dataset
from peft import LoraConfig
from transformers import AutoModelForCausalLM, AutoTokenizer
from trl import SFTConfig, SFTTrainer

ROOT = Path(__file__).resolve().parent.parent
MODEL_NAME = "Qwen/Qwen3-14B"
TRAIN_FILE = Path(__file__).resolve().parent / "train.jsonl"
OUTPUT_DIR = Path(__file__).resolve().parent / "qwen3_14b_lora"

# CUDA_VISIBLE_DEVICES=1,2 마스킹 이후에는 이 두 GPU가 각각 0,1로 재넘버링된다.
MAX_MEMORY = {0: "45GiB", 1: "45GiB", "cpu": "0GiB"}
MAX_LENGTH = 8192  # OOM 방지를 위해 축소 (중앙값 ~5.5K는 커버, 긴 예시는 일부 잘림)


def main():
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME, dtype=torch.bfloat16, device_map="auto", max_memory=MAX_MEMORY
    )

    model.enable_input_require_grads()  # device_map + PEFT + gradient checkpointing 조합에서 필수

    dataset = load_dataset("json", data_files=str(TRAIN_FILE), split="train")
    print(f"학습 예시: {len(dataset)}건")

    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        task_type="CAUSAL_LM",
    )

    sft_config = SFTConfig(
        output_dir=str(OUTPUT_DIR),
        num_train_epochs=3,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_steps=5,
        bf16=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        logging_steps=1,
        save_strategy="epoch",
        max_length=MAX_LENGTH,
        packing=False,
        loss_type="nll",  # chunked_nll(기본값)이 이 transformers 버전과 호환 문제 있어 회피
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        args=sft_config,
        train_dataset=dataset,
        peft_config=lora_config,
        processing_class=tokenizer,
    )

    trainer.train()
    trainer.save_model(str(OUTPUT_DIR))
    print(f"\n학습 완료. LoRA adapter 저장 위치: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
