"""Compare rules with an opt-in, locally hosted checkpoint on the frozen FEVER rows."""

import argparse
import asyncio
import hashlib
import json
import time
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from eval.metrics import latency_quantiles
from eval.run_eval import DATASET, evaluate, keyword_engine
from verialign.verification.claim_extractor import ClaimSelection


async def run(checkpoint: Path, model_id: str, max_ms: int) -> dict:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    torch.set_num_threads(2)
    tokenizer = AutoTokenizer.from_pretrained(checkpoint, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(checkpoint, local_files_only=True).eval()
    counts: Counter[str] = Counter()
    durations = []
    timeout_seconds = max_ms * 0.0004

    def complete(request: dict) -> dict:
        counts["calls"] += 1
        start = time.perf_counter()
        try:
            inputs = tokenizer.apply_chat_template(
                request["messages"],
                tokenize=True,
                add_generation_prompt=True,
                return_dict=True,
                return_tensors="pt",
            )
            with torch.inference_mode():
                tokens = model.generate(
                    **inputs, max_new_tokens=request["max_tokens"], do_sample=False
                )
            content = tokenizer.decode(
                tokens[0, inputs["input_ids"].shape[1] :], skip_special_tokens=True
            )
        except Exception as error:
            counts[f"error:{type(error).__name__}"] += 1
            raise
        elapsed = time.perf_counter() - start
        durations.append(elapsed * 1000)
        if elapsed >= timeout_seconds:
            counts["over_deadline"] += 1
        try:
            selection = ClaimSelection.model_validate_json(content)
        except ValidationError:
            counts["invalid_json_or_schema"] += 1
        else:
            candidates = json.loads(request["messages"][-1]["content"])
            if all(0 <= index < len(candidates) for index in selection.claim_indices):
                counts["valid_selection"] += 1
                if selection.claim_indices:
                    counts["nonempty_selection"] += 1
            else:
                counts["out_of_range"] += 1
        return {"choices": [{"message": {"content": content}}]}

    data = DATASET.read_bytes()
    rows = [json.loads(line) for line in data.splitlines()]
    rules = await evaluate(rows)
    engine = keyword_engine(llm_client=complete, llm_extractor_model=model_id, max_ms=max_ms)
    llm = await evaluate(rows, engine)
    if any(key.startswith("error:") for key in counts):
        raise RuntimeError(f"Local inference did not complete successfully: {dict(counts)}")
    return {
        "checkpoint": model_id,
        "dataset_sha256": hashlib.sha256(data).hexdigest(),
        "device": "CPU",
        "torch_threads": torch.get_num_threads(),
        "timeout_seconds": engine.claim_extractor.llm_timeout_seconds,
        "model_responses": dict(counts),
        "completed_model_latency": latency_quantiles(durations) if durations else None,
        "rules": rules,
        "rules_with_llm": llm,
        "delta_from_rules": {
            "f1": {
                label: round(llm["labels"][label]["f1"] - score["f1"], 6)
                for label, score in rules["labels"].items()
            },
            "ece": round(llm["trust_calibration"]["ece"] - rules["trust_calibration"]["ece"], 6),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-ms", type=int, default=5000)
    args = parser.parse_args()
    if args.max_ms <= 0:
        parser.error("--max-ms must be positive")
    result = asyncio.run(run(args.checkpoint, args.model_id, args.max_ms))
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {key: result[key] for key in ("checkpoint", "model_responses", "delta_from_rules")},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
