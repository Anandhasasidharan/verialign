import asyncio
import time
import statistics
from dataclasses import dataclass
from typing import List

import httpx


@dataclass
class BenchmarkResult:
    total_requests: int
    successful: int
    failed: int
    latencies_ms: List[float]
    min_latency_ms: float
    max_latency_ms: float
    mean_latency_ms: float
    median_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    requests_per_second: float


async def run_benchmark(
    base_url: str = "http://127.0.0.1:8000",
    num_requests: int = 100,
    concurrency: int = 10,
    use_demo: bool = True,
) -> BenchmarkResult:
    latencies = []
    successful = 0
    failed = 0

    semaphore = asyncio.Semaphore(concurrency)

    async def make_request(session: httpx.AsyncClient, request_id: int):
        nonlocal successful, failed
        payload = {
            "model": "demo" if use_demo else "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": f"Test request {request_id}"}],
            "metadata": {
                "context": [
                    {
                        "id": "doc-1",
                        "text": "This is a test context for benchmarking VeriAlign performance.",
                    }
                ]
            },
            "temperature": 0.7,
            "max_tokens": 100,
        }

        async with semaphore:
            start = time.perf_counter()
            try:
                response = await session.post(
                    f"{base_url}/v1/chat/completions", json=payload, timeout=30.0
                )
                elapsed = (time.perf_counter() - start) * 1000
                if response.status_code == 200:
                    successful += 1
                    latencies.append(elapsed)
                else:
                    failed += 1
                    print(
                        f"Request {request_id} failed: {response.status_code} - {response.text}"
                    )
            except Exception as e:
                failed += 1
                print(f"Request {request_id} error: {e}")

    async with httpx.AsyncClient() as session:
        tasks = [make_request(session, i) for i in range(num_requests)]
        await asyncio.gather(*tasks)

    if not latencies:
        return BenchmarkResult(
            total_requests=num_requests,
            successful=0,
            failed=num_requests,
            latencies_ms=[],
            min_latency_ms=0,
            max_latency_ms=0,
            mean_latency_ms=0,
            median_latency_ms=0,
            p95_latency_ms=0,
            p99_latency_ms=0,
            requests_per_second=0,
        )

    latencies.sort()
    total_time = sum(latencies) / 1000

    return BenchmarkResult(
        total_requests=num_requests,
        successful=successful,
        failed=failed,
        latencies_ms=latencies,
        min_latency_ms=min(latencies),
        max_latency_ms=max(latencies),
        mean_latency_ms=statistics.mean(latencies),
        median_latency_ms=statistics.median(latencies),
        p95_latency_ms=latencies[int(len(latencies) * 0.95)],
        p99_latency_ms=latencies[int(len(latencies) * 0.99)],
        requests_per_second=successful / total_time if total_time > 0 else 0,
    )


def print_results(result: BenchmarkResult):
    print("\n" + "=" * 60)
    print("VERIALIGN BENCHMARK RESULTS")
    print("=" * 60)
    print(f"Total Requests:     {result.total_requests}")
    print(f"Successful:         {result.successful}")
    print(f"Failed:             {result.failed}")
    print(f"Success Rate:       {result.successful / result.total_requests * 100:.1f}%")
    print("-" * 60)
    print(f"Min Latency:        {result.min_latency_ms:.2f} ms")
    print(f"Max Latency:        {result.max_latency_ms:.2f} ms")
    print(f"Mean Latency:       {result.mean_latency_ms:.2f} ms")
    print(f"Median Latency:     {result.median_latency_ms:.2f} ms")
    print(f"P95 Latency:        {result.p95_latency_ms:.2f} ms")
    print(f"P99 Latency:        {result.p99_latency_ms:.2f} ms")
    print(f"Requests/second:    {result.requests_per_second:.2f}")
    print("=" * 60)


async def main():
    import sys

    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    num_requests = int(sys.argv[2]) if len(sys.argv) > 2 else 100
    concurrency = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    print(f"Benchmarking {base_url}")
    print(f"Requests: {num_requests}, Concurrency: {concurrency}")

    result = await run_benchmark(base_url, num_requests, concurrency)
    print_results(result)


if __name__ == "__main__":
    asyncio.run(main())
