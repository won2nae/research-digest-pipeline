"""로컬 오픈소스 모델로 텍스트 생성. API 비용 전혀 없음, GPU 로컬 추론.

Claude Pro 한도와 완전히 무관하게 동작한다. 여러 모델을 바꿔가며 쓸 수 있게
model_name을 인자로 받는다 (한 번에 하나씩 로드/언로드).
"""
import gc
import re
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

DEFAULT_MODEL = "Qwen/Qwen3-8B"
# GPU 0은 이미 다른 작업에서 사용 중이라 회피. 큰 모델(32B 등)은 1,2번 GPU에 자동 분산.
MAX_MEMORY = {0: "0GiB", 1: "45GiB", 2: "45GiB", "cpu": "0GiB"}

# 모델별 LoRA adapter 경로. 등록돼 있으면 로드 시 자동으로 얹힌다.
# (for_tuning/generate_gold_labels.ipynb + train_lora.py로 학습한 결과물)
ADAPTER_PATHS = {
    "Qwen/Qwen3-14B": str(Path(__file__).resolve().parent.parent / "for_tuning" / "qwen3_14b_lora"),
}

_loaded = {}  # model_name -> (model, tokenizer)


def load_model(model_name: str = DEFAULT_MODEL):
    if model_name not in _loaded:
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForCausalLM.from_pretrained(
            model_name, dtype=torch.bfloat16, device_map="auto", max_memory=MAX_MEMORY
        )
        adapter_path = ADAPTER_PATHS.get(model_name)
        if adapter_path and Path(adapter_path).exists():
            model = PeftModel.from_pretrained(model, adapter_path)
            model.eval()
        _loaded[model_name] = (model, tokenizer)
    return _loaded[model_name]


def unload_model(model_name: str):
    if model_name in _loaded:
        del _loaded[model_name]
        gc.collect()
        torch.cuda.empty_cache()


def ask_local(
    prompt: str,
    model_name: str = DEFAULT_MODEL,
    max_new_tokens: int = 4096,
    use_adapter: bool = True,
    repetition_penalty: float = 1.0,
) -> str:
    """use_adapter=False로 주면, LoRA가 등록된 모델이어도 base 모델로만 생성한다.
    (adapter가 학습받지 않은 형태의 과제 - 예: 아주 짧은 요약 - 에 쓰기 위함)"""
    model, tokenizer = load_model(model_name)
    messages = [{"role": "user", "content": prompt}]
    kwargs = {"tokenize": False, "add_generation_prompt": True}
    try:
        text = tokenizer.apply_chat_template(messages, enable_thinking=False, **kwargs)
    except TypeError:
        # enable_thinking을 지원하지 않는 모델(Llama 등)
        text = tokenizer.apply_chat_template(messages, **kwargs)
    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    gen_kwargs = dict(
        max_new_tokens=max_new_tokens,
        temperature=0.6,
        top_p=0.9,
        do_sample=True,
        repetition_penalty=repetition_penalty,
        pad_token_id=tokenizer.eos_token_id,
    )

    is_peft = hasattr(model, "disable_adapter")
    with torch.no_grad():
        if is_peft and not use_adapter:
            with model.disable_adapter():
                output = model.generate(**inputs, **gen_kwargs)
        else:
            output = model.generate(**inputs, **gen_kwargs)

    generated = output[0][inputs["input_ids"].shape[1]:]
    result = tokenizer.decode(generated, skip_special_tokens=True)
    result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
    return result


if __name__ == "__main__":
    print(ask_local("1+1은 몇이야? 숫자만 답해."))
