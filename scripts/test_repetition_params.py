"""repetition_penalty를 1.2보다 올리거나 top_k를 추가하면 반복 루프가 줄어드는지
실험. trim_runaway_repetition으로 사후에 자르지 않은 '원본' 생성 결과에 대해
반복 탐지만 돌려서, 각 설정이 실제로 반복을 얼마나 줄이는지 비교한다.

알려진 반복 유발 프롬프트(2026-10-30 투자전략, 과거 3차례 반복 재현됨)로 고정.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from local_llm import load_model, _sentence_loop_cutoff, _heading_loop_cutoff
from summarize import DIGEST_PROMPT, CATEGORY_LABELS, load_reports, format_reports, historical_context, load_shock_summary
import torch

ROOT = Path(__file__).resolve().parent.parent
MODEL = "Qwen/Qwen3-14B"
TODAY = "2026-10-30"


def build_prompt():
    data_dir = ROOT / "data" / TODAY
    label, kr_label = "strategy", CATEGORY_LABELS["strategy"]
    reports = load_reports(data_dir, label)
    history = historical_context(reports, label, TODAY)
    shock_summary = load_shock_summary(data_dir)
    return DIGEST_PROMPT.format(
        today=TODAY, label=kr_label, content=format_reports(reports), history=history,
        shocks=shock_summary,
    )


def generate_raw(prompt, repetition_penalty, top_k):
    model, tokenizer, loaded_names = load_model(MODEL)
    if "sector_strategy" in loaded_names:
        model.set_adapter("sector_strategy")
    messages = [{"role": "user", "content": prompt}]
    text = tokenizer.apply_chat_template(messages, enable_thinking=False, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    gen_kwargs = dict(
        max_new_tokens=8192, temperature=0.65, top_p=0.9, do_sample=True,
        repetition_penalty=repetition_penalty, pad_token_id=tokenizer.eos_token_id,
    )
    if top_k:
        gen_kwargs["top_k"] = top_k

    with torch.no_grad():
        output = model.generate(**inputs, **gen_kwargs)
    generated = output[0][inputs["input_ids"].shape[1]:]
    result = tokenizer.decode(generated, skip_special_tokens=True)
    import re
    result = re.sub(r"<think>.*?</think>", "", result, flags=re.DOTALL).strip()
    return result


def diagnose(text):
    r1 = _sentence_loop_cutoff(text)
    r2 = _heading_loop_cutoff(text)
    candidates = [r for r in (r1, r2) if r]
    if not candidates:
        return None
    cut_at, desc = min(candidates, key=lambda c: c[0])
    return {"cut_at": cut_at, "desc": desc, "would_remove": len(text) - cut_at, "total_len": len(text)}


def main():
    prompt = build_prompt()
    print(f"프롬프트 길이: {len(prompt)}자\n")

    configs = [
        ("baseline (rp=1.2, top_k 없음 - 현재 프로덕션)", 1.2, None),
        ("rp=1.3", 1.3, None),
        ("rp=1.4", 1.4, None),
        ("rp=1.2 + top_k=50", 1.2, 50),
        ("rp=1.3 + top_k=50", 1.3, 50),
    ]

    results = []
    for name, rp, tk in configs:
        print(f"=== {name} 생성 중... ===")
        text = generate_raw(prompt, rp, tk)
        diag = diagnose(text)
        results.append((name, text, diag))
        if diag:
            print(f"  -> 반복 감지됨: {diag['desc']}, {diag['would_remove']}자 날아갈 것 (전체 {diag['total_len']}자)")
        else:
            print(f"  -> 반복 없음 (전체 {len(text)}자)")
        print()

    print("\n=== 요약 ===")
    for name, text, diag in results:
        status = f"반복 있음 ({diag['would_remove']}자/{diag['total_len']}자)" if diag else f"깨끗함 ({len(text)}자)"
        print(f"- {name}: {status}")

    out_dir = ROOT / "logs" / "repetition_param_test"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text, diag in results:
        safe = name.split(" ")[0].replace("=", "").replace("+", "_").replace(",", "")
        (out_dir / f"{safe}.md").write_text(text, encoding="utf-8")
    print(f"\n전체 생성 결과 저장: {out_dir}")


if __name__ == "__main__":
    main()
