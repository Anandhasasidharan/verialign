MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4": {"input": 30.00, "output": 60.00},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-3.5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-haiku-3": {"input": 0.25, "output": 1.25},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},
    "claude-opus-4": {"input": 15.00, "output": 75.00},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.0-pro": {"input": 2.00, "output": 8.00},
    "deepseek-chat": {"input": 0.27, "output": 1.10},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "llama-4": {"input": 0.10, "output": 0.40},
    "mistral-large": {"input": 2.00, "output": 6.00},
}

UNKNOWN_RATE = {"input": 1.00, "output": 4.00}


def calculate_cost(model: str, input_tokens: int, output_tokens: int) -> float | None:
    pricing = _find_pricing(model)
    if pricing is None:
        return None
    cost = (input_tokens / 1_000_000 * pricing["input"]) + (
        output_tokens / 1_000_000 * pricing["output"]
    )
    return round(cost, 6)


def estimate_cost(
    model: str, input_tokens: int, target_output_tokens: int = 1024
) -> float | None:
    pricing = _find_pricing(model)
    if pricing is None:
        return None
    cost = (input_tokens / 1_000_000 * pricing["input"]) + (
        target_output_tokens / 1_000_000 * pricing["output"]
    )
    return round(cost, 6)


def list_model_prices() -> dict[str, dict[str, float]]:
    return dict(MODEL_PRICING)


def _find_pricing(model: str) -> dict[str, float] | None:
    model_lower = model.lower().strip()
    if model_lower in MODEL_PRICING:
        return MODEL_PRICING[model_lower]
    for known, pricing in MODEL_PRICING.items():
        if known in model_lower or model_lower in known:
            return pricing
    return None
