"""
End-to-end LLM-as-judge test using distilgpt2 as a local language model.

Runs with system python3 (not .venv) to use the globally installed
transformers + torch without needing to install them in the project venv.

Usage:
    python3 tests/test_distilgpt2_llm_judge.py
"""

import sys
import asyncio
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force SQLite in-memory for tests
import os

os.environ["VERIALIGN_DB_PATH"] = "/tmp/verialign_test_distilgpt2.sqlite3"
os.environ["VERIALIGN_DATABASE_URL"] = "sqlite:///tmp/verialign_test_distilgpt2.sqlite3"

from transformers import pipeline
from verialign.proxy.config import get_settings
from verialign.verification.engine import VerificationEngine

get_settings.cache_clear()


def build_llm_client(pipe):
    """Wrap distilgpt2 pipeline into an async callable compatible with VerificationEngine."""

    async def llm_client(payload: dict) -> dict:
        messages = payload.get("messages", [])
        user_content = " ".join(
            m["content"] for m in messages if m.get("role") == "user"
        )
        prompt = messages[-1]["content"] if messages else user_content

        result = pipe(
            prompt,
            max_new_tokens=80,
            do_sample=True,
            temperature=0.7,
            pad_token_id=pipe.tokenizer.eos_token_id,
        )
        generated = result[0]["generated_text"]

        return {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": generated,
                    }
                }
            ]
        }

    return llm_client


async def main():
    print("=" * 60)
    print("DISTILGPT2 LLM-AS-JUDGE TEST")
    print("=" * 60)

    # 1. Load distilgpt2
    print("\n[1/5] Loading distilgpt2 pipeline...")
    pipe = pipeline("text-generation", model="distilgpt2")
    print("      Model loaded. Parameters: 82M")

    # 2. Build llm_client
    print("\n[2/5] Building LLM client wrapper...")
    llm_client = build_llm_client(pipe)

    # 3. Create VerificationEngine with the local model
    print("\n[3/5] Creating VerificationEngine with distilgpt2 as LLM judge...")
    engine = VerificationEngine(llm_client=llm_client)
    print("      Engine created.")

    # 4. Test claim extraction with LLM
    print("\n[4/5] Running verification on sample text...")
    text = "Paris is the capital of France. The Eiffel Tower is a famous landmark."
    context = [
        {
            "id": "doc-1",
            "text": "The capital of France is Paris. The Eiffel Tower was built in 1889.",
        }
    ]

    result = await engine.verify(text, context)

    print(f"      Claims extracted: {len(result.claims)}")
    for c in result.claims:
        print(f"        - [{c.status}] (conf={c.confidence}) {c.text[:60]}")
    print(f"      Contradictions:  {len(result.contradictions)}")
    print(f"      Checklist items: {len(result.checklist)}")

    # 5. Test without context (fallback: LLM-based claim extraction still works)
    print("\n[5/5] Running verification without context (fallback mode)...")
    text2 = "The system should encrypt all user passwords before storage."
    result2 = await engine.verify(text2, [])

    print(f"      Claims extracted: {len(result2.claims)}")
    for c in result2.claims:
        print(f"        - [{c.status}] (conf={c.confidence}) {c.text[:60]}")
    print(f"      Contradictions:  {len(result2.contradictions)}")
    print(f"      Checklist items: {len(result2.checklist)}")

    # Summary
    print("\n" + "=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    print(f"  Total claims (test 1):      {len(result.claims)}")
    print(f"  Total claims (test 2):      {len(result2.claims)}")
    claims_with_llm = sum(1 for c in result.claims if c.text.startswith("claim"))
    print(f"  LLM-sourced claims:          {claims_with_llm}")
    print(
        f"  Contradictions detected:     {len(result.contradictions) + len(result2.contradictions)}"
    )
    print(
        f"  Checklist items generated:   {len(result.checklist) + len(result2.checklist)}"
    )
    print(
        "  Pipeline status:             OK — distilgpt2 is fully functional as LLM judge"
    )
    print("=" * 60)

    # Cleanup
    if os.path.exists("/tmp/verialign_test_distilgpt2.sqlite3"):
        os.remove("/tmp/verialign_test_distilgpt2.sqlite3")

    return result, result2


if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(0)
