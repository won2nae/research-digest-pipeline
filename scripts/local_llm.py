"""로컬 오픈소스 모델로 텍스트 생성. API 비용 전혀 없음, GPU 로컬 추론.

Claude Pro 한도와 완전히 무관하게 동작한다. 여러 모델을 바꿔가며 쓸 수 있게
model_name을 인자로 받는다 (한 번에 하나씩 로드/언로드).
"""
import difflib
import gc
import re
import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

DEFAULT_MODEL = "Qwen/Qwen3-8B"
# GPU 0은 이미 다른 작업에서 사용 중이라 회피. 큰 모델(32B 등)은 1,2번 GPU에 자동 분산.
MAX_MEMORY = {0: "0GiB", 1: "45GiB", 2: "45GiB", "cpu": "0GiB"}

FOR_TUNING = Path(__file__).resolve().parent.parent / "for_tuning"

# 모델별로 "카테고리 그룹 이름 -> adapter 경로"를 등록한다.
# 채권 하나를 고치겠다고 섹터·투자전략까지 같이 흔들리는 걸 막기 위해, 카테고리를
# 두 그룹으로 나눠 어댑터도 따로 학습·적용한다 (교차 평가에서 실제로 bond가
# 묻히는 걸 확인한 뒤 분리하기로 함).
ADAPTER_PATHS = {
    "Qwen/Qwen3-14B": {
        "macro_bond": str(FOR_TUNING / "qwen3_14b_lora_macro_bond"),
        "sector_strategy": str(FOR_TUNING / "qwen3_14b_lora_sector_strategy"),
    },
}
CATEGORY_TO_GROUP = {
    "macro": "macro_bond", "bond": "macro_bond",
    "sector": "sector_strategy", "strategy": "sector_strategy",
}

_loaded = {}  # model_name -> (model, tokenizer, loaded_adapter_names: list[str])


def load_model(model_name: str = DEFAULT_MODEL):
    if model_name not in _loaded:
        tokenizer = AutoTokenizer.from_pretrained(model_name)
        model = AutoModelForCausalLM.from_pretrained(
            model_name, dtype=torch.bfloat16, device_map="auto", max_memory=MAX_MEMORY
        )
        loaded_names = []
        for name, path in ADAPTER_PATHS.get(model_name, {}).items():
            if not Path(path).exists():
                continue
            if not loaded_names:
                model = PeftModel.from_pretrained(model, path, adapter_name=name)
            else:
                model.load_adapter(path, adapter_name=name)
            loaded_names.append(name)
        if loaded_names:
            model.eval()
        _loaded[model_name] = (model, tokenizer, loaded_names)
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
    no_repeat_ngram_size: int = 0,
    adapter_group: str | None = None,
    temperature: float = 0.6,
    top_p: float = 0.9,
) -> str:
    """use_adapter=False로 주면, LoRA가 등록된 모델이어도 base 모델로만 생성한다.
    (adapter가 학습받지 않은 형태의 과제 - 예: 아주 짧은 요약 - 에 쓰기 위함)

    adapter_group: "macro_bond" 또는 "sector_strategy" 중 하나를 주면 해당 어댑터로
    전환해서 생성한다 (둘 다 베이스 모델에 로드돼 있고, 전환만 한다 - 재로딩 없음)."""
    model, tokenizer, loaded_names = load_model(model_name)
    if adapter_group and adapter_group in loaded_names:
        model.set_adapter(adapter_group)
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
        temperature=temperature,
        top_p=top_p,
        do_sample=True,
        repetition_penalty=repetition_penalty,
        pad_token_id=tokenizer.eos_token_id,
    )
    if no_repeat_ngram_size:
        gen_kwargs["no_repeat_ngram_size"] = no_repeat_ngram_size

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
    result = trim_runaway_repetition(result)
    return result


def _sentence_loop_cutoff(text: str, window: int = 10, threshold: float = 0.55, min_matches: int = 3):
    """문장 단위 근접중복 반복(완전 동일 문장 뿐 아니라 "트럼프 대통령은" <->
    "트럼프 대통령이"처럼 살짝 다른 표현으로 번갈아 반복되는 경우도 포함)을 찾아
    그 루프가 시작된 지점의 글자 offset을 반환한다. 못 찾으면 None."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    if len(sentences) < min_matches + 1:
        return None

    starts = []
    pos = 0
    for s in sentences:
        idx = text.find(s, pos)
        starts.append(idx)
        pos = idx + len(s)

    for i in range(len(sentences)):
        matches = [
            j for j in range(max(0, i - window), i)
            if difflib.SequenceMatcher(None, sentences[i], sentences[j]).ratio() > threshold
        ]
        if len(matches) >= min_matches:
            return starts[min(matches)], f"문장 {min(matches)}~{i}"
    return None


def _heading_loop_cutoff(text: str, threshold: float = 0.85, min_prior: int = 2, body_chars: int = 250):
    """## 헤딩 단위 반복(같은 소제목 아래 본문이 통째로 재생성되는 경우)을 찾는다.
    "관련 리포트"·"원자재 코멘트"처럼 같은 소제목이 서로 다른 내용에 재사용되는
    정상적인 경우도 많아서, 헤딩 텍스트만으론 오탐이 많다 (2026-11-01 확인).
    헤딩 + 그 아래 본문 앞부분을 합쳐서 비교해야 "같은 제목, 다른 내용"과
    "같은 제목, 같은 내용(진짜 반복)"을 구분할 수 있다."""
    headers = list(re.finditer(r"^#{1,6}\s+(.+)$", text, re.MULTILINE))
    if len(headers) < min_prior + 1:
        return None

    blocks = []
    for i, m in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else min(m.end() + body_chars, len(text))
        combo = m.group(1).strip() + " " + text[m.end():end].strip()[:body_chars]
        blocks.append((m.start(), combo))

    for i in range(len(blocks)):
        prior = [
            j for j in range(i)
            if difflib.SequenceMatcher(None, blocks[i][1], blocks[j][1]).ratio() > threshold
        ]
        if len(prior) >= min_prior:
            return blocks[i][0], f"헤딩 {prior[0]}~{i}"
    return None


def trim_runaway_repetition(text: str) -> str:
    """repetition_penalty로도 못 막는 디코딩 degenerate loop을 감지해서, 반복이
    시작되는 지점에서 잘라낸다.

    두 가지 방식을 같이 쓴다 (2026-11-01, 운영 로그로 둘 다 필요함을 확인):
    1. 문장 단위 근접중복 (`_sentence_loop_cutoff`) — 마침표로 끝나는 서술문 반복.
    2. 헤딩 단위 반복 (`_heading_loop_cutoff`) — 불릿 목록처럼 마침표 없이
       "### 소제목" 아래 본문이 통째로 재생성되는 경우. 1번만으로는 마침표가
       없는 불릿 반복을 못 잡아서 추가함 (output/2026-11-02 테스트에서 발견).
    둘 중 더 일찍(앞쪽에서) 반복이 시작된 지점을 기준으로 자른다.

    no_repeat_ngram_size로 생성 자체를 막아봤으나 비문/가비지 출력으로 더 나쁘게
    터져서, 생성은 그대로 두고 후처리로 걸러내는 쪽을 택함."""
    candidates = []
    r1 = _sentence_loop_cutoff(text)
    if r1:
        candidates.append(r1)
    r2 = _heading_loop_cutoff(text)
    if r2:
        candidates.append(r2)
    if not candidates:
        return text

    cut_at, desc = min(candidates, key=lambda c: c[0])
    cut = text[:cut_at].rstrip()
    print(f"[decoding] 반복 루프 감지({desc}), {len(text) - len(cut)}자 잘라냄", file=sys.stderr)
    return cut


if __name__ == "__main__":
    print(ask_local("1+1은 몇이야? 숫자만 답해."))
