"""LoRA adapter를 얹은 Qwen3-14B 추론 (튜닝 후 평가용).

scripts/local_llm.py와 인터페이스를 맞추되, 베이스 모델 위에 LoRA adapter를 로드한다.
GPU 0은 다른 프로세스가 점유 중이라 회피.
"""
import os

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "1,2")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import re

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE_MODEL = "Qwen/Qwen3-14B"
ADAPTER_DIR = os.environ.get(
    "ADAPTER_DIR", str(__import__("pathlib").Path(__file__).resolve().parent / "qwen3_14b_lora")
)
MAX_MEMORY = {0: "45GiB", 1: "45GiB", "cpu": "0GiB"}

_model = None
_tokenizer = None


def _load():
    global _model, _tokenizer
    if _model is None:
        _tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
        base = AutoModelForCausalLM.from_pretrained(
            BASE_MODEL, dtype=torch.bfloat16, device_map="auto", max_memory=MAX_MEMORY
        )
        _model = PeftModel.from_pretrained(base, ADAPTER_DIR)
        _model.eval()
    return _model, _tokenizer


def ask_tuned(prompt: str, max_new_tokens: int = 3000) -> str:
    model, tokenizer = _load()
    messages = [{"role": "user", "content": prompt}]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to(model.device)
    with torch.no_grad():
        output = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=0.6,
            top_p=0.9,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id,
        )
    generated = output[0][inputs["input_ids"].shape[1]:]
    result = tokenizer.decode(generated, skip_special_tokens=True)
    result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
    return result


if __name__ == "__main__":
    print(ask_tuned("1+1은 몇이야? 숫자만 답해."))
