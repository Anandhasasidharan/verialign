"""Measure concurrent loopback proxy requests with OTLP on, off, and failing."""

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
from collections import Counter
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock, Thread
from time import perf_counter

import httpx

from eval.metrics import latency_quantiles
from eval.run_eval import CHAT_PATH
from verialign.scripts.demo import DOC


class Collector(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), CollectorHandler)
        self.failing = False
        self.received = Counter()
        self.lock = Lock()


class CollectorHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers["Content-Length"]))
        with self.server.lock:
            status = 503 if self.server.failing else 200
            self.server.received[self.path, status] += 1
        self.send_response(status)
        self.send_header("Content-Type", "application/x-protobuf")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *_args) -> None:
        pass


@asynccontextmanager
async def proxy(directory: Path, telemetry: bool, collector: Collector):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OTEL_", "VERIALIGN_"))}
    env.update(
        PYTHONPATH=str(Path(__file__).resolve().parents[1]),
        PYTHONUNBUFFERED="1",
        VERIALIGN_USE_NLI="false",
        VERIALIGN_RATE_LIMIT_RPM="100000",
        VERIALIGN_RATE_LIMIT_TPM="10000000",
        VERIALIGN_DB_PATH=str(directory / f"traces-{telemetry}.sqlite3"),
        VERIALIGN_ENABLE_OTEL=str(telemetry).lower(),
        OTEL_EXPORTER_OTLP_ENDPOINT=f"http://127.0.0.1:{collector.server_port}",
        OTEL_EXPORTER_OTLP_TIMEOUT="1",
        OTEL_METRIC_EXPORT_INTERVAL="200",
        OTEL_BSP_SCHEDULE_DELAY="200",
    )
    with socket.socket() as listener, (directory / f"proxy-{telemetry}.log").open("w+") as log:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-m",
                "uvicorn",
                "verialign.proxy.main:app",
                "--fd",
                str(listener.fileno()),
                "--no-access-log",
            ],
            cwd=directory,
            env=env,
            pass_fds=(listener.fileno(),),
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            async with httpx.AsyncClient(
                base_url=f"http://127.0.0.1:{listener.getsockname()[1]}", timeout=15
            ) as client:
                async with asyncio.timeout(15):
                    while True:
                        if process.poll() is not None:
                            log.seek(0)
                            raise RuntimeError(f"Proxy failed to start\n{log.read()[-3000:]}")
                        try:
                            response = await client.get("/ready", timeout=0.4)
                            if response.is_success:
                                break
                        except httpx.RequestError:
                            pass
                        await asyncio.sleep(0.05)
                yield client
        finally:
            process.terminate()
            try:
                await asyncio.to_thread(process.wait, 15)
            except subprocess.TimeoutExpired:
                process.kill()
                await asyncio.to_thread(process.wait)


async def measure(client: httpx.AsyncClient, label: str, count: int, concurrency: int) -> dict:
    semaphore = asyncio.Semaphore(concurrency)

    async def send(index: int) -> tuple[float, int, str]:
        async with semaphore:
            payload = {
                "model": "demo",
                "messages": [{"role": "user", "content": "Summarize the project."}],
                "metadata": {"context": [{"id": f"{label}-{index}", "text": DOC}]},
            }
            start = perf_counter()
            response = await client.post(CHAT_PATH, json=payload)
            elapsed = (perf_counter() - start) * 1000
            response.raise_for_status()
            data = response.json()
            verification = data["verification"]
            if verification["status"] == "complete" and verification["trust_score"] != 0.7:
                raise RuntimeError("Completed verification returned an unexpected score")
            if not data["choices"][0]["message"]["content"].startswith(DOC):
                raise RuntimeError("Load request did not preserve the completion")
            return elapsed, response.status_code, verification["status"]

    await asyncio.gather(*(send(-(i + 1)) for i in range(concurrency)))
    start = perf_counter()
    results = await asyncio.gather(*(send(i) for i in range(count)))
    elapsed = perf_counter() - start
    return {
        **latency_quantiles(ms for ms, _, _ in results),
        "requests_per_second": round(count / elapsed, 3),
        "http_status": dict(Counter(status for _, status, _ in results)),
        "verification_status": dict(Counter(verification for _, _, verification in results)),
    }


async def wait_for_export(collector: Collector, status: int, previous: dict) -> dict:
    try:
        async with asyncio.timeout(8):
            while True:
                with collector.lock:
                    counts = {
                        kind: collector.received[f"/v1/{kind}", status]
                        for kind in ("traces", "metrics")
                    }
                if all(counts[k] > previous.get(k, 0) for k in counts):
                    return counts
                await asyncio.sleep(0.05)
    except TimeoutError as exc:
        raise RuntimeError(f"Collector did not see the expected HTTP {status}: {counts}") from exc


async def run(count: int, concurrency: int) -> dict:
    with TemporaryDirectory(prefix="verialign-otlp-load-") as tmp, Collector() as collector:
        thread = Thread(target=collector.serve_forever, daemon=True)
        thread.start()
        try:
            directory = Path(tmp)
            async with proxy(directory, False, collector) as client:
                off = await measure(client, "off", count, concurrency)
            async with proxy(directory, True, collector) as client:
                healthy = await measure(client, "healthy", count, concurrency)
                await wait_for_export(collector, 200, {})
                with collector.lock:
                    collector.failing = True
                outage = await measure(client, "outage", count, concurrency)
                await wait_for_export(collector, 503, {})
                with collector.lock:
                    previous = {
                        kind: collector.received[f"/v1/{kind}", 200]
                        for kind in ("traces", "metrics")
                    }
                    collector.failing = False
                recovery = await measure(client, "recovery", count, concurrency)
                await wait_for_export(collector, 200, previous)
            return {
                "transport": "loopback HTTP, single Uvicorn worker, demo upstream, SQLite",
                "concurrency": concurrency,
                "requests_per_arm": count,
                "warmups_per_arm": concurrency,
                "off": off,
                "healthy": healthy,
                "outage": outage,
                "recovery": recovery,
                "collector_requests": {
                    f"{path} HTTP {status}": requests
                    for (path, status), requests in sorted(collector.received.items())
                },
            }
        finally:
            await asyncio.to_thread(collector.shutdown)
            await asyncio.to_thread(thread.join)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=150)
    parser.add_argument("--concurrency", type=int, default=12)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1:
        parser.error("Requests and concurrency must be positive")
    result = asyncio.run(run(args.requests, args.concurrency))
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
