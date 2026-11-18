"""Evaluate the VeriAlign checkout on the fixed FEVER development slice."""

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sqlite3
import tempfile
import time
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI, Request

import verialign
from eval.build_dataset import normalize_claim
from eval.metrics import Prediction, latency_quantiles, summarize
from verialign.verification.engine import VerificationEngine
from verialign.verification.overlay import Overlay

DATASET = Path(__file__).parent / "datasets" / "fever_dev_300.jsonl"
LATENCY_WARMUP = 10
CHAT_PATH = "/v1/chat/completions"
PROFILE = "offline-keyword-v1"


def keyword_engine(**kwargs) -> VerificationEngine:
    engine = VerificationEngine(**{**kwargs, "use_nli": False, "use_rescoring": False})
    engine.source_grounder.use_semantic = False
    return engine


async def predict(rows: list[dict], engine: VerificationEngine) -> list[Prediction]:
    predictions = []
    for row in rows:
        try:
            result = await engine.verify(row["claim"], row["context"])
            overlay = Overlay.from_result(result)
        except Exception as exc:
            raise RuntimeError(f"Evaluation failed on FEVER ID {row['id']}") from exc
        target = normalize_claim(row["claim"])
        label = next(
            (claim.label for claim in overlay.claims if normalize_claim(claim.text) == target),
            "missing_claim",
        )
        predictions.append(Prediction(row["expected"], label, overlay.trust_score))
    return predictions


async def evaluate(rows: list[dict], engine: VerificationEngine | None = None) -> dict:
    return summarize(await predict(rows, engine if engine is not None else keyword_engine()))


async def timed_post(client: httpx.AsyncClient, payload: dict) -> tuple[float, dict]:
    start = time.perf_counter_ns()
    response = await client.post(CHAT_PATH, json=payload)
    elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
    response.raise_for_status()
    return elapsed_ms, response.json()


async def measure_latency(samples: int) -> dict:
    from verialign.proxy import config

    stub = FastAPI()

    @stub.post(CHAT_PATH)
    async def completion(request: Request):
        payload = await request.json()
        return {
            "id": "eval-completion",
            "object": "chat.completion",
            "model": payload["model"],
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": payload["messages"][0]["content"]},
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
        }

    raw_times = []
    proxy_times = []
    paired_overhead = []
    with (
        tempfile.TemporaryDirectory(prefix="verialign-eval-") as tmp,
        patch.dict(os.environ, {}, clear=True),
    ):
        settings = config.Settings(
            _env_file=None,
            upstream_base_url="http://eval-upstream/v1",
            upstream_api_key="local-eval-fixture",
            proxy_api_key="local-eval-client",
            db_path=str(Path(tmp) / "traces.sqlite3"),
            rate_limit_requests_per_minute=samples + LATENCY_WARMUP + 1,
            rate_limit_tokens_per_minute=(samples + LATENCY_WARMUP + 1) * 1000,
            use_nli=False,
        )
        with patch.object(config, "get_settings", new=lambda: settings):
            from verialign.proxy import main as proxy
            from verialign.proxy.routing import provider_router

            async with (
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=stub), base_url="http://eval-upstream"
                ) as raw,
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=proxy.app),
                    base_url="http://eval-proxy",
                    headers={"Authorization": "Bearer local-eval-client"},
                ) as verified,
            ):
                with (
                    patch.object(proxy, "get_settings", new=lambda: settings),
                    patch.object(proxy, "configure_logging", new=lambda: None),
                    patch.object(proxy, "VerificationEngine", new=keyword_engine),
                    patch.object(provider_router, "_http_client", raw),
                ):
                    async with proxy.lifespan(proxy.app):
                        for i in range(samples + LATENCY_WARMUP):
                            claim = f"The Paris entry uses reference number {i}."
                            payload = {
                                "model": "eval-upstream",
                                "messages": [{"role": "user", "content": claim}],
                                "metadata": {"context": [{"id": "eval-source", "text": claim}]},
                            }
                            if i % 2:
                                proxy_ms, actual = await timed_post(verified, payload)
                                raw_ms, control = await timed_post(raw, payload)
                            else:
                                raw_ms, control = await timed_post(raw, payload)
                                proxy_ms, actual = await timed_post(verified, payload)
                            if actual["choices"] != control["choices"]:
                                raise RuntimeError("Raw and proxied completion content differs")
                            overlay = Overlay.model_validate(actual["verification"])
                            if overlay.status != "complete" or not overlay.claims:
                                raise RuntimeError("Latency probe did not verify a claim")
                            if i >= LATENCY_WARMUP:
                                raw_times.append(raw_ms)
                                proxy_times.append(proxy_ms)
                                paired_overhead.append(proxy_ms - raw_ms)
    return {
        "transport": "in-process ASGI, full proxy vs direct upstream, distinct claims per pair",
        "samples_per_arm": samples,
        "warmup_per_arm": LATENCY_WARMUP,
        "raw": latency_quantiles(raw_times),
        "proxy": latency_quantiles(proxy_times),
        "paired_overhead": latency_quantiles(paired_overhead),
    }


def plot_calibration(calibration: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 5), layout="constrained")
    ax.plot([0, 1], [0, 1], "--", color="0.5", label="Perfect calibration")
    for i, bucket in enumerate(calibration["bins"]):
        lower, upper = bucket["lower"], bucket["upper"]
        ax.axvspan(lower, upper, color="0.92", alpha=0.6 if i % 2 == 0 else 0)
        if bucket["count"]:
            mean, correct = bucket["mean_trust"], bucket["actual_correctness"]
            ax.scatter(mean, correct, color="#126479", zorder=3)
            near_right = mean > 0.85
            ax.annotate(
                f"n={bucket['count']}",
                (mean, correct),
                xytext=(-6 if near_right else 6, -14 if correct > 0.9 else 7),
                textcoords="offset points",
                ha="right" if near_right else "left",
            )
    ax.set(
        xlim=(0, 1),
        ylim=(0, 1),
        xlabel="Mean reported trust score within bin",
        ylabel="Fraction of claims supported by FEVER",
        title=f"VeriAlign trust calibration  •  ECE {calibration['ece']}",
        xticks=[i / 5 for i in range(6)],
    )
    ax.legend(loc="lower right")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=170)
    plt.close(fig)


def compare(result: dict, baseline: dict) -> dict:
    if (
        result["dataset_sha256"] != baseline["dataset_sha256"]
        or result["profile"] != baseline["profile"]
    ):
        raise ValueError("Compare runs with the same dataset and evaluation profile")
    current, prior = result["latency"], baseline["latency"]
    if (
        current["samples_per_arm"] != prior["samples_per_arm"]
        or current["warmup_per_arm"] != prior["warmup_per_arm"]
        or current["transport"] != prior["transport"]
    ):
        raise ValueError("Compare latency with the same sample count and transport")
    ece = result["trust_calibration"]["ece"]
    prior_ece = baseline["trust_calibration"]["ece"]
    return {
        "labels": {
            label: {
                metric: round(scores[metric] - baseline["labels"][label][metric], 6)
                for metric in ("precision", "recall", "f1")
            }
            for label, scores in result["labels"].items()
        },
        "ece": round(ece - prior_ece, 6) if ece is not None and prior_ece is not None else None,
        "paired_overhead_ms": {
            p: round(value - prior["paired_overhead"][p], 6)
            for p, value in current["paired_overhead"].items()
        },
    }


async def run(dataset: Path, samples: int) -> dict:
    data = dataset.read_bytes()
    rows = [json.loads(line) for line in data.splitlines() if line.strip()]
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Expected a nonempty dataset with unique IDs")
    package_dir = Path(verialign.__file__).resolve().parent
    source_hash = hashlib.sha256()
    for file in sorted(package_dir.rglob("*.py")):
        source_hash.update(file.relative_to(package_dir).as_posix().encode() + b"\0")
        source_hash.update(hashlib.sha256(file.read_bytes()).digest())
    return {
        "dataset_sha256": hashlib.sha256(data).hexdigest(),
        "source_sha256": source_hash.hexdigest(),
        "profile": PROFILE,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "sqlite": sqlite3.sqlite_version,
            **{
                package: version(package)
                for package in ("fastapi", "starlette", "httpx", "pydantic")
            },
        },
        **await evaluate(rows),
        "latency": await measure_latency(samples),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plot", type=Path, help="Write a calibration plot (requires matplotlib)")
    parser.add_argument("--latency-samples", type=int, default=100)
    parser.add_argument("--compare", type=Path, help="Report deltas from a saved baseline")
    args = parser.parse_args()
    if args.latency_samples < 1:
        parser.error("--latency-samples must be positive")
    if args.compare and args.output and args.compare.resolve() == args.output.resolve():
        parser.error("--output must differ from the comparison baseline")
    result = asyncio.run(run(args.dataset, args.latency_samples))
    if args.compare:
        result["delta_from_baseline"] = compare(result, json.loads(args.compare.read_bytes()))
    if args.plot:
        plot_calibration(result["trust_calibration"], args.plot)
    serialized = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
