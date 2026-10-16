import asyncio
import json
import random
import sqlite3
from datetime import datetime, timedelta, timezone

DB_PATH = "./verialign.sqlite3"

MODELS = ["gpt-4", "gpt-3.5-turbo", "claude-3-haiku", "claude-3-sonnet", "demo"]

CONTEXTS = [
    {
        "id": "doc-1",
        "text": "VeriAlign is a verification support proxy for LLM outputs. It intercepts requests and adds verification metadata.",
    },
    {
        "id": "doc-2",
        "text": "The Earth orbits the Sun at an average distance of 149.6 million kilometers.",
    },
    {
        "id": "doc-3",
        "text": "Python is a high-level programming language created by Guido van Rossum in 1991.",
    },
    {
        "id": "doc-4",
        "text": "The capital of France is Paris. The population is approximately 2.1 million.",
    },
    {
        "id": "doc-5",
        "text": "Machine learning models require training data. More data generally improves accuracy.",
    },
]

PROMPTS = [
    (
        "What is VeriAlign?",
        "VeriAlign is a verification support proxy for LLM outputs. It can extract factual claims and compare them with supplied context.",
    ),
    (
        "How far is Earth from the Sun?",
        "The Earth orbits the Sun at an average distance of 149.6 million kilometers.",
    ),
    (
        "Tell me about Python",
        "Python is a high-level programming language created by Guido van Rossum in 1991. It is widely used for web development and data science.",
    ),
    (
        "What is the capital of France?",
        "The capital of France is Paris. The population is approximately 2.1 million people.",
    ),
    (
        "How does machine learning work?",
        "Machine learning models require training data. More data generally improves accuracy. The model learns patterns from the data.",
    ),
    ("What is 2+2?", "2+2 equals 4. This is a basic arithmetic fact."),
    ("Who wrote Hamlet?", "Hamlet was written by William Shakespeare around 1600."),
    (
        "What is the speed of light?",
        "The speed of light in vacuum is approximately 299,792,458 meters per second.",
    ),
    (
        "Explain photosynthesis",
        "Photosynthesis is the process by which plants convert sunlight into energy. Chlorophyll in leaves captures light energy.",
    ),
    (
        "What is an API?",
        "An API (Application Programming Interface) allows different software systems to communicate with each other.",
    ),
]

HALLUCINATED_PROMPTS = [
    (
        "What is VeriAlign?",
        "VeriAlign is a database management system created by Microsoft in 2020.",
    ),
    (
        "How far is Earth from the Sun?",
        "The Earth orbits the Sun at an average distance of 50 million kilometers.",
    ),
    (
        "Tell me about Python",
        "Python is a low-level programming language created by Bill Gates in 1995.",
    ),
    (
        "What is the capital of France?",
        "The capital of France is Lyon. The population is approximately 500,000.",
    ),
    (
        "How does machine learning work?",
        "Machine learning models do not require any training data. They work purely by magic.",
    ),
]

CONTRADICTION_PROMPTS = [
    (
        "Compare options",
        "Option A is better than Option B. Option B is better than Option A.",
    ),
    ("Analyze trends", "The stock market is rising. The stock market is falling."),
    (
        "Evaluate features",
        "Feature X increases performance. Feature X decreases performance.",
    ),
]

TASK_CATEGORIES = [
    "question_answering",
    "coding",
    "writing",
    "analysis",
    "summarization",
    "general",
]


async def generate_verification_data(prompt: str, response: str, context: list) -> dict:
    from dataclasses import replace

    from verialign.verification.checklist_generator import ChecklistGenerator
    from verialign.verification.claim_extractor import ClaimExtractor
    from verialign.verification.contradiction_detector import ContradictionDetector
    from verialign.verification.models import VerificationResult, VerifiedClaim
    from verialign.verification.source_grounder import SourceGrounder
    from verialign.verification.trust_scorer import TrustScorer

    claim_extractor = ClaimExtractor()
    # Demo seeding must stay fast and offline: skip NLI + embedding models.
    source_grounder = SourceGrounder(use_nli=False, use_semantic=False)
    contradiction_detector = ContradictionDetector()
    checklist_generator = ChecklistGenerator()

    claim_texts = await claim_extractor.extract(response)

    claims: list[VerifiedClaim] = []
    for idx, claim_text in enumerate(claim_texts):
        status, confidence, sources = await source_grounder.ground(claim_text, context)
        claims.append(
            VerifiedClaim(
                text=claim_text,
                status=status,
                confidence=round(confidence, 3),
                sources=sources,
                claim_id=f"claim-{idx}",
                sentence_offset=idx,
            ),
        )

    contradictions = contradiction_detector.detect(claim_texts)
    checklist = checklist_generator.generate(
        response,
        claim_texts,
        [claim.to_dict() for claim in claims],
    )

    # Build the real model so seeded traces match the production schema exactly
    # (including summary/profile/trust_score) instead of a hand-rolled dict.
    result = VerificationResult(
        claims=claims,
        contradictions=contradictions,
        checklist=checklist,
    )
    result = replace(result, trust_score=TrustScorer().score(result))
    return result.to_dict()


def create_sample_traces(count: int = 100, db_path: str = DB_PATH) -> None:
    """Generate ``count`` synthetic traces for demos and the TUI."""
    asyncio.run(_create_sample_traces(count, db_path))


async def _create_sample_traces(count: int, db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS traces (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            model TEXT NOT NULL,
            request_json TEXT NOT NULL,
            response_json TEXT NOT NULL,
            verification_json TEXT NOT NULL
        )
    """)

    batch_size = 100
    rows = []

    for i in range(count):
        model = random.choice(MODELS)
        context = random.sample(CONTEXTS, k=random.randint(1, 3))

        prompt_type = random.choices(
            ["normal", "hallucinated", "contradiction"],
            weights=[0.7, 0.2, 0.1],
        )[0]

        if prompt_type == "normal":
            prompt, response = random.choice(PROMPTS)
        elif prompt_type == "hallucinated":
            prompt, response = random.choice(HALLUCINATED_PROMPTS)
        else:
            prompt, response = random.choice(CONTRADICTION_PROMPTS)

        days_ago = random.randint(0, 30)
        hours_ago = random.randint(0, 23)
        minutes_ago = random.randint(0, 59)
        created_at = datetime.now(timezone.utc) - timedelta(
            days=days_ago,
            hours=hours_ago,
            minutes=minutes_ago,
        )

        request_payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "metadata": {"context": context},
            "temperature": 0.7,
            "max_tokens": 1000,
        }

        response_payload = {
            "id": f"chatcmpl-{random.randint(100000, 999999)}",
            "object": "chat.completion",
            "created": int(created_at.timestamp()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": response},
                    "finish_reason": "stop",
                },
            ],
            "usage": {
                "prompt_tokens": random.randint(50, 200),
                "completion_tokens": random.randint(50, 300),
                "total_tokens": random.randint(100, 500),
            },
        }

        verification = await generate_verification_data(prompt, response, context)
        response_payload["verification"] = verification

        rows.append(
            (
                created_at.isoformat(),
                model,
                json.dumps(request_payload),
                json.dumps(response_payload),
                json.dumps(verification),
            ),
        )

        if len(rows) >= batch_size or i == count - 1:
            conn.executemany(
                "INSERT INTO traces (created_at, model, request_json, response_json, verification_json) VALUES (?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
            rows = []

    conn.close()


if __name__ == "__main__":
    import sys

    count = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    create_sample_traces(count)
